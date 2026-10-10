"""Frozen real stock inputs across all registered default strategies and consumers.

No network or synthetic price substitution. Singleton optimization grids prove
entry-point equality at defaults, not exhaustive parameter-space validation.
Indices and boards are not silently treated as tradable equities.
"""

from numbers import Integral, Real
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from easy_tdx.backtest import BacktestEngine
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
from easy_tdx.web.market_data import closed_frame, load_equity_frame
from easy_tdx.web.routers import backtest, research
from easy_tdx.web.signal_scan import ScanTarget, evaluate_signals, fetch_scan_bars
from tests.market_matrix import entries, load_case
from tests.unit.test_real_market_matrix import freeze_time

STOCKS = [row for row in entries() if row["instrument"]["kind"] == "stock"]
STRATEGIES = get_registry().names()
OPTIMIZED_METRICS = (
    "total_return",
    "sharpe",
    "max_drawdown",
    "total_trades",
    "win_rate",
    "profit_factor",
)


async def input_frame(entry, monkeypatch):
    freeze_time(entry, monkeypatch)
    _, vendor, _ = load_case(entry)
    mac = AsyncMock()
    mac.get_stock_kline.side_effect = lambda *args, **kwargs: vendor.copy(deep=True)
    frame = await load_equity_frame(
        AsyncMock(),
        mac,
        entry["instrument"]["market"],
        entry["code"],
        entry["category"],
        0,
        len(vendor),
        entry["adjust"],
    )
    return closed_frame(frame), mac


def equivalent(actual, expected):
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            equivalent(actual[key], expected[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected, strict=True):
            equivalent(left, right)
    elif isinstance(expected, Real) and not isinstance(expected, bool):
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-10)
    else:
        assert actual == expected


