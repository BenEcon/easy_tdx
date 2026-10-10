"""Oct 9 document acceptance: observation is causal and never a trading gate."""

import json
from datetime import datetime, timedelta
from math import sin

import pandas as pd
import pytest

from easy_tdx.chanlun import ChanlunAnalyser
from easy_tdx.chanlun.research_context import (
    arrangement,
    build_context,
    indicator_events,
    pair_context,
    pen_direction,
)
from easy_tdx.web.routers.chanlun_observations import StudyRequest, observations


def frame(n=160):
    values = [30 + i * 0.015 + 2 * sin(i / 5) for i in range(n)]
    return pd.DataFrame(
        [
            dict(
                datetime=datetime(2026, 1, 1) + timedelta(days=i),
                open=p - 0.1,
                high=p + 0.3,
                low=p - 0.3,
                close=p,
                vol=100 + i + 20 * sin(i / 3),
                amount=1000,
            )
            for i, p in enumerate(values)
        ]
    )


def study(data, **kw):
    return observations(
        StudyRequest(
            as_of=datetime(2026, 12, 31, 15),
            series=[dict(code="000001", category="DAY", bars=data.to_dict("records"))],
            **kw,
        )
    )


def test_contiguous_ma_range_never_skips_failure_or_missing_values():
    values = {
        5: pd.Series([10]),
        10: pd.Series([9]),
        20: pd.Series([8]),
        30: pd.Series([8]),
        60: pd.Series([7]),
    }
    state = arrangement(values, list(values), 0, 1)
    assert state["to"] == 20 and "相等" in state["reason"]
    values[30] = pd.Series([float("nan")])
    assert "样本不足" in arrangement(values, list(values), 0, 1)["reason"]
    assert arrangement(values, list(values), 0, -1)["to"] is None


@pytest.mark.parametrize("kind", ["ma", "volume", "macd"])
def test_pair_keeps_directions_separate_when_both_fall(kind):
    result = pair_context(pd.Series([11.0, 10.0]), pd.Series([10.0, 8.0]), kind)
    assert "下降" in result["directions"]
    assert "多头展开" not in result["description"]
    assert result["gap_change"] == 1


def test_pair_zero_denominator_and_missing_are_not_zero():
    assert pair_context(pd.Series([1.0]), pd.Series([0.0]), "volume")["relative_gap"] is None
    assert pair_context(pd.Series([float("nan")]), pd.Series([0.0]), "ma")["gap"] is None


@pytest.mark.parametrize("count", [1, 2, 9, 10, 11])
def test_short_observations_keep_missing_values_and_do_not_claim_joint_repair(count):
    row = study(frame(count))["rows"][0]
    json.dumps(row, allow_nan=False)
    assert not row["eligible_for_trading"]
    if count < 10:
        assert row["pairs"]["ma"]["slow"] is None
        assert row["pairs"]["volume"]["slow"] is None
        assert row["pairs"]["ma"]["gap_change"] is None
    if count < 11:
        assert not any("三组快慢线差值同时增加" in text for text in row["observations"])


@pytest.mark.parametrize(
    "category,bar_time", [("MIN_5", "start"), ("MIN_5", "end"), ("DAY", "start")]
)
def test_direction_history_uses_observed_close_but_keeps_extreme_anchors(category, bar_time):
    from easy_tdx.chanlun.observations import observe
    from easy_tdx.web.bar_snapshot import period_end

    data = frame(70)
    if category == "MIN_5":
        data["datetime"] = [
            datetime(2026, 9, 28, 9, 30) + timedelta(minutes=5 * i) for i in range(70)
        ]
    raw = observe(data, category, window_bars=800)["direction_observation"]
    request = StudyRequest(
        as_of=datetime(2026, 12, 31, 15),
        window_bars=800,
        series=[
            dict(code="000001", category=category, bar_time=bar_time, bars=data.to_dict("records"))
        ],
    )
    delivered = observations(request)["rows"][0]["direction_observation"]
    assert raw["history"] and len(raw["history"]) == len(delivered["history"])
    for original, event in zip(raw["history"], delivered["history"]):
        assert event["bar_date"] == original["date"]
        assert event["date"] == period_end(
            datetime.fromisoformat(original["date"]), category, bar_time
        ).isoformat(sep=" ")
        assert event["anchor_date"] == original["anchor_date"]
        if original["known_date"]:
            assert event["known_bar_date"] == original["known_date"]
            assert event["known_date"] == period_end(
                datetime.fromisoformat(original["known_date"]), category, bar_time
            ).isoformat(sep=" ")
            assert event["known_date"] <= event["date"]
    assert delivered["strict"] == raw["strict"]


