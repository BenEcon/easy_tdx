"""Cooperative computation boundaries, independent of HTTP and strategy rules.

Cancellation is not a strategy failure: it must bypass per-grid/per-symbol
``except Exception`` recovery and must never publish a partial ranking as done.
"""

from __future__ import annotations

import time
from _thread import LockType
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Literal


class ComputationStopped(BaseException):
    def __init__(self, reason: Literal["cancelled", "timed_out"]) -> None:
        self.reason = reason
        super().__init__("任务已取消" if reason == "cancelled" else "任务计算超时")


@dataclass
class ComputationControl:
    deadline: float | None = None
    event: Event = field(default_factory=Event)
    reason: Literal["cancelled", "timed_out"] | None = None
    _lock: LockType = field(default_factory=Lock)

    def request(self, reason: Literal["cancelled", "timed_out"] = "cancelled") -> None:
        with self._lock:
            if self.reason is None:
                self.reason = reason
            self.event.set()

    def observe_deadline(self) -> None:
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.request("timed_out")

    def check(self) -> None:
        self.observe_deadline()
        if self.event.is_set():
            raise ComputationStopped(self.reason or "cancelled")


_control: ContextVar[ComputationControl | None] = ContextVar(
    "tdx_computation_control", default=None
)


@contextmanager
def computation_scope(control: ComputationControl) -> Iterator[None]:
    token = _control.set(control)
    try:
        control.check()
        yield
        control.check()
    finally:
        _control.reset(token)


def computation_checkpoint() -> None:
    control = _control.get()
    if control is not None:
        control.check()
