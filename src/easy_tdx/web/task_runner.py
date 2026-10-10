"""回测后台任务执行器。

在进程内 ThreadPoolExecutor 上运行回测任务，通过 task_id 轮询结果。
不引入外部依赖（Celery/Redis），适合单机部署。

线程池使计算不直接阻塞 HTTP 事件循环，不保证 CPU 并行。
终态结果保存在内存，LRU 默认保留 100 条，重启即丢；持久化队列仍待实现。
活动任务另有全局与每账户配额，不因结果缓存淘汰。取消采用协作检查点：
运行中的原生调用或子进程必须实际退出后才能释放配额，不能伪装成已停止。
注册任务、提交 future、取消及结果发布持同一把锁，避免中途取消仍发布结果。
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from easy_tdx.web.task_payload import TaskInput

from easy_tdx.computation import ComputationControl, ComputationStopped, computation_scope
from easy_tdx.progress import progress_scope

logger = logging.getLogger(__name__)

TaskStatus = Literal["pending", "running", "cancelling", "done", "failed", "cancelled", "timed_out"]
ACTIVE_STATES = {"pending", "running", "cancelling"}


class TaskCapacityError(ValueError):
    """Reject work before it enters the executor's otherwise unbounded queue."""


# 结果表上限：超过后丢弃最旧的已完成/失败任务（LRU）。running 任务不会被淘汰。
# 每个全市场组合回测结果约几百 KB，100 条上限内存占用 < 100 MB。
_MAX_RESULTS = 100


