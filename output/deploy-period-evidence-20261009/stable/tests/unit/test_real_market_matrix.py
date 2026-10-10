"""Real stock/index/industry snapshots through actual feed and analysis routes.

Only the network transport is replaced by frozen vendor frames. The shared
time/quality loaders and Chanlun pipeline are the production implementation.
"""

from copy import deepcopy
from datetime import datetime
from functools import partial
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from easy_tdx.mac.enums import Adjust
from easy_tdx.web import market_data
from easy_tdx.web.bar_snapshot import annotate_snapshot, mark_indicator_closed_bars
from easy_tdx.web.routers import chanlun
from easy_tdx.web.routers.bars import research_bars, security_bars
from easy_tdx.web.routers.chanlun_replay import ReplayRequest, replay_snapshot
from easy_tdx.web.schemas import ChanlunRequest
from tests.market_matrix import entries, load_case

CASES = entries()
NEW = [case for case in CASES if not case["legacy_metadata_preserved"]]
STOCKS = [case for case in CASES if case["instrument"]["kind"] == "stock"]
RESEARCH = [case for case in NEW if case["instrument"]["kind"] != "stock"]
CORE = ("macd", "bis", "xds", "zss", "bcs", "mmds", "pen_consolidations")


def freeze_time(entry, monkeypatch):
    observed = datetime.fromisoformat(entry["observed_at"])
    if observed.tzinfo is not None:
        observed = observed.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    monkeypatch.setattr(market_data, "annotate_snapshot", partial(annotate_snapshot, now=observed))
    monkeypatch.setattr(
        chanlun, "mark_indicator_closed_bars", partial(mark_indicator_closed_bars, now=observed)
    )


def replay(entry, rows, count):
    return replay_snapshot(
        ReplayRequest(
            code=entry["code"], category=entry["category"], bars=rows, visible_count=count
        ),
        ownership_history="summary",
    )


def test_manifest_covers_real_instrument_timeframe_cross_product():
    assert len(CASES) == 22
    assert {(c["instrument"]["kind"], c["category"]) for c in NEW} == {
        (kind, category)
        for kind in ("stock", "index", "board")
        for category in ("DAY", "WEEK", "MONTH", "MIN_30")
    }
    assert all(c["adjust"] == "NONE" for c in RESEARCH)
    old_index = next(c for c in CASES if c["code"] == "399006")
    assert old_index not in RESEARCH
    assert any("rule regression only" in note for note in old_index["notes"])


