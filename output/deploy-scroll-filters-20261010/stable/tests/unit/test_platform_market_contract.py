"""Cross-entry data contract: explicit adjustment, native close times and quality."""

from datetime import date, datetime
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from fastapi import HTTPException

from easy_tdx.web.adjusted_bars import fetch_adjusted_bars
from easy_tdx.web.bar_snapshot import annotate_snapshot, mark_indicator_closed_bars, period_end
from easy_tdx.web.market_data import closed_frame, load_equity_frame
from easy_tdx.web.routers.bars import security_bars
from easy_tdx.web.trading_calendar import is_session


def frame():
    return pd.DataFrame(
        [
            dict(
                datetime=f"2026-09-30 {t}",
                open=10.0,
                high=12.0,
                low=9.0,
                close=11.0,
                vol=100.0,
                amount=1000.0,
            )
            for t in ("10:30:00", "11:30:00", "14:00:00", "15:00:00")
        ]
    )


@pytest.mark.asyncio
async def test_chart_and_internal_workflows_share_native_values_and_provenance():
    mac, standard = AsyncMock(), AsyncMock()
    mac.get_stock_kline.return_value = frame()
    internal = await fetch_adjusted_bars(standard, mac, "SH", "603936", "MIN_60", 0, 4, "QFQ")
    chart = await security_bars(
        market="SH",
        code="603936",
        category="MIN_60",
        start=0,
        count=4,
        adjust="QFQ",
        bar_time="native",
        client=standard,
        mac_client=mac,
    )
    assert (
        chart["metadata"]["data_fingerprint"]
        == internal.attrs["snapshot_metadata"]["data_fingerprint"]
    )
    assert chart["metadata"]["bar_time"] == "end"
    assert chart["data"][-1]["period_end"] == "2026-09-30 15:00:00"
    assert chart["data"][-1]["close"] == internal.close.iloc[-1]
    assert mac.get_stock_kline.call_args.kwargs["bar_time"] == "start"
    standard.get_security_bars.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("adjust", ["QFQ", "HFQ"])
async def test_missing_adjustment_cannot_silently_fall_back(adjust):
    standard = AsyncMock()
    with pytest.raises(HTTPException) as failure:
        await fetch_adjusted_bars(standard, None, "SZ", "300750", "DAY", 0, 600, adjust)
    assert failure.value.status_code == 503
    assert "未使用不复权行情替代" in failure.value.detail
    standard.get_security_bars.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_none_allows_standard_fallback_and_sets_source():
    standard = AsyncMock()
    standard.get_security_bars.return_value = frame()
    data = await fetch_adjusted_bars(standard, None, "SH", "603936", "MIN_60", 0, 4, "NONE")
    assert data.attrs["snapshot_metadata"]["source"] == "TDX_STANDARD"
    assert data.attrs["snapshot_metadata"]["actual_adjust"] == "NONE"


def test_observed_close_labels_are_not_shifted_twice_and_explicit_open_survives():
    data = frame()
    data.attrs["snapshot_metadata"] = {"bar_time": "end"}
    marked = mark_indicator_closed_bars(data, "MIN_60", datetime(2026, 9, 30, 11, 30))
    assert list(marked.is_closed) == [True, True, False, False]
    assert len(closed_frame(marked)) == 2
    marked.loc[0, "is_closed"] = False
    assert not mark_indicator_closed_bars(
        marked, "MIN_60", datetime(2026, 9, 30, 15)
    ).is_closed.iloc[0]
    assert "is_closed" not in data


@pytest.mark.parametrize(
    "label,category,expected",
    [
        ("2026-09-21", "WEEK", "2026-09-24 15:00:00"),
        ("2026-05-01", "MONTH", "2026-05-29 15:00:00"),
        ("2025-01-31", "MONTH", "2025-01-27 15:00:00"),
        ("2024-02-05", "WEEK", "2024-02-08 15:00:00"),
        ("2027-01-01", "MONTH", "2027-01-31 15:00:00"),
    ],
)
def test_calendar_completion_known_and_explicit_conservative_unknown(label, category, expected):
    assert str(period_end(datetime.fromisoformat(label), category)) == expected


def test_civil_makeup_weekend_not_trading_day():
    assert is_session(date(2026, 10, 10)) is False
    assert is_session(date(2026, 10, 8)) is True
    assert is_session(date(2027, 1, 4)) is None


