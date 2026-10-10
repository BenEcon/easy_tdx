"""Independent subprocess ownership and observed-exit publication.

No API routes use this supervisor yet. Each instance only terminates handles it
created; it never kills an arbitrary PID from the database. Cold recovery holds
both the abandoned supervisor guard and its inherited attempt guard before
requeueing. Stale heartbeats alone cannot prove either process has stopped.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from easy_tdx.web.task_guard import GUARD_PROTOCOL, TaskGuard, UnsafeTaskGuard, guard_path
from easy_tdx.web.task_store import StaleTaskLease, TaskLease, TaskStore
from easy_tdx.web.task_version import execution_version


@dataclass(frozen=True)
class WorkerLimits:
    wall_seconds: float = 600
    cpu_seconds: int = 600
    stop_grace_seconds: float = 0.5
    address_space_bytes: int | None = 2 * 1024**3 if sys.platform == "linux" else None

    def __post_init__(self) -> None:
        for value in (self.wall_seconds, self.stop_grace_seconds):
            if (
                not isinstance(value, int | float)
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError("工作进程时间预算必须为有限正数")
        if type(self.cpu_seconds) is not int or self.cpu_seconds <= 0:
            raise ValueError("工作进程 CPU 预算必须为正整数")
        if self.address_space_bytes is not None and (
            type(self.address_space_bytes) is not int or self.address_space_bytes <= 0
        ):
            raise ValueError("工作进程地址空间预算必须为正整数")


@dataclass
class _Running:
    lease: TaskLease
    process: subprocess.Popen[bytes]
    owner: str
    started: float
    stopping: float | None = None
    terminated: bool = False


def _owner_active(owner: str) -> bool:
    from easy_tdx.web.account_store import get_account_store

    user = get_account_store().get_user(owner)
    return user is not None and user.active


class TaskSupervisor:
    def __init__(
        self,
        store: TaskStore,
        *,
        limits: WorkerLimits | None = None,
        owner_active: Callable[[str], bool] = _owner_active,
    ) -> None:
        if sys.platform == "win32":
            raise RuntimeError("独立任务资源限制尚不支持 Windows；不能静默跳过限制")
        self.store = store
        self.limits = limits or WorkerLimits()
        self.version = execution_version()
        self.worker_id = uuid.uuid4().hex
        self._owner_active = owner_active
        self._running: dict[str, _Running] = {}
        self._closed = False
        self.recovery_issues: dict[str, str] = {}
        guard = TaskGuard.acquire(guard_path(store.path, self.worker_id), create=True)
        assert guard is not None
        self._guard = guard

    @property
    def active_count(self) -> int:
        return len(self._running)

    def _authorized(self, owner: str) -> bool:
        try:
            return self._owner_active(owner) is True
        except Exception:
            return False

    def _spawn(self, lease: TaskLease, owner: str) -> None:
        guard = TaskGuard.acquire(guard_path(self.store.path, self.worker_id, lease), create=True)
        assert guard is not None
        try:
            self.store.mark_guard_ready(lease)
            self._spawn_guarded(lease, owner, guard)
        finally:
            # Child inherits the lock *at spawn*, before any bootstrap/heartbeat.
            guard.close()

    def _spawn_guarded(self, lease: TaskLease, owner: str, guard: TaskGuard) -> None:
        environment = os.environ.copy()
        # Applied before Python/NumPy import; the queue owns compute concurrency.
        for key in (
            "OPENBLAS_NUM_THREADS",
            "OMP_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS",
        ):
            environment[key] = "1"
        bootstrap: dict[str, Any] = {
            "path": str(self.store.path.resolve()),
            "version": self.version,
            "lease": asdict(lease),
            "parent_pid": os.getpid(),
            "cpu_seconds": self.limits.cpu_seconds,
            "address_space_bytes": self.limits.address_space_bytes,
            "guard_fd": guard.fd,
        }
        message = json.dumps(bootstrap).encode() + b"\n"
        if len(message) > 8192:
            self.store.finish_after_exit(lease, error="工作进程启动消息过大，未启动计算")
            return
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "easy_tdx.web.task_worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=environment,
                close_fds=True,
                pass_fds=(guard.fd,),
                bufsize=0,
            )
        except OSError:
            self.store.finish_after_exit(lease, error="无法启动独立工作进程，未开始计算")
            return
        self._running[lease.task_id] = _Running(lease, process, owner, time.monotonic())
        try:
            assert process.stdin is not None
            if process.stdin.write(message) != len(message):
                raise OSError("incomplete bootstrap")
        except OSError:
            # Keep the handle and slot until poll confirms the exit.
            process.terminate()

    def recover(self) -> int:
        """Requeue abandoned work only with two independent OS liveness proofs.

        An unknown prior exit code cannot publish a staged success. Recovered
        work uses its frozen input and validated checkpoints where supported;
        cancellation/timeout remains final.
        Legacy attempts or damaged guard evidence are deliberately not reclaimed.
        """
        if self._closed:
            raise RuntimeError("任务监督器已关闭")
        recovered = 0
        self.recovery_issues = {}
        for lease in self.store.leased_tasks():
            if lease.worker_id == self.worker_id:
                continue
            owner_guard: TaskGuard | None = None
            attempt_guard: TaskGuard | None = None
            try:
                protocol, _ = self.store.guard_state(lease)
                if protocol != GUARD_PROTOCOL:
                    self.recovery_issues[lease.task_id] = "旧执行无存活证明，未自动重新计算"
                    continue
                owner_guard = TaskGuard.acquire(guard_path(self.store.path, lease.worker_id))
                if owner_guard is None:
                    continue
                # Fence again under the owner's lock; another recovery may have
                # finished since we took the initial metadata snapshot.
                protocol, ready = self.store.guard_state(lease)
                if protocol != GUARD_PROTOCOL:
                    continue
                try:
                    attempt_guard = TaskGuard.acquire(
                        guard_path(self.store.path, lease.worker_id, lease)
                    )
                    if attempt_guard is None:
                        self.recovery_issues[lease.task_id] = "旧计算仍持有执行锁，等待实际退出"
                        continue
                except FileNotFoundError:
                    if ready:
                        raise UnsafeTaskGuard("已启动代次的执行锁缺失，拒绝推断退出") from None
                    # Owner is dead and ready was never committed: protocol
                    # guarantees Popen could not yet have been called.
                self.store.requeue_after_exit(lease, reason="supervisor_lost")
                recovered += 1
            except StaleTaskLease:
                continue
            except (OSError, UnsafeTaskGuard):
                self.recovery_issues[lease.task_id] = "执行存活证据缺失或异常，未自动重新计算"
            finally:
                if attempt_guard is not None:
                    attempt_guard.close()
                if owner_guard is not None:
                    owner_guard.close()
        return recovered

    def step(self, *, admit: bool = True) -> None:
        if self._closed:
            raise RuntimeError("任务监督器已关闭")
        self.recover()
        for task_id, running in list(self._running.items()):
            process = running.process
            if not self._authorized(running.owner):
                self.store.cancel(running.owner, task_id)
            if time.monotonic() - running.started >= self.limits.wall_seconds:
                self.store.request_timeout(running.lease)
            exit_code = process.poll()
            if exit_code is not None:
                self.store.finish_staged_after_exit(running.lease, exit_code)
                if process.stdin is not None:
                    process.stdin.close()
                del self._running[task_id]
                continue
            reason = self.store.heartbeat(running.lease)
            if reason is not None:
                if running.stopping is None:
                    running.stopping = time.monotonic()
                elapsed = time.monotonic() - running.stopping
                if elapsed >= 2 * self.limits.stop_grace_seconds:
                    process.kill()
                elif elapsed >= self.limits.stop_grace_seconds and not running.terminated:
                    process.terminate()
                    running.terminated = True
        if admit:
            for _ in range(self.store.limits.executing - len(self._running)):
                lease = self.store.claim(
                    self.version, self.worker_id, guard_protocol=GUARD_PROTOCOL
                )
                if lease is None:
                    break
                owner = self.store.lease_owner(lease)
                if not self._authorized(owner):
                    self.store.cancel(owner, lease.task_id)
                    self.store.requeue_after_exit(lease)  # No process was started.
                    continue
                self._spawn(lease, owner)

    def close(self) -> None:
        """Stop only owned children; retain running state if exit is unproven."""
        if self._closed:
            return
        failures: list[Exception] = []
        for task_id, running in list(self._running.items()):
            process = running.process
            try:
                if not self._authorized(running.owner):
                    self.store.cancel(running.owner, task_id)
                if time.monotonic() - running.started >= self.limits.wall_seconds:
                    self.store.request_timeout(running.lease)
            except StaleTaskLease:
                pass
            except Exception as exc:
                failures.append(exc)
            # Database failures must not prevent stopping a known owned child.
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            except Exception as exc:
                failures.append(exc)
                continue
            assert process.returncode is not None
            try:
                if process.returncode == 0:
                    self.store.finish_staged_after_exit(running.lease, process.returncode)
                else:
                    # Preserve checkpoints; only the algorithm can validate/use them.
                    self.store.requeue_after_exit(running.lease)
            except StaleTaskLease:
                pass  # Do not modify the newer generation; this child is dead.
            except Exception as exc:
                failures.append(exc)
                continue  # Keep the observed-dead handle for a bookkeeping retry.
            if process.stdin is not None:
                process.stdin.close()
            del self._running[task_id]
        self._closed = not self._running
        if self._closed:
            self._guard.close()
        if failures:
            raise RuntimeError("关闭任务服务未完成，未释放未经确认的任务名额") from failures[0]
