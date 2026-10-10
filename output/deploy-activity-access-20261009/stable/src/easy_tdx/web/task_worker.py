"""Fixed subprocess entry point. Bootstrap arrives on a private parent pipe.

The pipe stays open for the parent's lifetime. No result is sent through stdout
and no pickle is accepted. The worker stages an outcome but cannot publish a
terminal status; the supervisor must first observe its exit.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any


def _parent_guard(parent_pid: int) -> None:
    if sys.platform == "linux":
        import ctypes

        # PR_SET_PDEATHSIG: even a native call holding the GIL cannot survive its
        # supervisor on Linux. Recheck ppid to close the setup/death race.
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "cannot install parent-death guard")
    if os.getppid() != parent_pid:
        raise RuntimeError("监督进程已退出")

    def watch_pipe() -> None:
        os.read(sys.stdin.fileno(), 1)
        os._exit(75)

    threading.Thread(target=watch_pipe, name="research-parent-guard", daemon=True).start()


def _limits(cpu_seconds: int, address_space_bytes: int | None) -> None:
    import resource

    def cap(kind: int, soft: int, hard: int) -> None:
        old_soft, old_hard = resource.getrlimit(kind)
        if old_hard != resource.RLIM_INFINITY:
            hard = min(hard, old_hard)
        if old_soft != resource.RLIM_INFINITY:
            soft = min(soft, old_soft)
        resource.setrlimit(kind, (min(soft, hard), hard))

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    cap(resource.RLIMIT_CPU, cpu_seconds, cpu_seconds + 1)
    if address_space_bytes is not None:
        cap(resource.RLIMIT_AS, address_space_bytes, address_space_bytes)


def _bootstrap() -> dict[str, Any]:
    raw = sys.stdin.buffer.readline(8193)
    if len(raw) > 8192 or not raw.endswith(b"\n"):
        raise ValueError("工作进程启动消息异常")
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {
        "path",
        "version",
        "lease",
        "parent_pid",
        "cpu_seconds",
        "address_space_bytes",
        "guard_fd",
    }:
        raise ValueError("工作进程启动字段异常")
    if any(not isinstance(data[key], str) or not data[key] for key in ("path", "version")):
        raise ValueError("工作进程启动路径或版本异常")
    for key in ("parent_pid", "cpu_seconds", "guard_fd"):
        if type(data[key]) is not int or data[key] <= 0:
            raise ValueError("工作进程预算或父进程标识异常")
    memory = data["address_space_bytes"]
    if memory is not None and (type(memory) is not int or memory <= 0):
        raise ValueError("工作进程地址空间预算异常")
    lease = data["lease"]
    if not isinstance(lease, dict) or set(lease) != {"task_id", "generation", "token", "worker_id"}:
        raise ValueError("工作进程执行凭据异常")
    if type(lease["generation"]) is not int or lease["generation"] < 1:
        raise ValueError("工作进程代次异常")
    if any(
        not isinstance(lease[key], str) or not lease[key]
        for key in ("task_id", "token", "worker_id")
    ):
        raise ValueError("工作进程执行凭据异常")
    return data


def main() -> int:
    data = _bootstrap()
    _parent_guard(data["parent_pid"])
    _limits(data["cpu_seconds"], data["address_space_bytes"])

    from easy_tdx.computation import ComputationControl, ComputationStopped, computation_scope
    from easy_tdx.web.task_dispatch import dispatch_task
    from easy_tdx.web.task_guard import GUARD_PROTOCOL, guard_path, verify_inherited_guard
    from easy_tdx.web.task_store import TaskLease, TaskStore
    from easy_tdx.web.task_version import execution_version

    store = TaskStore(Path(data["path"]))
    lease = TaskLease(**data["lease"])
    verify_inherited_guard(data["guard_fd"], guard_path(store.path, lease.worker_id, lease))
    if store.guard_state(lease) != (GUARD_PROTOCOL, True):
        raise ValueError("执行代次尚未持久化有效启动证明")
    # Keep the raw inherited descriptor until OS exit, including watcher errors
    # and interpreter shutdown. Never explicitly unlock it on return from main.
    control = ComputationControl()
    finished = threading.Event()

    def watch_stop() -> None:
        while not finished.wait(0.1):
            try:
                reason = store.heartbeat(lease)
                if reason == "cancelled":
                    control.request("cancelled")
                    return
                if reason == "timed_out":
                    control.request("timed_out")
                    return
            except Exception:
                # Lost store/lease: never continue computation unaccounted for.
                os._exit(74)

    watcher = threading.Thread(target=watch_stop, name="research-stop-guard", daemon=True)
    watcher.start()
    try:
        version = execution_version()
        if version != data["version"]:
            raise ValueError("工作进程源码或数值运行环境与冻结输入版本不一致")
        value = store.load_input(lease, execution_version=version)
        from easy_tdx.checkpoints import checkpoint_scope
        from easy_tdx.web.task_checkpoints import TaskCheckpoints

        with computation_scope(control), checkpoint_scope(TaskCheckpoints(store, lease, version)):
            result = dispatch_task(value)
        if execution_version() != version:
            raise ValueError("计算期间执行源码已变化，拒绝发布混合版本结果")
        store.stage_result(lease, result=result)
    except ComputationStopped:
        # The stop intent is already durable; publication waits for process exit.
        pass
    except Exception as exc:
        store.stage_result(lease, error=f"{type(exc).__name__}: {str(exc)[:800]}")
    finally:
        finished.set()
        watcher.join(timeout=6)
        if watcher.is_alive():
            return 74
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