def test_missing_bars_not_invented_or_claimed_as_suspension():
    data = frame().iloc[:2].to_dict("records")
    data[0]["datetime"], data[1]["datetime"] = "2026-09-23", "2026-09-28"
    snap = annotate_snapshot(data, "DAY", source="MAC", requested_adjust="QFQ", actual_adjust="QFQ")
    quality = snap["metadata"]["quality"]
    assert quality["missing_sessions"] == ["2026-09-24"]
    assert quality["suspension_status"] == "not_verified"
    assert len(snap["data"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["order", "duplicate", "ohlc", "nonfinite", "negative-volume"])
async def test_untrusted_feed_fails_explicitly(invalid):
    data = frame()
    if invalid == "order":
        data = data.iloc[::-1]
    if invalid == "duplicate":
        data.loc[1, "datetime"] = data.loc[0, "datetime"]
    if invalid == "ohlc":
        data.loc[0, "high"] = 5
    if invalid == "nonfinite":
        data.loc[0, "close"] = float("inf")
    if invalid == "negative-volume":
        data.loc[0, "vol"] = -1
    mac = AsyncMock()
    mac.get_stock_kline.return_value = data
    with pytest.raises(HTTPException) as failure:
        await load_equity_frame(AsyncMock(), mac, "SH", "603936", "MIN_60", 0, 4, "QFQ")
    assert failure.value.status_code == 502


def test_fingerprint_changes_on_adjustment_data_revision_and_raw_input_not_modified():
    raw = frame().to_dict("records")
    a = annotate_snapshot(raw, "MIN_60", source="MAC", requested_adjust="QFQ", actual_adjust="QFQ")
    assert "is_closed" not in raw[0]
    raw[0]["close"] = 10.5
    b = annotate_snapshot(raw, "MIN_60", source="MAC", requested_adjust="QFQ", actual_adjust="QFQ")
    assert a["metadata"]["data_fingerprint"] != b["metadata"]["data_fingerprint"]


@pytest.mark.asyncio
async def test_mac_local_recompute_failure_cannot_be_labelled_qfq():
    data = frame()
    data.attrs.update(actual_adjust="NONE", adjustment_source="qfq_recompute_unavailable")
    mac = AsyncMock()
    mac.get_stock_kline.return_value = data
    with pytest.raises(HTTPException) as failure:
        await fetch_adjusted_bars(AsyncMock(), mac, "SH", "603936", "MIN_60", 0, 4, "QFQ")
    assert failure.value.status_code == 503
    assert "实际 NONE" in failure.value.detail


@pytest.mark.parametrize("client_name", ["MacClient", "AsyncMacClient"])
def test_both_protocol_clients_tag_none_when_xdxr_is_unavailable(client_name):
    from easy_tdx.mac import client as module

    client = object.__new__(getattr(module, client_name))
    client._fetch_xdxr_records = lambda *_: None
    original = frame()
    result = client._local_recompute_qfq(original, 1, "603936")
    assert result.attrs["actual_adjust"] == "NONE"
    assert "actual_adjust" not in original.attrs


def test_inline_backtest_excludes_open_rows_and_rejects_ambiguous_flags():
    from easy_tdx.web.routers.backtest import _ohlcv_to_df

    data = frame().to_dict("records")
    for i, row in enumerate(data):
        row["is_closed"] = i < 3
    assert len(_ohlcv_to_df(data)) == 3
    data[0]["is_closed"] = "false"
    with pytest.raises(ValueError, match="布尔"):
        _ohlcv_to_df(data)


@pytest.mark.asyncio
async def test_portfolio_does_not_silently_drop_a_failed_member():
    from easy_tdx.web.routers.backtest import _fetch_portfolio_bars

    with pytest.raises(ValueError, match="未使用不复权行情替代"):
        await _fetch_portfolio_bars(AsyncMock(), ["SH:603936"], "DAY", None, None)


@pytest.mark.asyncio
async def test_radar_failure_reason_reaches_every_duplicate_target():
    from easy_tdx.web.signal_scan import ScanTarget, fetch_scan_bars

    targets = [
        ScanTarget(str(i), "example", "single", "ma_cross", symbol="SH:603936", category="DAY")
        for i in range(2)
    ]
    result = await fetch_scan_bars(AsyncMock(), targets, adjust="QFQ")
    assert result == {("SH:603936", "DAY"): None}
    assert all("未使用不复权行情替代" in t.error for t in targets)
