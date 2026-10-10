"""Complete signal-loop state at bar boundaries; never pickle a live strategy.

Indicators are rebuilt from frozen data, then explicit strategy state and engine
state are restored. Order execution/portfolio accounting still run from the
complete signal list: these checkpoints do not claim to resume those phases.
"""

from __future__ import annotations

import hashlib
import math
from copy import deepcopy
from dataclasses import asdict, fields
from numbers import Integral, Real
from typing import Any

import pandas as pd

from easy_tdx.backtest.bar_time import BAR_TIME_CONTRACT, time_key
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.backtest.types import Signal
from easy_tdx.checkpoints import CalculationJournal
from easy_tdx.computation import computation_checkpoint


def _number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


class SignalCheckpoint:
    def __init__(
        self,
        journal: CalculationJournal,
        key: str,
        strategy: Strategy,
        identity: dict[str, Any],
        frame: pd.DataFrame,
        configuration: dict[str, Any],
    ) -> None:
        self.journal, self.key, self.strategy = journal, key, strategy
        self.rows = len(frame)
        self.header = {
            "schema": "backtest-signal-bars-v1",
            "bar_time_contract": BAR_TIME_CONTRACT,
            "strategy": type(strategy).__module__ + "." + type(strategy).__qualname__,
            "identity": deepcopy(identity),
            "configuration": configuration,
            "rows": self.rows,
            "columns": list(frame.columns),
            "dtypes": [str(dtype) for dtype in frame.dtypes],
            # Secondary slot/shape guard; the journal independently binds the
            # entire lossless task input, provenance and execution version.
            "frame_hash": hashlib.sha256(
                pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()
            ).hexdigest(),
        }

    def restore(self) -> tuple[int, list[Signal], list[dict[str, Any]]]:
        saved = self.journal.restore(self.key)
        if saved is None:
            return 0, [], []
        required = {"completed_bars", "cash", "position", "signals", "stops", "state"}
        if set(saved) != set(self.header) | required or any(
            saved[name] != value for name, value in self.header.items()
        ):
            raise ValueError("回测逐根检查点与策略、行情或配置不匹配")
        count = saved["completed_bars"]
        if type(count) is not int or not 1 <= count <= self.rows:
            raise ValueError("回测逐根检查点位置无效")
        if not _number(saved["cash"]) or not _number(saved["position"]):
            raise ValueError("回测逐根检查点资金或持仓无效")
        if not isinstance(saved["state"], dict) or not isinstance(saved["stops"], list):
            raise ValueError("回测逐根检查点策略或止损状态无效")
        stops = saved["stops"]
        for stop in stops:
            if (
                not isinstance(stop, dict)
                or set(stop) != {"stop_loss", "take_profit"}
                or all(value is None for value in stop.values())
                or any(value is not None and not _number(value) for value in stop.values())
            ):
                raise ValueError("回测逐根检查点止损止盈条件无效")
        signals = saved["signals"]
        if not isinstance(signals, list):
            raise ValueError("回测逐根检查点信号列表无效")
        dates = self.strategy._datetime_array
        assert dates is not None
        allowed_dates = {time_key(date): index for index, date in enumerate(dates[:count])}
        previous: int | None = None
        restored: list[Signal] = []
        for item in signals:
            if (
                not isinstance(item, dict)
                or set(item) != {field.name for field in fields(Signal)}
                or not isinstance(item["datetime"], Integral | pd.Timestamp)
                or isinstance(item["datetime"], bool)
                or time_key(item["datetime"]) not in allowed_dates
                or (previous is not None and allowed_dates[time_key(item["datetime"])] < previous)
                or item["direction"] not in {"BUY", "SELL"}
                or not isinstance(item["source"], str)
                or not _number(item["size"])
                or any(
                    item[name] is not None and not _number(item[name])
                    for name in ("price", "stop_loss", "take_profit")
                )
            ):
                raise ValueError("回测逐根检查点信号内容或日期无效")
            previous = allowed_dates[time_key(item["datetime"])]
            restored.append(Signal(**item))
        computation_checkpoint()
        # Restore custom state only after all engine-owned fields validate.
        self.strategy.restore_checkpoint_state(deepcopy(saved["state"]))
        self.strategy._cash = saved["cash"]
        self.strategy._position_size = saved["position"]
        self.strategy._signals = []
        self.strategy._set_bar_index(count - 1)
        self.journal.used(self.key, count)
        return count, restored, stops

    def save(self, completed: int, signals: list[Signal], stops: list[Any]) -> None:
        computation_checkpoint()
        if self.strategy._signals:
            raise ValueError("信号队列未清空，不能保存未完成 bar")
        self.journal.save(
            self.key,
            {
                **self.header,
                "completed_bars": completed,
                "cash": self.strategy._cash,
                "position": self.strategy._position_size,
                "signals": [asdict(item) for item in signals],
                "stops": [asdict(item) for item in stops],
                "state": self.strategy.checkpoint_state(),
            },
        )
