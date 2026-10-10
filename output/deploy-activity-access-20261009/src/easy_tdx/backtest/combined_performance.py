"""Shared valuation and performance for independently funded strategy slots."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from easy_tdx.backtest.performance import PerformanceAnalyzer
from easy_tdx.backtest.types import BacktestResult
from easy_tdx.backtest.valuation import CONTRACT, common_samples, observations


def combine_equity(
    results: dict[str, BacktestResult], allocations: dict[str, float]
) -> pd.DataFrame:
    columns = ["datetime", "total", "drawdown", "drawdown_pct"]
    series: dict[str, pd.Series] = {}
    normalize = any(
        result.config.get("performance_basis", {}).get("category_source", "legacy_daily_default")
        != "legacy_daily_default"
        for result in results.values()
    )
    for key, result in results.items():
        curve = observations(result, normalize_legacy=normalize)
        if curve.empty:
            continue
        if not np.isfinite(curve.total.to_numpy(dtype=float)).all():
            raise ValueError(f"组合成员 {key} 存在非有限净值，不能以沿用估值掩盖")
        index = pd.DatetimeIndex(curve.datetime)
        series[key] = pd.Series(curve.total.to_numpy(), index=index)
    if not series:
        return pd.DataFrame(columns=columns)
    aligned = pd.concat(series, axis=1).sort_index().ffill()
    # A slot not started yet still holds its allocated cash. Zero would create
    # fictitious deposits and gains when its first observation arrives.
    for key, cash in allocations.items():
        aligned[key] = aligned[key].fillna(cash) if key in aligned else cash
    total = aligned.sum(axis=1)
    peak = total.cummax()
    drawdown = peak - total
    return pd.DataFrame(
        {
            "datetime": total.index,
            "total": total.to_numpy(),
            "drawdown": drawdown.to_numpy(),
            "drawdown_pct": (drawdown / peak.where(peak != 0, 1)).to_numpy(),
        }
    ).reset_index(drop=True)


def aggregate_performance(
    results: dict[str, BacktestResult], allocations: dict[str, float], curve: pd.DataFrame
) -> tuple[dict[str, float], dict[str, Any]]:
    bases = [result.config.get("performance_basis", {}) for result in results.values()]
    categories = {basis.get("input_category", "DAY") for basis in bases}
    category = next(iter(categories)) if len(categories) == 1 else "DAY"
    source = curve.copy(deep=False)
    sampling_curve = None
    common_evidence: dict[str, Any] = {}
    if len(categories) > 1:
        sampling_curve, common_evidence = common_samples(results, allocations)
        category = common_evidence["sample_category"]
        source = sampling_curve.copy(deep=False)
    # Daily legacy library callers retain the declared legacy convention.
    explicit = any(basis.get("category_source") != "legacy_daily_default" for basis in bases)
    if explicit:
        source.attrs["snapshot_metadata"] = {
            "category": category,
            # The union has already been placed at actual valuation availability.
            "bar_time": "end",
        }
    trade_frames = []
    for key, result in results.items():
        if not result.trades.empty:
            frame = result.trades.copy()
            frame["performance_slot"] = key
            trade_frames.append(frame)
    trades = (
        pd.concat(trade_frames, ignore_index=True)
        if trade_frames
        else pd.DataFrame(columns=["direction", "pnl", "rejected"])
    )
    analyzer = PerformanceAnalyzer(curve, trades, source=source, sampling_curve=sampling_curve)
    metrics = analyzer.compute()
    # Analyzer maintains one FIFO queue per performance_slot; no cross-slot pairing
    # or zero substitution for unavailable member holding durations.
    metrics.update(total_stocks=float(len(results)), total_cash=sum(allocations.values()))
    basis: dict[str, Any] = dict(analyzer.basis)
    basis["valuation_policy"] = "initial_cash_then_last_observed_equity"
    basis["valuation_contract"] = CONTRACT
    if len(categories) > 1:
        reason = common_evidence.pop("unavailable_reason")
        basis.update(common_evidence)
        basis["observed_sample_count"] = basis["sample_count"] - len(basis["closed_period_samples"])
        if basis["closed_period_samples"]:
            basis["warnings"].append(
                f"含 {len(basis['closed_period_samples'])} 个交易所整周期休市估值，"
                "保留周期长度，各成员依据详见共同估值；不补造行情"
            )
        basis["input_category"] = "MIXED"
        basis["unavailable_reason"] = reason or basis["unavailable_reason"]
        basis["full_curve_bars"] = len(curve)
        basis["warnings"].append(
            "成员周期不同：年化仅使用最粗周期的共同已收盘估值；"
            "成员沿用最近已完成原生周期，非同期真实成交价。总收益和回撤保留完整估值并集。"
        )
    return metrics, basis
