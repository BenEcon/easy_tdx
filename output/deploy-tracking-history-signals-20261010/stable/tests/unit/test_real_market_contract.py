"""Real frozen vendor bars through shared input and all five computation entry points.

No live network, no historical-vintage claim; one equity/strategy does not stand
in for the still-required stock/index/board and multi-timeframe acceptance matrix.
"""

import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from easy_tdx.backtest.multi_strategy_engine import StrategySlot
from easy_tdx.backtest.portfolio_engine import StockData
from easy_tdx.backtest.strategies import get_registry, presets
from easy_tdx.web.backtest_schemas import (
    BacktestRequest,
    MultiStrategyBacktestRequest,
    OptimizeAllBacktestRequest,
    OptimizeBacktestRequest,
    PortfolioBacktestRequest,
)
from easy_tdx.web.bar_snapshot import quality_report
from easy_tdx.web.market_data import load_equity_frame
from easy_tdx.web.routers import backtest
from easy_tdx.web.routers.bars import security_bars
from easy_tdx.web.trading_calendar import VERSION


@pytest.fixture
def market():
    path = Path(__file__).parents[1] / "fixtures/chanlun/600699-qfq-20260929.json"
    payload = json.loads(path.read_text())
    raw = json.dumps(payload["bars"], ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert hashlib.sha256(raw.encode()).hexdigest() == payload["bars_sha256"]
    return payload


def test_real_800_daily_bars_cover_calendar_and_a_removed_quote_is_not_a_holiday(market):
    original = market["bars"]
    report = quality_report(original, "DAY")
    assert len(original) == 800
    assert report["status"] == "ok"
    assert report["calendar_unverified_years"] == []
    assert report["missing_sessions"] == []
    shortened = [b for b in original if not b["datetime"].startswith("2023-06-21")]
    assert len(shortened) == 799
    report = quality_report(shortened, "DAY")
    assert report["missing_sessions"] == ["2023-06-21"]
    assert report["suspension_status"] == "not_verified"
    assert len(original) == 800


@pytest.mark.asyncio
async def test_frozen_vendor_chart_and_internal_input_have_identical_bars_and_fingerprint(market):
    frame = pd.DataFrame(market["bars"])
    frame["datetime"] = pd.to_datetime(frame["datetime"])
    standard, mac = AsyncMock(), AsyncMock()
    mac.get_stock_kline.return_value = frame
    internal = await load_equity_frame(standard, mac, "SH", "600699", "DAY", 0, 800, "QFQ")
    chart = await security_bars(
        market="SH",
        code="600699",
        category="DAY",
        start=0,
        count=800,
        adjust="QFQ",
        bar_time="native",
        client=standard,
        mac_client=mac,
    )
    meta = internal.attrs["snapshot_metadata"]
    assert meta["data_fingerprint"] == chart["metadata"]["data_fingerprint"]
    chart_frame = pd.DataFrame(chart["data"]).rename(columns={"date": "datetime"})
    chart_frame["datetime"] = pd.to_datetime(chart_frame["datetime"])
    pd.testing.assert_frame_equal(
        internal[frame.columns].reset_index(drop=True),
        chart_frame[frame.columns].reset_index(drop=True),
        check_exact=True,
    )
    assert meta["quality"]["status"] == "ok"
    assert meta["calendar_version"] == VERSION
    assert meta["historical_data_vintage"] is False
    standard.get_security_bars.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("remove_session", [False, True])
async def test_real_frozen_input_produces_same_metrics_across_five_workflows(
    market, monkeypatch, remove_session
):
    vendor = pd.DataFrame(market["bars"])
    vendor["datetime"] = pd.to_datetime(vendor["datetime"])
    if remove_session:
        vendor = vendor.loc[vendor.datetime != pd.Timestamp("2023-06-21")].copy()
    calls = []

    async def get(*args, **kwargs):
        start, count = args[3:5]
        calls.append(start)
        end = len(vendor) - start
        return vendor.iloc[max(0, end - count) : max(0, end)].copy()

    mac = AsyncMock()
    mac.get_stock_kline.side_effect = get
    frame = await backtest._history_frame(
        AsyncMock(), mac, "SH", "600699", "DAY", "QFQ", "2023-06-14", "2026-09-29"
    )
    assert calls == ([0] if remove_session else [0, 799, 0])
    assert pd.api.types.is_datetime64_any_dtype(frame.datetime)
    before = frame.copy(deep=True)
    symbol, strategy, params = "SH:600699", "ma_cross", {"fast": 5, "slow": 20}
    common = dict(strategy=strategy, symbol=symbol, category="DAY")
    single = backtest._run_backtest(frame, BacktestRequest(**common, params=params))
    portfolio = backtest._run_portfolio_backtest(
        [StockData("600699", "SH", frame)],
        PortfolioBacktestRequest(strategy=strategy, stocks=[symbol], category="DAY", params=params),
    )
    multi = backtest._run_multi_strategy_backtest(
        [StrategySlot("ma", symbol, get_registry().get(strategy).build(params), frame)],
        MultiStrategyBacktestRequest(items=[dict(**common, params=params)]),
    )
    grid = {key: [value] for key, value in params.items()}
    optimize = backtest._run_optimize(frame, OptimizeBacktestRequest(**common, param_grid=grid))
    monkeypatch.setattr(presets, "STRATEGY_PRESETS", {strategy: grid})
    all_result = backtest._run_optimize_all(
        frame,
        OptimizeAllBacktestRequest(symbol=symbol, category="DAY"),
        process_budget=1,
    )
    outputs = [single, portfolio, multi, optimize, all_result]
    fingerprints = []
    for output in outputs:
        evidence = output["data_provenance"]
        basis = evidence["performance_basis"]
        if remove_session:
            assert "缺少交易日" in basis["unavailable_reason"]
        else:
            assert basis["unavailable_reason"] is None
        assert basis["calendar_version"] == VERSION
        assert basis["observed_sample_count"] == 800 - int(remove_session)
        assert basis["return_count"] == 799 - int(remove_session)
        assert basis["missing_sessions"] == (["2023-06-21"] if remove_session else [])
        meta = evidence["datasets"][0]["metadata"]
        fingerprints.append(meta["data_fingerprint"])
        assert meta["quality"]["status"] == ("warning" if remove_session else "ok")
        assert meta["historical_data_vintage"] is False
        assert evidence["historical_data_vintage"] is False
    assert len(set(fingerprints)) == 1
    expected = single["performance"]
    for actual in [
        portfolio["total_performance"],
        multi["total_performance"],
        optimize["best"],
        all_result["best"],
    ]:
        for key in [
            "total_return",
            "sharpe",
            "max_drawdown",
            "total_trades",
            "win_rate",
            "profit_factor",
        ]:
            if expected[key] is None:
                assert actual[key] is None, key
            else:
                assert actual[key] == pytest.approx(expected[key]), key
    for actual in [portfolio["total_performance"], multi["total_performance"]]:
        for key, value in expected.items():
            assert actual[key] == pytest.approx(value) if value is not None else actual[key] is None
    pd.testing.assert_frame_equal(frame, before, check_exact=True)
    assert frame.attrs == before.attrs