def signal_stamp(value):
    stamp = (
        pd.to_datetime(str(value), format="%Y%m%d")
        if isinstance(value, Integral)
        else pd.Timestamp(value)
    )
    return str(stamp)[:16]


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", STOCKS, ids=lambda row: row["id"])
@pytest.mark.parametrize("strategy", STRATEGIES)
async def test_all_default_strategies_agree_across_five_real_workflows(
    entry, strategy, monkeypatch
):
    frame, _ = await input_frame(entry, monkeypatch)
    before = frame.copy(deep=True)
    params = {param.name: param.default for param in get_registry().get(strategy).params}
    symbol = f"{entry['instrument']['market']}:{entry['code']}"
    common = dict(strategy=strategy, symbol=symbol, category=entry["category"], count=len(frame))
    single = backtest._run_backtest(frame, BacktestRequest(**common, params=params))
    portfolio = backtest._run_portfolio_backtest(
        [StockData(entry["code"], entry["instrument"]["market"], frame)],
        PortfolioBacktestRequest(
            strategy=strategy,
            stocks=[symbol],
            category=entry["category"],
            params=params,
        ),
    )
    multi = backtest._run_multi_strategy_backtest(
        [StrategySlot("strategy", symbol, get_registry().get(strategy).build(params), frame)],
        MultiStrategyBacktestRequest(items=[dict(**common, params=params)]),
    )
    grid = {key: [value] for key, value in params.items()}
    # The public heatmap contract has at most two varied parameters. Remaining
    # parameters still take the same registered defaults, not different values.
    public_grid = dict(list(grid.items())[:2])
    optimize = backtest._run_optimize(
        frame, OptimizeBacktestRequest(**common, param_grid=public_grid)
    )
    monkeypatch.setattr(presets, "STRATEGY_PRESETS", {strategy: grid})
    all_result = backtest._run_optimize_all(
        frame,
        OptimizeAllBacktestRequest(symbol=symbol, category=entry["category"], count=len(frame)),
        process_budget=1,
    )
    expected = single["performance"]
    for grouped in (portfolio, multi):
        assert set(grouped["total_performance"]) - set(expected) == {"total_stocks", "total_cash"}
        assert grouped["total_performance"]["total_stocks"] == 1
        assert grouped["total_performance"]["total_cash"] == 1_000_000
        equivalent({key: grouped["total_performance"][key] for key in expected}, expected)
        assert len(grouped["individual_results"]) == 1
        individual = next(iter(grouped["individual_results"].values()))
        equivalent(individual["trades"], single["trades"])
        equivalent(individual["equity_curve"], single["equity_curve"])
    for optimized in (optimize, all_result):
        assert optimized["best"] is not None
        assert set(optimized["best"]["metric_status"]) == set(OPTIMIZED_METRICS) - {"total_trades"}
        for key in OPTIMIZED_METRICS:
            equivalent(optimized["best"][key], expected[key])
            if key != "total_trades":
                assert (
                    optimized["best"]["metric_status"][key]
                    == single["config"]["performance_basis"]["metric_status"][key]
                )
    fingerprints = []
    for result in (single, portfolio, multi, optimize, all_result):
        proof = result["data_provenance"]
        basis = proof["performance_basis"]
        assert basis["input_category"] == entry["category"]
        assert basis["input_bars"] == len(frame)
        fingerprints.append(proof["datasets"][0]["metadata"]["data_fingerprint"])
        assert proof["historical_data_vintage"] is False
        if entry["category"] == "MONTH":
            assert len(frame) == 47
            assert basis["annual_periods"] == 12
        if entry["category"] == "MIN_30":
            assert basis["sample_category"] == "DAY"
    assert len(set(fingerprints)) == 1
    pd.testing.assert_frame_equal(frame, before, check_exact=True)
    assert frame.attrs == before.attrs


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", STOCKS, ids=lambda row: row["id"])
@pytest.mark.parametrize("strategy", STRATEGIES)
async def test_radar_default_strategy_signals_match_actual_engine_on_real_bars(
    entry, strategy, monkeypatch
):
    frame, mac = await input_frame(entry, monkeypatch)
    symbol = f"{entry['instrument']['market']}:{entry['code']}"
    target = ScanTarget(
        strategy_id="fixture",
        strategy_name=strategy,
        kind="single",
        strategy=strategy,
        symbol=symbol,
        category=entry["category"],
    )
    fetched = await fetch_scan_bars(AsyncMock(), [target, target], mac, adjust=entry["adjust"])
    scanned = fetched[(symbol, entry["category"])]
    assert scanned is not None
    pd.testing.assert_frame_equal(scanned, frame, check_exact=True)
    # One loader call above plus one deduplicated radar query, not one per target.
    assert mac.get_stock_kline.call_count == 2
    engine = BacktestEngine(
        strategy=get_registry().get(strategy).build(), cash=100_000, commission=0.0003
    )
    signals = engine._generate_signals(frame, None)
    radar = evaluate_signals(get_registry().get(strategy).build(), scanned, window=len(frame))
    expected = [
        {"date": signal_stamp(signal.datetime), "direction": signal.direction} for signal in signals
    ]
    assert radar["recent_signals"] == expected
    assert radar["last_bar_date"] == str(frame.datetime.iloc[-1])[:16]
    assert radar["last_close"] == frame.close.iloc[-1]
    assert target.error is None


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", STOCKS, ids=lambda row: row["id"])
async def test_real_factor_route_matches_direct_factor_engine_and_preserves_provenance(
    entry, monkeypatch
):
    from easy_tdx.factor import FactorEngine, list_factors

    frame, mac = await input_frame(entry, monkeypatch)
    requested = [item["name"] for item in list_factors()]
    batches = [requested[start : start + 10] for start in range(0, len(requested), 10)]
    for factors in batches:
        result = await research.factor_compute(
            research.FactorComputeRequest(
                market=entry["instrument"]["market"],
                code=entry["code"],
                category=entry["category"],
                # Keep short upstream monthly samples, never invent warm-up prices.
                count=max(60, entry["count"]),
                factors=factors,
            ),
            AsyncMock(),
            mac,
        )
        data = result.data
        expected = frame.copy(deep=True)
        errors = {}
        for name in factors:
            # The library's PE/PB placeholders return only NaN; the web contract
            # deliberately reports missing historical fundamentals instead of
            # pretending these are successfully computed valuation series.
            if name in {"pe_ratio", "pb_ratio"}:
                errors[name] = "尚未接入历史财务数据，不能计算此估值因子"
                continue
            try:
                expected = FactorEngine().compute_single(expected, [name])
            except Exception as exc:
                errors[name] = str(exc)
        assert data["errors"] == errors
        assert (
            data["metadata"]["data_fingerprint"]
            == frame.attrs["snapshot_metadata"]["data_fingerprint"]
        )
        assert data["metadata"]["historical_data_vintage"] is False
        assert data["input_count"] == len(frame)
        actual = pd.DataFrame(data["rows"])
        for name in factors:
            if name in errors:
                assert name not in actual.columns
            if name not in errors:
                pd.testing.assert_series_equal(
                    pd.to_numeric(actual[name]),
                    expected[name].tail(160).reset_index(drop=True),
                    check_names=False,
                    check_dtype=False,
                    check_exact=True,
                )


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", STOCKS, ids=lambda row: row["id"])
@pytest.mark.parametrize("strategy", STRATEGIES)
async def test_real_strategy_signals_do_not_change_with_future_prices(entry, strategy, monkeypatch):
    frame, _ = await input_frame(entry, monkeypatch)
    cut = len(frame) // 2
    visible = frame.iloc[:cut].copy(deep=True)
    changed = frame.copy(deep=True)
    changed.loc[changed.index[cut:], ["open", "high", "low", "close"]] *= 100
    changed.loc[changed.index[cut:], ["vol", "amount"]] *= 100
    cutoff = signal_stamp(visible.datetime.iloc[-1])

    def signals(data):
        engine = BacktestEngine(strategy=get_registry().get(strategy).build(), cash=100_000)
        return [
            (signal_stamp(sig.datetime), sig.direction, sig.size, sig.price, sig.source)
            for sig in engine._generate_signals(data, None)
            if signal_stamp(sig.datetime) <= cutoff
        ]

    assert signals(frame) == signals(visible) == signals(changed)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", STOCKS, ids=lambda row: row["id"])
