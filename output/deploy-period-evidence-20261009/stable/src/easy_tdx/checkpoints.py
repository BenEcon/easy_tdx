"""Optional lossless calculation journals, independent of HTTP and storage.

The installed journal must bind state to the complete frozen input and execution
version. Algorithms validate their own state before consuming any saved result.
Saving is outside per-item error recovery: storage failure is not a skipped item.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Protocol


class CalculationJournal(Protocol):
    def restore(self, key: str) -> dict[str, Any] | None: ...

    def save(self, key: str, state: dict[str, Any]) -> None: ...

    def used(self, key: str, completed: int) -> None: ...


_journal: ContextVar[CalculationJournal | None] = ContextVar(
    "tdx_calculation_journal", default=None
)


def calculation_journal() -> CalculationJournal | None:
    return _journal.get()


@contextmanager
def checkpoint_scope(journal: CalculationJournal) -> Iterator[None]:
    token = _journal.set(journal)
    try:
        yield
    finally:
        _journal.reset(token)
