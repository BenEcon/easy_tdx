"""Call-local incremental search; identical choices to the v3 slice algorithm.

One cursor per source start shares lifecycle work across ends and candidates.
It advances only to the requested stop, copying each eligible prefix before
any later admission. Cached cuts never escape; each result owns its metadata.
The caller must supply a validated chain and leave it unchanged during the call.
No symbol/user/global cache, truncation, or natural-completion rule is introduced.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from easy_tdx.chanlun.expansion_regrouping import (
    _endpoints_consistent,
    _iter_trend_component_prefixes,
)
from easy_tdx.chanlun.types import XD

# Absolute cut positions plus three immutable-by-convention geometry snapshots.
Plan = tuple[int, int, list[dict[str, Any]]]


class _ComponentCursor:
    def __init__(self, items: list[XD], start: int) -> None:
        self.steps = _iter_trend_component_prefixes(items, start)
        self.frontier = start
        self.exhausted = False
        self.trends: dict[int, dict[str, Any]] = {}
        self.singles: dict[int, dict[str, Any]] = {}

    def get(self, stop: int, allow_trends: bool) -> dict[str, Any] | None:
        while self.frontier < stop and not self.exhausted:
            step = next(self.steps, None)
            if step is None:
                self.exhausted = True
                break
            self.frontier, summary = step
            if summary is not None:
                self.trends[self.frontier] = summary
                if len(summary["centre_chain"]) == 1:
                    self.singles[self.frontier] = {
                        key: value
                        for key, value in summary.items()
                        if key not in ("component_kind", "centre_chain")
                    }
        return (self.trends if allow_trends else self.singles).get(stop)


class ResearchPartitionSearch:
    def __init__(self, items: list[XD]) -> None:
        self.items = items
        self.components: dict[int, _ComponentCursor] = {}
        self.plans: dict[tuple[int, int], Plan | None] = {}

    def _component(self, start: int, stop: int, allow_trends: bool) -> dict[str, Any] | None:
        if start not in self.components:
            self.components[start] = _ComponentCursor(self.items, start)
        return self.components[start].get(stop, allow_trends)

    def _search(self, start: int, stop: int, allow_trends: bool) -> Plan | None:
        fallback = None
        # Preserve ascending cut order and endpoint-consistent precedence exactly.
        for first in range(start + 3, stop - 5):
            a = self._component(start, first, allow_trends)
            if a is None:
                continue
            for second in range(first + 3, stop - 2):
                b = self._component(first, second, allow_trends)
                if b is None:
                    continue
                c = self._component(second, stop, allow_trends)
                if c is None:
                    continue
                if a["direction"] != c["direction"] or a["direction"] == b["direction"]:
                    continue
                parts = [a, b, c]
                if max(p["low"] for p in parts) < min(p["high"] for p in parts):
                    if _endpoints_consistent(parts):
                        return first, second, parts
                    if fallback is None:
                        fallback = first, second, parts
        return fallback

    def partition(self, start: int, stop: int) -> list[dict[str, Any]] | None:
        if not 0 <= start <= stop <= len(self.items):
            raise ValueError("Partition bounds must lie inside the validated input")
        if stop - start < 9 or self.items[start].direction != self.items[stop - 1].direction:
            return None
        key = start, stop
        if key not in self.plans:
            original = self._search(start, stop, False)
            if original and _endpoints_consistent(original[2]):
                self.plans[key] = original
            else:
                wider = self._search(start, stop, True)
                self.plans[key] = (
                    wider if wider and _endpoints_consistent(wider[2]) else original or wider
                )
        plan = self.plans[key]
        if plan is None:
            return None
        first, second, parts = plan
        bounds = start, first, second, stop
        return [
            {**deepcopy(part), "source_segment_indices": [self.items[i].index for i in range(a, b)]}
            for part, a, b in zip(parts, bounds[:-1], bounds[1:], strict=True)
        ]