async def test_real_factor_values_do_not_backfill_from_future_prices(entry, monkeypatch):
    from easy_tdx.factor import FactorEngine, list_factors

    frame, _ = await input_frame(entry, monkeypatch)
    cut = len(frame) // 2
    visible = frame.iloc[:cut].copy(deep=True)
    changed = frame.copy(deep=True)
    changed.loc[changed.index[cut:], ["open", "high", "low", "close", "vol", "amount"]] *= 100
    for factor in list_factors():
        name = factor["name"]
        values = []
        failures = []
        for data in (frame, visible, changed):
            try:
                values.append(FactorEngine().compute_single(data, [name])[name].iloc[:cut])
            except Exception as exc:
                failures.append(str(exc))
        if failures:
            assert len(failures) == 3
            assert len(set(failures)) == 1
        else:
            pd.testing.assert_series_equal(values[0], values[1], check_exact=True)
            pd.testing.assert_series_equal(values[0], values[2], check_exact=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_real_two_stock_risk_uses_only_common_observed_returns(monkeypatch, missing):
    current = next(row for row in STOCKS if row["category"] == "DAY" and row["code"] == "300750")
    older = next(row for row in entries() if row["code"] == "600699")
    freeze_time(current, monkeypatch)
    frames = {entry["code"]: load_case(entry)[1] for entry in (current, older)}
    removed = pd.Timestamp("2026-09-21")
    if missing:
        # Remove a real open-market date from both; alignment alone cannot see it.
        frames = {
            code: frame.loc[frame.datetime != removed].reset_index(drop=True)
            for code, frame in frames.items()
        }
    mac = AsyncMock()
    mac.get_stock_kline.side_effect = lambda market, code, *a, **k: frames[code].copy(deep=True)
    result = await research.portfolio_risk(
        research.PortfolioRiskRequest(
            stocks=[{"market": "SZ", "code": "300750"}, {"market": "SH", "code": "600699"}],
            method="equal",
            count=800,
        ),
        AsyncMock(),
        mac,
    )
    data = result.data
    prices = pd.concat(
        [frame.set_index("datetime").close.rename(code) for code, frame in frames.items()], axis=1
    ).sort_index()
    returns = prices.pct_change(fill_method=None)
    if missing:
        returns.loc[pd.Timestamp("2026-09-22")] = float("nan")
    returns = returns.dropna(how="any")
    assert data["observations"] == len(returns)
    assert data["alignment"]["start"] == str(returns.index[0])
    assert data["alignment"]["end"] == str(returns.index[-1])
    assert data["alignment"]["calendar_gap_returns"] == (["2026-09-22 00:00:00"] if missing else [])
    assert data["weights"] == {"300750": 0.5, "600699": 0.5}
    for asset in data["assets"]:
        assert asset["annual_return"] == pytest.approx(returns[asset["code"]].mean() * 252)
        assert asset["volatility"] == pytest.approx(returns[asset["code"]].std() * 252**0.5)
    assert {row["code"] for row in data["provenance"]} == {"300750", "600699"}
    assert all(row["metadata"]["historical_data_vintage"] is False for row in data["provenance"])
