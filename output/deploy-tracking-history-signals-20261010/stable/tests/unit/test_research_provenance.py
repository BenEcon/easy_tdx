"""Evidence is bound to actual inputs, before potentially mutating computation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from pydantic import ValidationError

from easy_tdx.web.backtest_schemas import (
    BacktestRequest,
    MultiStrategyBacktestRequest,
    MultiStrategyItem,
    OptimizeBacktestRequest,
    PortfolioBacktestRequest,
)
from easy_tdx.web.research_provenance import frame_evidence
from easy_tdx.web.routers import backtest


def records():
    return [
        dict(datetime=str(day.date()), open=10, high=12, low=9, close=11, vol=100, amount=1100)
        for day in pd.bdate_range("2026-08-03", periods=12)
    ]


@pytest.mark.parametrize(
    "dates",
    [
        {"start_date": "2026-02-30"},
        {"end_date": "20260803"},
        {"start_date": "2026-08-05", "end_date": "2026-08-03"},
    ],
)
def test_request_rejects_invalid_or_reversed_dates(dates):
    with pytest.raises(ValidationError):
        BacktestRequest(strategy="ma_cross", symbol="SZ:000001", **dates)


def test_inline_evidence_is_unverified_and_describes_filtered_input():
    frame = backtest._ohlcv_to_df(records(), category="DAY", adjust="QFQ")
    filtered = backtest._filter_df_by_date(frame, "2026-08-04", "2026-08-06")
    evidence = frame_evidence(
        filtered, category="DAY", adjust="QFQ", symbol="SZ:000001", label="example"
    )
    meta = evidence["metadata"]
    assert evidence["bar_count"] == 3
    assert meta["range_start"].startswith("2026-08-04")
    assert meta["range_end"].startswith("2026-08-06")
    assert meta["actual_adjust"] == "UNKNOWN"
    assert not meta["adjustment_verified"]
    assert meta["source_fingerprint"] != meta["data_fingerprint"]
    assert len(frame) == 12


@pytest.mark.parametrize("change", ["duplicate", "bad_ohlc", "nan"])
def test_inline_bad_data_never_enters_computation(change):
    rows = records()
    if change == "duplicate":
        rows[1]["datetime"] = rows[0]["datetime"]
    elif change == "bad_ohlc":
        rows[1]["high"] = 8
    else:
        rows[1]["close"] = float("nan")
    with pytest.raises(ValueError, match="质量检查"):
        backtest._ohlcv_to_df(rows)


def test_evidence_is_frozen_before_strategy_mutates_frame(monkeypatch):
    from easy_tdx.backtest import BacktestEngine

    frame = backtest._ohlcv_to_df(records())
    req = BacktestRequest(strategy="ma_cross", ohlcv=records())
    before = frame_evidence(
        frame, category=req.category, adjust=req.adjust, symbol=None, label=req.strategy
    )

    def mutate(self, df, *, checkpoint_key=None):
        assert checkpoint_key == "backtest/signals"
        df.loc[0, "close"] = 10
        req.params["mutation"] = True
        return SimpleNamespace(config={"performance_basis": {"test": True}})

    monkeypatch.setattr(BacktestEngine, "run", mutate)
    monkeypatch.setattr(backtest, "serialize_result", lambda result: {"config": result.config})
    result = backtest._run_backtest(frame, req)["data_provenance"]
    assert result["datasets"][0] == before
    assert result["request"]["params"] == {}
    assert "ohlcv" not in result["request"]


@pytest.mark.asyncio
async def test_optimize_date_range_uses_range_loader_not_single_page(monkeypatch):
    frame = pd.DataFrame(records())
    ranged = AsyncMock(return_value=frame)
    single = AsyncMock(side_effect=AssertionError("single page must not be used"))
    monkeypatch.setattr(backtest, "_history_frame", ranged)
    monkeypatch.setattr(backtest, "_fetch_bars", single)
    req = OptimizeBacktestRequest(
        strategy="ma_cross", param_grid={"fast": [5]}, symbol="SZ:000001", start_date="2026-08-03"
    )
    assert await backtest._optimize_input(None, None, req) is frame
    assert ranged.await_args.args[-2:] == ("2026-08-03", None)
    single.assert_not_awaited()


@pytest.mark.asyncio
async def test_inline_optimize_applies_requested_dates():
    req = OptimizeBacktestRequest(
        strategy="ma_cross",
        param_grid={"fast": [5]},
        ohlcv=records(),
        start_date="2026-08-04",
        end_date="2026-08-06",
    )
    result = await backtest._optimize_input(None, None, req)
    assert len(result) == 3
    assert result.datetime.iloc[-1] == pd.Timestamp("2026-08-06")


@pytest.mark.asyncio
async def test_optimize_range_retrieves_more_than_800_actual_bars():
    data = pd.DataFrame(
        [
            dict(records()[0], datetime=str(day.date()))
            for day in pd.bdate_range("2022-01-03", periods=900)
        ]
    )
    offsets = []

    async def get(*args, **kwargs):
        start, count = args[3:5]
        offsets.append(start)
        end = len(data) - start
        return data.iloc[max(0, end - count) : max(0, end)].copy()

    mac = AsyncMock()
    mac.get_stock_kline.side_effect = get
    req = OptimizeBacktestRequest(
        strategy="ma_cross",
        param_grid={"fast": [5]},
        symbol="SZ:000001",
        start_date="2022-01-03",
        end_date="2025-12-31",
    )
    frame = await backtest._optimize_input(None, mac, req)
    assert len(frame) == 900
    assert offsets == [0, 799, 0]
    assert frame.attrs["snapshot_metadata"]["page_count"] == 2


def test_minutes_same_day_and_explicit_unclosed_exclusion():
    rows = [
        dict(records()[0], datetime=f"2026-08-03 {stamp}", is_closed=closed)
        for stamp, closed in [("10:00:00", True), ("10:30:00", True), ("11:00:00", False)]
    ]
    frame = backtest._ohlcv_to_df(rows, category="MIN_30", adjust="NONE")
    frame = backtest._filter_df_by_date(frame, "2026-08-03", "2026-08-03")
    assert len(frame) == 2
    assert frame.attrs["snapshot_metadata"]["excluded_open_count"] == 1
    assert frame.attrs["snapshot_metadata"]["category"] == "MIN_30"


@pytest.mark.parametrize("kind", ["portfolio", "multi"])
def test_every_combination_member_keeps_independent_evidence_before_execution(monkeypatch, kind):
    from easy_tdx.backtest.multi_strategy_engine import MultiStrategyEngine, StrategySlot
    from easy_tdx.backtest.portfolio_engine import PortfolioBacktestEngine, StockData
    from easy_tdx.backtest.strategies import get_registry

    frames = [backtest._ohlcv_to_df(records()), backtest._ohlcv_to_df(records()[2:])]
    before = [
        frame_evidence(frame, category="DAY", adjust="QFQ", symbol=None, label="")["metadata"][
            "data_fingerprint"
        ]
        for frame in frames
    ]

    def mutate(self):
        for frame in frames:
            frame.loc[frame.index[0], "close"] = 10
        return SimpleNamespace(performance_basis={"test": True})

    monkeypatch.setattr(
        backtest, "serialize_result", lambda result: {"performance_basis": result.performance_basis}
    )
    if kind == "portfolio":
        monkeypatch.setattr(PortfolioBacktestEngine, "run", mutate)
        req = PortfolioBacktestRequest(strategy="ma_cross", stocks=["SZ:000001", "SH:600000"])
        result = backtest._run_portfolio_backtest(
            [StockData("000001", "SZ", frames[0]), StockData("600000", "SH", frames[1])], req
        )
    else:
        monkeypatch.setattr(MultiStrategyEngine, "run", mutate)
        req = MultiStrategyBacktestRequest(
            items=[
                MultiStrategyItem(strategy="ma_cross", symbol=symbol)
                for symbol in ["SZ:000001", "SH:600000"]
            ]
        )
        result = backtest._run_multi_strategy_backtest(
            [
                StrategySlot(
                    item.strategy, item.symbol, get_registry().get(item.strategy).build({}), frame
                )
                for item, frame in zip(req.items, frames, strict=True)
            ],
            req,
        )
    evidence = result["data_provenance"]
    assert [d["symbol"] for d in evidence["datasets"]] == ["SZ:000001", "SH:600000"]
    assert [d["bar_count"] for d in evidence["datasets"]] == [12, 10]
    assert [d["metadata"]["data_fingerprint"] for d in evidence["datasets"]] == before
    assert evidence["alignment"] == "independent_equity_union_forward_fill"