@dataclass
class TaskState:
    """单个回测任务的状态快照。"""

    task_id: str
    status: TaskStatus = "pending"
    kind: str | None = None
    progress: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    # 供前端展示的描述（策略名 + 标的等），不参与业务逻辑
    description: str = ""
    owner_id: str | None = None
    frozen_input: tuple[bytes, str, str] | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 兼容字典（供轮询接口返回）。"""
        return {
            "task_id": self.task_id,
            "status": self.status,
            "kind": self.kind,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "description": self.description,
            "elapsed": (self.finished_at or time.time()) - (self.started_at or self.created_at),
        }


class BacktestTaskRunner:
    """回测任务执行器（全局单例）。

    Thread-safety: 所有对 ``self._tasks`` 的读写都在 ``self._lock`` 内。
    活动任务不会被缓存淘汰；工作线程安全退出前始终占用活动配额。
    """

    def __init__(
        self,
        max_workers: int = 4,
        max_results: int = _MAX_RESULTS,
        *,
        max_active: int = 16,
        max_per_owner: int = 3,
        max_task_seconds: float = 600,
        max_input_bytes: int = 128 * 1024 * 1024,
        max_owner_input_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        quotas = (
            max_workers,
            max_results,
            max_active,
            max_per_owner,
            max_input_bytes,
            max_owner_input_bytes,
        )
        if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in quotas):
            raise ValueError("任务配额必须为正整数")
        if not math.isfinite(max_task_seconds) or max_task_seconds <= 0:
            raise ValueError("任务配额与超时必须为正数")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="backtest-worker",
        )
        self._tasks: OrderedDict[str, TaskState] = OrderedDict()
        self._lock = Lock()
        self._max_results = max_results
        self._shutdown = False
        self._max_active = max_active
        self._max_per_owner = max_per_owner
        self._max_task_seconds = max_task_seconds
        self._max_input_bytes = max_input_bytes
        self._max_owner_input_bytes = max_owner_input_bytes
        self._controls: dict[str, ComputationControl] = {}
        self._futures: dict[str, Future[None]] = {}

    def submit(
        self,
        func: Callable[[], dict[str, Any]],
        *,
        description: str = "",
        owner_id: str | None = None,
        frozen_input: tuple[bytes, str, str] | None = None,
        kind: str | None = None,
    ) -> str:
        """Retain the HTTP admission through queued/running work, including cancellation."""
        from easy_tdx.web.resource_admission import retain_current_admission

        admission = retain_current_admission()

        def guarded() -> dict[str, Any]:
            if admission:
                admission.check()
            result = func()
            if admission:
                admission.check()
            return result

        try:
            return self._submit(
                guarded,
                description=description,
                owner_id=owner_id,
                on_finished=admission.release if admission else None,
                frozen_input=frozen_input,
                kind=kind,
            )
        except BaseException:
            if admission:
                admission.release()
            raise

    def _submit(
        self,
        func: Callable[[], dict[str, Any]],
        *,
        description: str,
        owner_id: str | None,
        on_finished: Callable[[], None] | None,
        frozen_input: tuple[bytes, str, str] | None = None,
        kind: str | None = None,
    ) -> str:
        """提交一个回测任务，立即返回 task_id。

        注册 task state 与提交 executor 在同一把锁内，避免任务在拿到 future
        前就被并发淘汰。

        Args:
            func: 无参可调用，返回 ``dict[str, Any]`` 形式的回测结果。
                内部异常会被捕获并记入 ``TaskState.error``。
            description: 任务描述（前端展示用）。

        Returns:
            task_id（uuid4 十六进制）。
        """
        task_id = uuid.uuid4().hex
        with self._lock:
            if self._shutdown:
                raise RuntimeError("任务执行器已关闭，拒绝提交")
            active = [s for s in self._tasks.values() if s.status in ACTIVE_STATES]
            if len(active) >= self._max_active:
                raise TaskCapacityError("计算队列已满，请等待现有任务结束后重试")
            if (
                owner_id is not None
                and sum(s.owner_id == owner_id for s in active) >= self._max_per_owner
            ):
                raise TaskCapacityError(f"每个账户最多同时保留 {self._max_per_owner} 个计算任务")
            if frozen_input is not None:
                self._reserve_input_locked(len(frozen_input[0]), owner_id)
            self._tasks[task_id] = TaskState(
                task_id=task_id,
                description=description,
                owner_id=owner_id,
                frozen_input=frozen_input,
                kind=kind,
            )
            # 提交 executor 也在锁内——避免「注册后被淘汰再提交」的窗口。
            # executor.submit 本身很快（入队即返回），不会显著持锁。
            self._controls[task_id] = ComputationControl()
            try:
                self._futures[task_id] = self._executor.submit(self._run, task_id, func)
                if on_finished:
                    self._futures[task_id].add_done_callback(lambda _future: on_finished())
            except BaseException:
                self._tasks.pop(task_id, None)
                self._controls.pop(task_id, None)
                raise
            self._evict_if_needed_locked()
        return task_id

    def _reserve_input_locked(self, size: int, owner: str | None) -> None:
        if size > min(self._max_input_bytes, self._max_owner_input_bytes):
            raise TaskCapacityError("单次原行情超过缓存容量，请减少扫描标的后重试")

        def used(states: list[TaskState]) -> int:
            return sum(len(s.frozen_input[0]) for s in states if s.frozen_input)

        active = [s for s in self._tasks.values() if s.status in ACTIVE_STATES]
        if (
            size + used(active) > self._max_input_bytes
            or size + used([s for s in active if s.owner_id == owner]) > self._max_owner_input_bytes
        ):
            raise TaskCapacityError("原任务行情缓存已满，请等待活动任务结束后重试")
        # Match the existing bounded in-memory result cache: evict terminal
        # records only. Never detach a running task or pretend it was cancelled.
        while True:
            states = list(self._tasks.values())
            own_full = (
                size + used([s for s in states if s.owner_id == owner])
                > self._max_owner_input_bytes
            )
            if not own_full and size + used(states) <= self._max_input_bytes:
                break
            key = next(
                tid
                for tid, s in self._tasks.items()
                if s.status not in ACTIVE_STATES
                and s.frozen_input
                and (not own_full or s.owner_id == owner)
            )
            self._tasks.pop(key)

    def completed_input(self, owner: str, task_id: str) -> tuple[TaskInput, dict[str, Any]]:
        from easy_tdx.web.task_payload import decode_task_input

        with self._lock:
            state = self._tasks.get(task_id)
            if state is None or state.owner_id != owner:
                raise KeyError("任务不存在")
            if state.status != "done" or state.result is None or state.frozen_input is None:
                raise ValueError("任务尚未成功完成或未保存原行情，不能作为原扫描复核")
            payload, version, fingerprint = state.frozen_input
            result = deepcopy(state.result)
        return decode_task_input(
            payload, execution_version=version, fingerprint=fingerprint
        ), result

    def get(self, task_id: str) -> TaskState:
        """取任务状态，不存在抛 KeyError。"""
        with self._lock:
            if task_id not in self._tasks:
                raise KeyError(f"未知任务 '{task_id}'")
            self._observe_deadline_locked(task_id)
            return self._tasks[task_id]

    def peek(self, task_id: str) -> TaskState | None:
        """取任务状态，不存在返回 None（不抛异常，便于轮询）。"""
        with self._lock:
            self._observe_deadline_locked(task_id)
            return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> TaskState:
        """Pending futures can stop immediately; running work retains its slot.

        A running job remains 'cancelling' until the worker actually exits. Native
        calls/child process pools may not reach a checkpoint immediately.
        """
        with self._lock:
            state = self._tasks[task_id]
            if state.status not in ACTIVE_STATES:
                return state
            control = self._controls[task_id]
            control.request()
            future = self._futures.get(task_id)
            if state.status == "pending" and future is not None and future.cancel():
                state.status = "cancelled"
                state.error = "任务已取消"
                state.finished_at = time.time()
                self._controls.pop(task_id, None)
                self._futures.pop(task_id, None)
                self._tasks.move_to_end(task_id)
                self._evict_if_needed_locked()
            else:
                state.status = "cancelling"
            return state

    def _observe_deadline_locked(self, task_id: str) -> None:
        control = self._controls.get(task_id)
        state = self._tasks.get(task_id)
        if control is not None and state is not None and state.status in ACTIVE_STATES:
            control.observe_deadline()
            if control.event.is_set():
                state.status = "cancelling"

    def list_recent(self, limit: int = 20, *, owner_id: str | None = None) -> list[TaskState]:
        """返回最近 N 个任务（按完成/创建时间倒序，LRU 表尾=最近）。

        Args:
            limit: 最多返回的任务数（默认 20）。
        """
        with self._lock:
            for task_id in self._controls:
                self._observe_deadline_locked(task_id)
            # OrderedDict 尾部是最近使用的（done 时 move_to_end）；倒序取
            items = list(reversed(self._tasks.values()))
            if owner_id is not None:
                items = [state for state in items if state.owner_id == owner_id]
            return items[:limit]

    def status(self, task_id: str) -> TaskStatus | None:
        """取任务状态字符串，不存在返回 None。"""
        state = self.peek(task_id)
        return state.status if state else None

    def shutdown(self, wait: bool = True) -> None:
        """关闭执行器（应用退出时调用）。

        取消排队中的 pending 任务，等待 running 任务完成（wait=True）。
        之后再 submit 会抛 RuntimeError。
        """
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            pending = [tid for tid, state in self._tasks.items() if state.status == "pending"]
        for task_id in pending:
            try:
                self.cancel(task_id)
            except KeyError:
                # A queued task can finish while shutdown is between these
                # locks, then be evicted from the terminal-only result cache.
                # Missing here therefore means there is nothing left to stop.
                pass
        self._executor.shutdown(wait=wait, cancel_futures=False)

    # ── 内部实现 ───────────────────────────────────────────────────────────────

    def _run(self, task_id: str, func: Callable[[], dict[str, Any]]) -> None:
        """在工作线程内执行：更新状态、跑任务、捕获异常。

        发布结果前再次检查控制状态，取消及超时不返回部分结果。
        """
        # 取本地引用；若已被淘汰则静默退出（无副作用）
        with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                logger.warning("任务 %s 在执行前已被淘汰，跳过", task_id)
                return
            state.status = "running"
            state.started_at = time.time()
            control = self._controls[task_id]
            control.deadline = time.monotonic() + self._max_task_seconds

        def publish(value: dict[str, Any]) -> None:
            with self._lock:
                control.check()
                state.progress = value

        try:
            with computation_scope(control), progress_scope(publish):
                result = func()
            with self._lock:
                # cancel() can win between the final checkpoint and acquiring
                # this lock. In that case no computed result may be published.
                control.check()
                # 即使被淘汰也写到本地 state（无害），move_to_end 容忍缺失
                state.result = result
                state.status = "done"
                state.finished_at = time.time()
                try:
                    self._tasks.move_to_end(task_id)
                except KeyError:
                    pass  # 已被淘汰，无需移动
        except ComputationStopped as exc:
            with self._lock:
                state.status = exc.reason
                state.error = str(exc)
                state.result = None
                state.finished_at = time.time()
                if task_id in self._tasks:
                    self._tasks.move_to_end(task_id)
        except Exception as exc:  # noqa: BLE001 — 故意宽口径，任务级兜底
            logger.exception("回测任务 %s 失败", task_id)
            with self._lock:
                control.observe_deadline()
                if control.reason is not None:
                    state.status = control.reason
                    state.error = str(ComputationStopped(control.reason))
                else:
                    state.error = f"{type(exc).__name__}: {exc}"
                    state.status = "failed"
                state.result = None
                state.finished_at = time.time()
                try:
                    self._tasks.move_to_end(task_id)
                except KeyError:
                    pass
        finally:
            with self._lock:
                self._controls.pop(task_id, None)
                self._futures.pop(task_id, None)
                self._evict_if_needed_locked()

    def _evict_if_needed_locked(self) -> None:
        """仅淘汰终态记录；排队、运行和取消中任务由独立活动配额约束。"""
        while sum(s.status not in ACTIVE_STATES for s in self._tasks.values()) > self._max_results:
            # 活动任务不能因为结果缓存容量不足而消失。
            evict_id: str | None = None
            for tid, st in self._tasks.items():
                if st.status not in ACTIVE_STATES:
                    evict_id = tid
                    break
            if evict_id is None:
                break  # 全部 running，暂时无法淘汰
            self._tasks.pop(evict_id, None)


# ── 全局单例 ───────────────────────────────────────────────────────────────────

_RUNNER: BacktestTaskRunner | None = None
_RUNNER_LOCK = Lock()


def get_runner() -> BacktestTaskRunner:
    """获取全局回测任务执行器单例（惰性初始化，线程安全）。"""
    global _RUNNER  # noqa: PLW0603 — 模块级单例
    if _RUNNER is None:
        with _RUNNER_LOCK:
            # double-checked locking：拿到锁后再确认一次，避免重复创建
            if _RUNNER is None:
                _RUNNER = BacktestTaskRunner()
    return _RUNNER


def shutdown_runner() -> None:
    """关闭全局执行器（应用退出时调用，幂等）。"""
    global _RUNNER  # noqa: PLW0603
    with _RUNNER_LOCK:
        if _RUNNER is not None:
            _RUNNER.shutdown()
            _RUNNER = None
