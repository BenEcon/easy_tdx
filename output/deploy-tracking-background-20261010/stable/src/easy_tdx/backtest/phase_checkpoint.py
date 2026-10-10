"""Data-only checkpoints for execution and equity phases of a frozen backtest."""

from __future__ import annotations

import hashlib
import math
from copy import deepcopy
from dataclasses import fields
from numbers import Real
from typing import Any

import numpy as np
import pandas as pd

from easy_tdx.backtest.bar_time import BAR_TIME_CONTRACT, time_key
from easy_tdx.backtest.types import Trade
from easy_tdx.checkpoints import CalculationJournal
from easy_tdx.computation import computation_checkpoint


def finite_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


class PhaseCheckpoint:
    """The journal also binds the full lossless input and executable version.

    Each consumer validates its entire phase state before calling used(). A
    completed phase is not a completed task; only the supervisor publishes it.
    """

    def __init__(
        self,
        journal: CalculationJournal,
        key: str,
        schema: str,
        frame: pd.DataFrame,
        records: list[dict[str, Any]],
        configuration: dict[str, Any],
        total: int,
    ) -> None:
        self.journal, self.key, self.total = journal, key, total
        self.header = {
            "schema": schema,
            "bar_time_contract": BAR_TIME_CONTRACT,
            "input_records": deepcopy(records),
            "configuration": deepcopy(configuration),
            "total": total,
            "columns": list(frame.columns),
            "dtypes": [str(dtype) for dtype in frame.dtypes],
            "frame_hash": hashlib.sha256(
                pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()
            ).hexdigest(),
        }

    def restore(self) -> tuple[int, dict[str, Any] | None]:
        saved = self.journal.restore(self.key)
        if saved is None:
            return 0, None
        if set(saved) != set(self.header) | {"completed_units", "state"} or any(
            saved[name] != value for name, value in self.header.items()
        ):
            raise ValueError("回测阶段检查点与输入或配置不匹配")
        count = saved["completed_units"]
        if type(count) is not int or not 1 <= count <= self.total:
            raise ValueError("回测阶段检查点位置无效")
        if not isinstance(saved["state"], dict):
            raise ValueError("回测阶段检查点状态无效")
        computation_checkpoint()
        return count, saved["state"]

    def used(self, count: int) -> None:
        computation_checkpoint()
        self.journal.used(self.key, count)

    def save(self, count: int, state: dict[str, Any]) -> None:
        computation_checkpoint()
        self.journal.save(self.key, {**self.header, "completed_units": count, "state": state})


def restore_order_state(
    state: dict[str, Any],
    completed: int,
    signals: list[dict[str, Any]],
    frame: pd.DataFrame,
    initial_cash: float,
    initial_position: float,
) -> tuple[float, float, list[Trade], list[dict[str, Any] | None]]:
    if set(state) != {"cash", "position", "processed"} or not all(
        finite_number(state[key]) for key in ("cash", "position")
    ):
        raise ValueError("成交检查点资金或持仓无效")
    processed = state["processed"]
    if not isinstance(processed, list) or len(processed) != completed:
        raise ValueError("成交检查点信号游标与记录不一致")
    dates = {time_key(value) for value in frame["datetime"]}
    trades = []
    cash, position = initial_cash, initial_position
    for index, item in enumerate(processed):
        if item is None:  # original unfilled/skipped signal, not a successful trade
            continue
        if (
            not isinstance(item, dict)
            or set(item) != {field.name for field in fields(Trade)}
            or item["direction"] != signals[index]["direction"]
            or type(item["rejected"]) is not bool
            or any(
                not finite_number(item[name])
                for name in ("size", "price", "commission", "slippage", "pnl", "cost_basis")
            )
            or item["pnl"] != 0
            or item["cost_basis"] != 0
        ):
            raise ValueError("成交检查点记录无效")
        try:
            valid_date = time_key(item["datetime"]) in dates
        except TypeError:
            valid_date = False
        if not valid_date:
            raise ValueError("成交检查点日期不在冻结行情中")
        trade = Trade(**item)
        trades.append(trade)
        if not trade.rejected:
            if trade.direction == "BUY":
                cash -= trade.size * trade.price + trade.commission + trade.slippage
                position += trade.size
            else:
                cash += trade.size * trade.price - trade.commission - trade.slippage
                position -= trade.size
    if cash != state["cash"] or position != state["position"]:
        raise ValueError("成交检查点现金/持仓与成交前缀不一致")
    return state["cash"], state["position"], trades, processed


def restore_equity_state(state: dict[str, Any], count: int, arrays: dict[str, Any]) -> None:
    if set(state) != set(arrays):
        raise ValueError("权益检查点字段不完整")
    restored = {}
    for name, target in arrays.items():
        values = state[name]
        if (
            not isinstance(values, list)
            or len(values) != count
            or any(
                not isinstance(value, np.generic)
                or value.dtype != target.dtype
                or not finite_number(value)
                for value in values
            )
        ):
            raise ValueError("权益检查点长度、数值或类型不一致")
        restored[name] = np.asarray(values, dtype=target.dtype)
    # Validate every vector before mutating any live array. Typed NumPy scalars
    # survive the journal codec exactly, including integer cash and signed zero.
    for name, target in arrays.items():
        target[:count] = restored[name]
