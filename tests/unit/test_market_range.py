from datetime import date
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from fastapi import HTTPException

from easy_tdx.web import market_range
from easy_tdx.web.bar_snapshot import annotate_snapshot
from easy_tdx.web.routers.bars import index_bars, research_bars


def history(size=9):
    return pd.DataFrame(
        [
            dict(
                datetime=str(stamp),
                open=10.0,
                high=12.0,
                low=9.0,
                close=11.0,
                vol=100.0,
                amount=1000.0,
            )
            for stamp in pd.date_range("2026-09-01", periods=size, freq="B")
        ]
    )


def feed(data, modify=None):
    calls = []

    async def get(*args, **kwargs):
        start, count = args[3:5]
        calls.append(start)
        end = len(data) - start
        result = data.iloc[max(0, end - count) : max(0, end)].copy()
        if modify:
            modify(result, calls)
        return result

    mac = AsyncMock()
    mac.get_stock_kline.side_effect = get
    return mac, calls


@pytest.fixture(autouse=True)
def small_pages(monkeypatch):
    monkeypatch.setattr(market_range, "PAGE_SIZE", 4)


@pytest.mark.asyncio
async def test_whole_range_metadata_and_shared_backtest_values():
    from easy_tdx.web.routers.backtest import _history_frame

    mac, calls = feed(history())
    snap = await market_range.load_equity_range(
        None, mac, "SH", "603936", "DAY", "QFQ", date(2026, 9, 1), date(2026, 9, 9)
    )
    assert calls == [0, 3, 6, 0]
    assert snap["count"] == 7
    meta = snap["metadata"]
    assert meta["page_count"] == 3
    assert meta["range_start"].startswith("2026-09-01")
    assert meta["last_closed_at"] == "2026-09-09 15:00:00"
    assert meta["consistency_check"] == "overlap_and_head_recheck"
    frame = await _history_frame(
        None, mac, "SH", "603936", "DAY", "QFQ", "2026-09-01", "2026-09-09"
    )
    assert len(frame) == 7
    assert pd.api.types.is_datetime64_any_dtype(frame.datetime)
    assert frame.datetime.iloc[0] == pd.Timestamp("2026-09-01")
    assert frame.attrs["snapshot_metadata"]["data_fingerprint"] == meta["data_fingerprint"]


@pytest.mark.asyncio
async def test_range_to_backtest_retains_full_intraday_identity():
    from easy_tdx.web.backtest_schemas import BacktestRequest
    from easy_tdx.web.routers.backtest import _history_frame, _run_backtest

    vendor = history(8)
    vendor["datetime"] = [
        f"2026-09-01 {clock}"
        for clock in ["10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00"]
    ]
    mac, _ = feed(vendor)
    frame = await _history_frame(
        None, mac, "SH", "603936", "MIN_30", "QFQ", "2026-09-01", "2026-09-01"
    )
    expected = pd.to_datetime(vendor.datetime)
    pd.testing.assert_series_equal(frame.datetime, expected, check_exact=True)
    result = _run_backtest(
        frame,
        BacktestRequest(
            strategy="ma_cross",
            symbol="SH:603936",
            category="MIN_30",
            params={"fast": 2, "slow": 5},
        ),
    )
    assert len(result["equity_curve"]) == 8
    assert len({row["datetime"] for row in result["equity_curve"]}) == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("issue", ["overlap", "revision", "source", "missing-overlap"])
async def test_offset_or_revision_changes_never_yield_partial_result(issue):
    def modify(result, calls):
        if issue == "overlap" and calls[-1] == 3:
            result.loc[result.index[-1], "close"] = 10.5
        if issue == "revision" and len(calls) > 1 and calls[-1] == 0:
            result.loc[result.index[-1], "close"] = 10.5
        if issue == "source" and calls[-1] == 3:
            result.attrs["adjustment_source"] = "different"
        if issue == "missing-overlap" and calls[-1] == 3:
            result.drop(result.index, inplace=True)

    mac, _ = feed(history(), modify)
    with pytest.raises(HTTPException) as error:
        await market_range.load_equity_range(None, mac, "SH", "603936", "DAY", "QFQ")
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_cap_is_error_not_success_with_truncated_data(monkeypatch):
    monkeypatch.setattr(market_range, "MAX_PAGES", 2)
    mac, _ = feed(history(12))
    with pytest.raises(HTTPException, match="上限"):
        await market_range.load_equity_range(None, mac, "SH", "603936", "DAY", "QFQ")


