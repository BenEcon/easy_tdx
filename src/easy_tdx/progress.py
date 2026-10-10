"""Observed work units, not an ETA, checkpoint or completed task result."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from easy_tdx.computation import computation_checkpoint

PHASES = frozenset(
    {
        "factor_values",
        "factor_series",
        "factor_windows",
        "factor_composition",
        "redundancy",
        "time_validation",
        "archive",
        "result_validation",
    }
)
_sink: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar(
    "work_progress", default=None
)


class ProgressPublicationError(RuntimeError):
    """A task cannot quietly ignore loss of its execution accounting channel."""


def validate_progress(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "phase",
        "completed",
        "total",
        "detail",
        "sequence",
    }:
        raise ValueError("计算进度字段不完整")
    if (
        not isinstance(value["phase"], str)
        or value["phase"] not in PHASES
        or any(type(value[k]) is not int for k in ("completed", "total", "sequence"))
        or not 0 <= value["completed"] <= value["total"] <= 1_000_000
        or value["total"] < 1
        or not 1 <= value["sequence"] <= 1_000_000
        or not isinstance(value["detail"], str)
        or len(value["detail"]) > 96
    ):
        raise ValueError("计算进度单位或范围无效")
    return dict(value)


@contextmanager
def progress_scope(sink: Callable[[dict[str, Any]], None]) -> Iterator[None]:
    sequence = 0

    def publish(value: dict[str, Any]) -> None:
        nonlocal sequence
        sequence += 1
        sink(validate_progress({**value, "sequence": sequence}))

    token = _sink.set(publish)
    try:
        yield
    finally:
        _sink.reset(token)


def report_progress(phase: str, completed: int, total: int, detail: str = "") -> None:
    computation_checkpoint()
    sink = _sink.get()
    if sink is not None:
        try:
            sink({"phase": phase, "completed": completed, "total": total, "detail": detail})
        except Exception as exc:
            raise ProgressPublicationError(f"无法记录真实计算进度：{exc}") from exc
    computation_checkpoint()
