"""Per-task journal backed by the current fenced execution lease."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from easy_tdx.web.task_store import TaskLease, TaskStore

_PHASE_SCHEMAS = {
    "order_signals": "backtest-order-signals-v1",
    "pnl_trades": "backtest-pnl-trades-v1",
    "equity_bars": "backtest-equity-bars-v1",
}


class TaskCheckpoints:
    def __init__(self, store: TaskStore, lease: TaskLease, version: str) -> None:
        self.store, self.lease, self.version = store, lease, version
        self._used: dict[str, int] = {}
        state, self.fingerprint = store.load_checkpoint(lease, execution_version=version)
        if state is None:
            self.entries: dict[str, Any] = {}
        else:
            if (
                set(state) != {"contract", "entries"}
                or state["contract"] != "calculation-journal-v1"
                or not isinstance(state["entries"], dict)
                or any(
                    not isinstance(key, str) or not isinstance(value, dict)
                    for key, value in state["entries"].items()
                )
            ):
                raise ValueError("计算检查点结构或版本不兼容")
            self.entries = state["entries"]

    def restore(self, key: str) -> dict[str, Any] | None:
        value = self.entries.get(key)
        return deepcopy(value) if value is not None else None

    def save(self, key: str, state: dict[str, Any]) -> None:
        if not key or len(key) > 256:
            raise ValueError("检查点分区名无效")
        entries = {**self.entries, key: deepcopy(state)}
        phases = {
            unit: sum(
                value["completed_units"]
                for value in entries.values()
                if value.get("schema") == schema and type(value.get("completed_units")) is int
            )
            for unit, schema in _PHASE_SCHEMAS.items()
        }
        fingerprint = self.store.save_checkpoint(
            self.lease,
            {"contract": "calculation-journal-v1", "entries": entries},
            execution_version=self.version,
            previous_fingerprint=self.fingerprint,
            grid_points=sum(
                len(value["points"])
                for value in entries.values()
                if value.get("schema") == "optimizer-grid-v1"
                and isinstance(value.get("points"), list)
            ),
            scan_targets=sum(
                len(value["rows"])
                for value in entries.values()
                if value.get("schema") == "signal-scan-rows-v1"
                and isinstance(value.get("rows"), list)
            ),
            signal_bars=sum(
                value["completed_bars"]
                for value in entries.values()
                if value.get("schema") == "backtest-signal-bars-v1"
                and type(value.get("completed_bars")) is int
            ),
            order_signals=phases["order_signals"],
            pnl_trades=phases["pnl_trades"],
            equity_bars=phases["equity_bars"],
        )
        # A failed write leaves both the persisted and in-memory cursor unchanged.
        self.entries, self.fingerprint = entries, fingerprint

    def used(self, key: str, completed: int) -> None:
        if key in self._used or completed == 0:
            return
        if self.fingerprint is None or key not in self.entries:
            raise ValueError("不能声称复用不存在的检查点")
        schema = self.entries[key].get("schema")
        if schema == "backtest-signal-bars-v1":
            available = self.entries[key].get("completed_bars")
        elif schema in _PHASE_SCHEMAS.values():
            available = self.entries[key].get("completed_units")
        else:
            field = {"optimizer-grid-v1": "points", "signal-scan-rows-v1": "rows"}.get(schema)
            if field is None:
                raise ValueError("检查点不支持此类复用计数")
            points = self.entries[key].get(field)
            available = len(points) if isinstance(points, list) else None
        if (
            type(completed) is not int
            or type(available) is not int
            or not 0 < completed <= available
        ):
            raise ValueError("不能声称复用超出检查点的工作单元")
        used = {**self._used, key: completed}
        phases = {
            unit: sum(
                count for name, count in used.items() if self.entries[name].get("schema") == schema
            )
            for unit, schema in _PHASE_SCHEMAS.items()
        }
        self.store.checkpoint_used(
            self.lease,
            self.fingerprint,
            sum(
                count
                for name, count in used.items()
                if self.entries[name].get("schema") == "optimizer-grid-v1"
            ),
            scan_targets=sum(
                count
                for name, count in used.items()
                if self.entries[name].get("schema") == "signal-scan-rows-v1"
            ),
            signal_bars=sum(
                count
                for name, count in used.items()
                if self.entries[name].get("schema") == "backtest-signal-bars-v1"
            ),
            order_signals=phases["order_signals"],
            pnl_trades=phases["pnl_trades"],
            equity_bars=phases["equity_bars"],
        )
        self._used = used