@pytest.mark.asyncio
async def test_minute_start_day_not_cut_off_at_middle_of_page():
    data = history(9)
    data["datetime"] = [str(d) for d in pd.date_range("2026-09-01 09:35", periods=9, freq="5min")]
    mac, calls = feed(data)
    snap = await market_range.load_equity_range(
        None, mac, "SH", "603936", "MIN_5", "QFQ", date(2026, 9, 1), date(2026, 9, 1)
    )
    assert len(snap["data"]) == 9
    assert calls == [0, 3, 6, 0]


@pytest.mark.asyncio
async def test_source_exhaustion_explicit_warning_and_no_fabrication():
    mac, _ = feed(history(2))
    snap = await market_range.load_equity_range(
        None, mac, "SH", "603936", "DAY", "QFQ", date(2026, 1, 1)
    )
    assert len(snap["data"]) == 2
    assert any("历史起点" in w for w in snap["metadata"]["quality"]["warnings"])


def test_minute_gaps_exclude_lunch_weekend_holiday_and_count_across_days():
    data = history(4)
    data["datetime"] = [
        "2026-09-24 11:30",
        "2026-09-24 14:00",
        "2026-09-24 15:00",
        "2026-09-28 11:30",
    ]
    snap = annotate_snapshot(
        data.to_dict("records"),
        "MIN_60",
        source="MAC",
        requested_adjust="NONE",
        actual_adjust="NONE",
        bar_time="end",
    )
    quality = snap["metadata"]["quality"]
    assert quality["missing_bar_samples"] == ["2026-09-28 10:30:00"]
    assert quality["missing_bar_count"] == 1
    assert quality["suspension_status"] == "not_verified"


@pytest.mark.asyncio
async def test_index_legacy_entry_returns_provenance_and_rejects_bad_dates():
    standard = AsyncMock()
    standard.get_index_bars.return_value = history(2)
    kwargs = dict(
        market="SH",
        code="000001",
        category="DAY",
        start=0,
        count=2,
        bar_time="native",
        client=standard,
    )
    result = await index_bars(**kwargs)
    assert result["metadata"]["actual_adjust"] == "NONE"
    assert result["metadata"]["instrument"]["kind"] == "index"
    data = history(2)
    data.loc[0, "datetime"] = None
    standard.get_index_bars.return_value = data
    with pytest.raises(HTTPException) as error:
        await index_bars(**kwargs)
    assert error.value.status_code == 502


@pytest.mark.asyncio
async def test_research_entry_rejects_bad_dates_as_upstream_error():
    mac, _ = feed(history(2))
    data = history(2)
    data.loc[0, "datetime"] = None
    mac.get_stock_kline.side_effect = None
    mac.get_stock_kline.return_value = data
    with pytest.raises(HTTPException) as error:
        await research_bars(
            kind="index",
            code="000001",
            market="SH",
            board_type="HY",
            category="DAY",
            count=2,
            mac_client=mac,
            client=AsyncMock(),
        )
    assert error.value.status_code == 502


def test_closed_frame_fingerprints_actual_input_not_excluded_candles():
    from easy_tdx.web.market_data import closed_frame

    rows = history(3).to_dict("records")
    rows[-1]["is_closed"] = False
    snapshot = annotate_snapshot(
        rows, "DAY", source="MAC", requested_adjust="QFQ", actual_adjust="QFQ", bar_time="end"
    )
    data = pd.DataFrame(snapshot["data"])
    data.attrs["snapshot_metadata"] = snapshot["metadata"]
    result = closed_frame(data)
    meta = result.attrs["snapshot_metadata"]
    assert len(result) == meta["input_count"] == 2
    assert meta["excluded_open_count"] == 1
    assert meta["source_fingerprint"] == snapshot["metadata"]["data_fingerprint"]
    assert meta["data_fingerprint"] != meta["source_fingerprint"]
    assert meta["last_bar_at"].startswith("2026-09-02")


@pytest.mark.parametrize("flags", [[True, "false"], [False, True]])
def test_ambiguous_or_internally_open_history_cannot_be_filtered_into_valid_history(flags):
    from easy_tdx.web.market_data import closed_frame

    data = history(2)
    data["is_closed"] = flags
    with pytest.raises(ValueError, match="收盘标记"):
        closed_frame(data)