@pytest.mark.parametrize("entry", CASES, ids=lambda c: c["id"])
def test_source_hash_quality_and_native_closing_times(entry):
    payload, frame, snapshot = load_case(entry)
    assert len(frame) == entry["count"]
    quality = snapshot["metadata"]["quality"]
    assert quality["status"] == "ok"
    assert quality["errors"] == []
    assert snapshot["metadata"]["historical_data_vintage"] is False
    if entry["category"].startswith("MIN_"):
        for row in snapshot["data"]:
            assert pd.Timestamp(row["period_end"]) == pd.Timestamp(row["datetime"])
            assert datetime.fromisoformat(row["period_end"]).hour <= 15
        if entry["legacy_metadata_preserved"]:
            assert payload["metadata"]["bar_time"] == "start"
            assert any("incorrectly" in note for note in entry["notes"])
    if entry in NEW and entry["category"] == "MONTH":
        assert snapshot["data"][-1]["is_closed"] is False
        assert all(row["is_closed"] for row in snapshot["data"][:-1])
    if entry["instrument"]["kind"] == "board":
        identity = entry["instrument"]
        assert str(identity["catalog_entry"]["code"]) == identity["code"]
        assert identity["belong_entry"]["board_code"] == identity["code"]
        assert identity["catalog_entry"]["market"] == identity["exchange"]
        assert identity["belong_entry"]["market"] == identity["exchange"]


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", STOCKS, ids=lambda c: c["id"])
async def test_stock_chart_internal_and_actual_chanlun_share_real_bars(entry, monkeypatch):
    freeze_time(entry, monkeypatch)
    _, frame, snapshot = load_case(entry)
    mac, standard = AsyncMock(), AsyncMock()
    mac.get_stock_kline.side_effect = lambda *a, **k: frame.copy(deep=True)
    params = dict(
        market=entry["instrument"]["market"],
        code=entry["code"],
        category=entry["category"],
        start=0,
        count=len(frame),
        adjust=entry["adjust"],
    )
    internal = await market_data.load_equity_frame(standard, mac, **params)
    chart = await security_bars(**params, bar_time="native", client=standard, mac_client=mac)
    assert (
        internal.attrs["snapshot_metadata"]["data_fingerprint"]
        == chart["metadata"]["data_fingerprint"]
    )
    chart_frame = pd.DataFrame(chart["data"]).rename(columns={"date": "datetime"})
    chart_frame["datetime"] = pd.to_datetime(chart_frame.datetime)
    columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
        "is_closed",
        "period_end",
    ]
    pd.testing.assert_frame_equal(internal[columns], chart_frame[columns], check_exact=True)
    actual = await chanlun.chanlun_analyze(
        ChanlunRequest(**params), standard, mac, ownership_history="summary"
    )
    expected = replay(entry, snapshot["data"], len(frame))
    assert {key: actual[key] for key in CORE} == {key: expected[key] for key in CORE}
    assert actual["metadata"]["data_fingerprint"] == chart["metadata"]["data_fingerprint"]
    standard.get_security_bars.assert_not_called()
    assert all(call.kwargs["bar_time"] == "start" for call in mac.get_stock_kline.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", RESEARCH, ids=lambda c: c["id"])
async def test_actual_index_and_board_research_routes_preserve_identity_and_price(
    entry, monkeypatch
):
    freeze_time(entry, monkeypatch)
    _, frame, snapshot = load_case(entry)
    mac, standard = AsyncMock(), AsyncMock()
    mac.get_stock_kline.side_effect = lambda *a, **k: frame.copy(deep=True)
    identity = entry["instrument"]
    if identity["kind"] == "board":
        mac.get_board_list.return_value = pd.DataFrame([identity["catalog_entry"]])
        mac.get_belong_board.return_value = pd.DataFrame([identity["belong_entry"]])
    chart = await research_bars(
        kind=identity["kind"],
        code=entry["code"],
        market=identity["market"],
        board_type="HY",
        category=entry["category"],
        count=len(frame),
        mac_client=mac,
        client=standard,
    )
    assert chart["metadata"]["instrument"]["kind"] == identity["kind"]
    assert chart["metadata"]["instrument"]["market"] == identity["market"]
    assert chart["metadata"]["actual_adjust"] == "NONE"
    assert chart["metadata"]["bar_time"] == "end"
    for original, actual in zip(snapshot["data"], chart["data"], strict=True):
        for key in ("open", "high", "low", "close", "vol", "amount", "is_closed", "period_end"):
            assert original[key] == actual[key]
    if identity["kind"] == "board":
        actual = await chanlun.industry_analyze(
            chanlun.IndustryRequest(
                stock_market=identity["stock_market"],
                stock_code=identity["stock_code"],
                board_code=identity["code"],
                category=entry["category"],
                count=len(frame),
            ),
            mac,
            ownership_history="summary",
        )
        expected = replay(entry, snapshot["data"], len(frame))
        assert {key: actual["result"][key] for key in CORE} == {key: expected[key] for key in CORE}
    assert all(call.kwargs["adjust"] == Adjust.NONE for call in mac.get_stock_kline.call_args_list)
    assert all(call.args[0] == identity["exchange"] for call in mac.get_stock_kline.call_args_list)
    standard.get_index_bars.assert_not_called()


@pytest.mark.parametrize("entry", NEW, ids=lambda c: c["id"])
def test_real_prefix_replay_is_independent_of_future_prices_and_completion(entry):
    _, _, snapshot = load_case(entry)
    rows = snapshot["data"]
    count = len(rows) // 2
    expected = replay(entry, rows, count)
    changed = deepcopy(rows)
    for i, row in enumerate(changed[count:]):
        for key in ("open", "high", "low", "close"):
            row[key] *= 10 + i
        row["vol"] *= 100
        row["is_closed"] = False
    assert replay(entry, changed, count) == expected
    truncated = replay(entry, rows[:count], count)
    assert {k: v for k, v in truncated.items() if k != "replay"} == {
        k: v for k, v in expected.items() if k != "replay"
    }
    for family in ("bis", "xds", "bcs", "mmds"):
        for item in expected[family]:
            for key in ("confirmed_index", "detected_index", "invalidated_index"):
                if item.get(key) is not None:
                    assert 0 <= item[key] < count
