"""Fixed, data-only research dispatch. No network clients or saved live objects.

The input must already have been frozen and version-checked by the worker.
All-strategy optimization is serial *inside* this process; the shared queue,
not a nested process pool, controls parallelism across independent tasks.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from easy_tdx.computation import computation_checkpoint
from easy_tdx.web.backtest_schemas import (
    BacktestRequest,
    MultiStrategyBacktestRequest,
    OptimizeAllBacktestRequest,
    OptimizeBacktestRequest,
    PortfolioBacktestRequest,
    SignalScanRequest,
)
from easy_tdx.web.signal_scan import ScanTarget
from easy_tdx.web.task_payload import TaskInput


class _ScanTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    strategy_id: str
    strategy_name: str
    kind: str
    strategy: str
    strategy_label: str = ""
    params: dict[str, Any] = {}
    symbol: str = ""
    category: str = "DAY"
    error: str | None = None


def scan_task_input(
    version: str,
    request: SignalScanRequest,
    bars: dict[tuple[str, str], pd.DataFrame | None],
    targets: list[ScanTarget],
) -> TaskInput:
    frames: list[pd.DataFrame] = []
    keys: list[dict[str, Any]] = []
    for (symbol, category), frame in bars.items():
        keys.append(
            {
                "symbol": symbol,
                "category": category,
                "frame": len(frames) if frame is not None else None,
            }
        )
        if frame is not None:
            frames.append(frame)
    return TaskInput(
        "signal_scan",
        version,
        request.model_dump(),
        tuple(frames),
        {"bar_keys": keys, "targets": [asdict(target) for target in targets]},
    )


def _scan_data(
    value: TaskInput,
) -> tuple[dict[tuple[str, str], pd.DataFrame | None], list[ScanTarget]]:
    if set(value.context) != {"bar_keys", "targets"}:
        raise ValueError("雷达冻结上下文不完整")
    keys, targets = value.context["bar_keys"], value.context["targets"]
    if not isinstance(keys, list) or not isinstance(targets, list):
        raise ValueError("雷达冻结上下文格式错误")
    restored_targets = [
        ScanTarget(**_ScanTarget.model_validate(target).model_dump()) for target in targets
    ]
    target_keys = {(target.symbol, target.category) for target in restored_targets}
    restored: dict[tuple[str, str], pd.DataFrame | None] = {}
    references: set[int] = set()
    for key in keys:
        if not isinstance(key, dict) or set(key) != {"symbol", "category", "frame"}:
            raise ValueError("雷达行情映射格式错误")
        if not isinstance(key["symbol"], str) or not isinstance(key["category"], str):
            raise ValueError("雷达行情标的或周期格式错误")
        pair = (key["symbol"], key["category"])
        if pair in restored or pair not in target_keys:
            raise ValueError("雷达行情重复或与任务不匹配")
        index = key["frame"]
        if index is None:
            restored[pair] = None
        else:
            if type(index) is not int or not 0 <= index < len(value.frames):
                raise ValueError("雷达行情引用越界")
            references.add(index)
            restored[pair] = value.frames[index]
    if references != set(range(len(value.frames))) or any(
        not target.error and (target.symbol, target.category) not in restored
        for target in restored_targets
    ):
        raise ValueError("雷达冻结行情与子任务不完整对应")
    return restored, restored_targets


def _frame_count(value: TaskInput, count: int) -> None:
    if len(value.frames) != count:
        raise ValueError("冻结行情数量与任务不符，不能省略标的或改变分仓")


def dispatch_task(value: TaskInput) -> dict[str, Any]:
    from easy_tdx.backtest.multi_strategy_engine import StrategySlot
    from easy_tdx.backtest.portfolio_engine import StockData
    from easy_tdx.backtest.strategies import get_registry
    from easy_tdx.web.routers import backtest
    from easy_tdx.web.signal_scan import run_scan

    computation_checkpoint()
    if value.kind == "backtest":
        _frame_count(value, 1)
        request = BacktestRequest.model_validate(value.request)
        return backtest._run_backtest(value.frames[0], request)
    if value.kind == "portfolio":
        portfolio = PortfolioBacktestRequest.model_validate(value.request)
        _frame_count(value, len(portfolio.stocks))
        stocks = []
        for symbol, frame in zip(portfolio.stocks, value.frames, strict=True):
            market, code = symbol.split(":", 1)
            stocks.append(StockData(code=code, market=market, df=frame))
        return backtest._run_portfolio_backtest(stocks, portfolio)
    if value.kind == "multi_strategy":
        multi = MultiStrategyBacktestRequest.model_validate(value.request)
        _frame_count(value, len(multi.items))
        slots = []
        registry = get_registry()
        for item, frame in zip(multi.items, value.frames, strict=True):
            entry = registry.get(item.strategy)
            slots.append(
                StrategySlot(
                    label=item.strategy_label or entry.label,
                    symbol=item.symbol,
                    strategy=entry.build(item.params),
                    df=frame,
                )
            )
        return backtest._run_multi_strategy_backtest(slots, multi)
    if value.kind == "optimize":
        _frame_count(value, 1)
        optimize = OptimizeBacktestRequest.model_validate(value.request)
        return backtest._run_optimize(value.frames[0], optimize)
    if value.kind == "optimize_all":
        _frame_count(value, 1)
        all_strategies = OptimizeAllBacktestRequest.model_validate(value.request)
        return backtest._run_optimize_all(value.frames[0], all_strategies, process_budget=1)
    if value.kind == "signal_scan":
        scan = SignalScanRequest.model_validate(value.request)
        bars, targets = _scan_data(value)
        return run_scan(bars, targets, scan.window_bars)
    raise ValueError("未知登记任务种类，拒绝执行")