def test_custom_ma_settings_sorted_without_visibility_and_warmup_unchanged():
    data = frame()
    short = study(data, ma_periods=[30, 5, 10, 5], window_bars=20)["rows"][0]
    long = study(data, ma_periods=[30, 5, 10], window_bars=60)["rows"][0]
    assert short["ma_research"]["periods"] == [5, 10, 30]
    assert short["ma_research"] == long["ma_research"]
    assert short["pairs"] == long["pairs"]
    assert short["window"]["count"] == 20 and long["window"]["count"] == 60
    json.dumps(short, allow_nan=False)


def test_explicit_range_cuts_before_all_calculations_and_does_not_reset_ema():
    data = frame(80)
    end = data.datetime.iloc[49].replace(hour=15)
    start = data.datetime.iloc[40]
    a = study(data, window_start=start, window_end=end)["rows"][0]
    b = study(data.iloc[:50], window_start=start, window_end=end)["rows"][0]
    assert a["pairs"] == b["pairs"]
    assert a["direction_observation"] == b["direction_observation"]
    assert a["window"]["count"] == 10 and a["window"]["warmup_bars"] == 40
    assert all(event["date"] >= str(start) for event in a["events"])
    assert all(event["known_at"] <= str(end) for event in a["events"])


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(ma_periods=[0]),
        dict(ma_periods=[801]),
        dict(window_bars=0),
        dict(window_start=datetime(2026, 1, 1)),
        dict(window_start=datetime(2026, 2, 1), window_end=datetime(2026, 1, 1)),
        dict(window_start=datetime(2026, 1, 1), window_end=datetime(2027, 1, 1)),
    ],
)
def test_bad_study_parameters_rejected(kwargs):
    with pytest.raises(ValueError):
        study(frame(5), **kwargs)


def test_empty_requested_window_reports_error_instead_of_current_data():
    row = study(frame(5), window_start=datetime(2026, 5, 1), window_end=datetime(2026, 6, 1))[
        "rows"
    ][0]
    assert "没有已收盘" in row["error"]


def test_end_label_not_delayed_by_an_extra_period_and_open_candle_excluded():
    bars = frame(3).to_dict("records")
    for i, b in enumerate(bars):
        b["datetime"] = datetime(2026, 9, 30, 10, 0) + timedelta(minutes=30 * i)
    req = StudyRequest(
        as_of=datetime(2026, 9, 30, 10, 30),
        series=[dict(code="1", category="MIN_30", bar_time="end", bars=bars)],
    )
    assert observations(req)["rows"][0]["bar_count"] == 2
    req.series[0].bars[1].is_closed = False
    assert observations(req)["rows"][0]["bar_count"] == 1


def test_event_invalidation_is_first_reverse_and_not_overwritten():
    data = frame(7)
    fast = pd.Series([-1.0, 1.0, 2.0, -1.0, -2.0, 1.0, 2.0])
    slow = pd.Series([0.0] * 7)
    pairs = {key: (fast, slow) for key in ("ma", "volume", "macd")}
    vals = {5: fast, 10: slow}
    events = indicator_events(data, pairs, vals, [5, 10], 0)
    up = [e for e in events if e["key"] == "ma" and e["direction"] == 1]
    assert up[0]["invalidated_at"] == str(data.datetime.iloc[3])
    assert up[0]["active"] is False and up[1]["active"] is True
    assert [e for e in indicator_events(data, pairs, vals, [5, 10], 5) if e["key"] == "ma"] == [
        up[1]
    ]


def test_asynchronous_repair_and_axis_up_then_down_are_preserved():
    data = frame(8)
    slow = pd.Series([0.0] * 8)
    pairs = {
        "ma": (pd.Series([-3.0, -2.0, -1.0, 1.0, 2.0, 3.0, 4.0, 5.0]), slow),
        "volume": (pd.Series([-4.0, -4.0, -4.0, -3.0, -2.0, -1.0, 1.0, 2.0]), slow),
        "macd": (
            pd.Series([-3.0, -2.0, 1.0, 2.0, -1.0, 1.0, 2.0, 3.0]),
            pd.Series([-0.5, -0.3, 0.1, 0.2, -0.2, -0.1, 0.1, 0.2]),
        ),
    }
    events = indicator_events(data, pairs, {5: pairs["ma"][0], 10: slow}, [5, 10], 0)
    assert next(e for e in events if e["key"] == "ma" and e["direction"] == 1)["index"] == 3
    assert next(e for e in events if e["key"] == "volume" and e["direction"] == 1)["index"] == 6
    ups = [e for e in events if e["key"] == "both_axis" and e["direction"] == 1]
    assert ups[0]["invalidated_at"] == str(data.datetime.iloc[4])
    assert ups[-1]["active"] and ups[-1]["index"] == 6


def test_green_shrink_is_a_separate_process_event():
    data = frame(5)
    fast = pd.Series([-1.0, -2.0, -1.5, -1.0, -0.5])
    slow = pd.Series([0.0] * 5)
    events = indicator_events(
        data,
        {key: (fast, slow) for key in ("ma", "volume", "macd")},
        {5: fast, 10: slow},
        [5, 10],
        0,
    )
    event = next(e for e in events if e["key"] == "hist_shrink")
    assert event["label"] == "绿柱开始缩短" and event["index"] == 2 and event["active"]


def test_observation_does_not_mutate_strict_structure():
    data = frame(100)
    result = ChanlunAnalyser(frequency="day").process_klines(data)
    before = [(b.start.val, b.end.val, b.confirmed_index) for b in result.bis]
    context = build_context(data, result)
    assert before == [(b.start.val, b.end.val, b.confirmed_index) for b in result.bis]
    assert context["direction_observation"]["strict"]["locked"] is False
    assert len(context["direction_observation"]["history"]) > 0


def test_direction_projection_is_withdrawn_when_anchor_breaks_and_mirrors():
    data = frame(90)
    result = ChanlunAnalyser().process_klines(data)
    state = pen_direction(data, result.bis, result.fractals)
    anchor = result.bis[-1].end
    top = anchor.fx_type.value == "ding"
    broken = data.copy()
    broken.loc[len(data) - 1, "high" if top else "low"] = anchor.val + (1 if top else -1)
    out = pen_direction(broken, result.bis, result.fractals)
    assert out["state"] == "invalidated" and out["projection"] is None
    inverse = data.copy()
    inverse["high"], inverse["low"] = 100 - data.low, 100 - data.high
    inverse["open"], inverse["close"] = 100 - data.open, 100 - data.close
    reverse = ChanlunAnalyser().process_klines(inverse)
    mirrored = pen_direction(inverse, reverse.bis, reverse.fractals)
    assert mirrored["state"] == state["state"]
    assert mirrored["direction"] != state["direction"]


def test_prefix_history_is_stable_for_future_appends():
    data = frame(70)
    first = build_context(
        data.iloc[:60], ChanlunAnalyser().process_klines(data.iloc[:60]), window_bars=800
    )
    full = build_context(data, ChanlunAnalyser().process_klines(data), window_bars=800)
    cutoff = str(data.datetime.iloc[59])
    assert first["direction_observation"]["history"] == [
        e for e in full["direction_observation"]["history"] if e["date"] <= cutoff
    ]


def test_child_history_missing_does_not_claim_parent_support():
    bars = frame(60)
    child = bars.iloc[-5:].copy()
    request = StudyRequest(
        as_of=datetime(2026, 12, 31, 15),
        series=[
            dict(code="1", category="DAY", bars=bars.to_dict("records")),
            dict(code="1", category="MIN_5", bars=child.to_dict("records")),
        ],
    )
    rows = observations(request)["rows"]
    auxiliary = rows[0]["direction_observation"]["auxiliary"][0]
    if not auxiliary["covered"]:
        assert not auxiliary["supports"] and "未覆盖" in auxiliary["description"]
    assert observations(request)["eligible_for_trading"] is False


@pytest.mark.asyncio
async def test_native_quote_labels_keep_actual_close_without_double_offset():
    from unittest.mock import AsyncMock

    from easy_tdx.web.routers.bars import security_bars

    data = frame(2)
    data["datetime"] = [datetime(2026, 9, 30, 14), datetime(2026, 9, 30, 15)]
    client = AsyncMock()
    client.get_stock_kline.return_value = data
    snap = await security_bars(
        market="SH",
        code="603936",
        category="MIN_60",
        start=0,
        count=2,
        bar_time="native",
        adjust="QFQ",
        mac_client=client,
        client=AsyncMock(),
    )
    assert client.get_stock_kline.call_args.kwargs["bar_time"] == "start"
    assert snap["metadata"]["bar_time"] == "end"
    assert snap["data"][-1]["period_end"] == "2026-09-30 15:00:00"
