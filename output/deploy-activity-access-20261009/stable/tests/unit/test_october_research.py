"""Oct 1 requirements: provenance, rolling overlaps and causal research context."""

from datetime import datetime, timedelta
from math import sin

import pandas as pd
import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.macd import calc_macd
from easy_tdx.chanlun.pen_consolidation import recent_pen_consolidations
from easy_tdx.chanlun.types import BI, FX, CLKline, Direction, FXType
from easy_tdx.indicator import compute_indicators
from easy_tdx.web.bar_snapshot import annotate_snapshot, period_end
from easy_tdx.web.routers.chanlun_observations import StudyRequest, observations


def pens(prices):
    points = []
    for i, value in enumerate(prices):
        day = datetime(2026, 9, 1) + timedelta(days=i)
        candle = CLKline(i, day, value, value, value, value, 0, index=i)
        points.append(FX(FXType.DI if i % 2 == 0 else FXType.DING, candle, [candle], value))
    return [
        BI(
            a,
            b,
            Direction.UP if i % 2 == 0 else Direction.DOWN,
            i,
            max(a.val, b.val),
            min(a.val, b.val),
            confirmed_index=i + 2 if i < len(points) - 2 else None,
        )
        for i, (a, b) in enumerate(zip(points, points[1:]))
    ]


def test_overlap_keeps_last_four_windows_and_duplicate_ranges():
    lines = pens([10, 20, 12, 18, 13, 19, 11, 21])
    before = [(b.low, b.high, b.confirmed_index) for b in lines]
    zones = recent_pen_consolidations(lines)
    assert len(zones) == 4
    assert [z["pen_indices"] for z in zones] == [[1, 2, 3], [2, 3, 4], [3, 4, 5], [4, 5, 6]]
    assert zones[1]["lower"] == zones[2]["lower"] == 13
    assert zones[1]["upper"] == zones[2]["upper"] == 18
    assert zones[-1]["confirmed"] is False
    assert all(not z["eligible_for_trading"] for z in zones)
    assert before == [(b.low, b.high, b.confirmed_index) for b in lines]


def test_point_contact_is_not_a_rectangle_and_result_is_detached():
    assert recent_pen_consolidations(pens([1, 2, 2, 3])) == []
    result = ChanlunResult(macd={"dif": [1], "dea": [2], "hist": [-2]})
    output = result.to_dict()
    output["macd"]["dif"][0] = 100
    assert result.macd["dif"][0] == 1


def test_chart_macd_matches_engine_without_rounding_near_zero():
    close = [20 + 0.004 * sin(i / 8) + i * 0.00001 for i in range(160)]
    expected = calc_macd(close)
    chart = compute_indicators(pd.DataFrame({"close": close}), ["MACD"])
    for name in ("dif", "dea", "hist"):
        assert list(chart[f"MACD_{name.upper()}"]) == expected[name]
    assert chart.MACD_HIST.iloc[120] != 0


def test_explicit_adjustment_fallback_and_completion_metadata():
    rows = [{"datetime": "2026-09-30 10:00:00", "close": 10}]
    snap = annotate_snapshot(
        rows,
        "MIN_5",
        source="TDX_STANDARD",
        requested_adjust="QFQ",
        actual_adjust="NONE",
        now=datetime(2026, 9, 30, 10, 3),
    )
    assert snap["data"][0]["is_closed"] is False
    assert snap["data"][0]["period_end"] == "2026-09-30 10:05:00"
    assert snap["metadata"]["actual_adjust"] == "NONE"
    assert snap["metadata"]["historical_data_vintage"] is False
    assert "period_end" not in rows[0]
    assert period_end(datetime(2026, 9, 30), "MONTH") == datetime(2026, 9, 30, 15)


def study_bars():
    return [
        {
            "datetime": datetime(2026, 9, 30, 9, 30) + timedelta(minutes=5 * i),
            "open": 10 + i * 0.01,
            "high": 11 + i * 0.01,
            "low": 9 + i * 0.01,
            "close": 10.1 + i * 0.01,
            "vol": 100 + i,
            "amount": 1000,
        }
        for i in range(12)
    ]


def test_multiperiod_cutoff_excludes_future_and_spanning_candles():
    bars = study_bars()
    request = StudyRequest(
        as_of=datetime(2026, 9, 30, 10, 0),
        series=[
            {"code": "300450", "category": "MIN_5", "bars": bars},
            {
                "code": "300450",
                "category": "DAY",
                "bars": [{**bars[0], "datetime": datetime(2026, 9, 30)}],
            },
        ],
    )
    result = observations(request)
    assert result["rows"][0]["bar_count"] == 6
    assert result["rows"][0]["last_date"].endswith("09:55:00")
    assert "error" in result["rows"][1]
    assert not result["eligible_for_trading"]
    assert result["rows"][0]["warmup_warning"]
    bars[-1]["close"] = 1000
    bars[-1]["high"] = 1001
    changed = request.model_copy(
        update={
            "series": [request.series[0].model_copy(update={"bars": request.series[0].bars[:6]})]
        }
    )
    assert observations(changed)["rows"][0]["pairs"] == result["rows"][0]["pairs"]


def test_multiperiod_rejects_mixed_stocks_and_duplicate_periods():
    source = {"code": "300450", "category": "MIN_5", "bars": study_bars()}
    for second in [source, {**source, "code": "000001", "category": "MIN_15"}]:
        with pytest.raises(ValueError):
            StudyRequest(as_of=datetime(2026, 9, 30, 10), series=[source, second])


@pytest.mark.asyncio
async def test_120_minute_route_uses_five_minute_multiplier_not_60_minute_alias():
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from easy_tdx.mac.enums import Period
    from easy_tdx.web.routers.bars import security_bars

    mac = AsyncMock()
    mac.get_stock_kline.return_value = pd.DataFrame(study_bars())
    kwargs = dict(
        market="SZ",
        code="300450",
        category="MIN_120",
        start=0,
        count=12,
        adjust="QFQ",
        bar_time="start",
        client=AsyncMock(),
    )
    result = await security_bars(mac_client=mac, **kwargs)
    args = mac.get_stock_kline.call_args.args
    assert args[2] == Period.MINS and args[5] == 24
    assert result["metadata"]["category"] == "MIN_120"
    assert result["data"][0]["period_end"] == "2026-09-30 11:30:00"
    with pytest.raises(HTTPException) as exc:
        await security_bars(mac_client=None, **kwargs)
    assert exc.value.status_code == 503


@pytest.mark.parametrize("side", ["up", "down"])
def test_conflicts_mirror_but_old_divergences_do_not_trigger(monkeypatch, side):
    import importlib

    module = importlib.import_module("easy_tdx.web.routers.chanlun_observations")
    latest = "2026-09-30 09:55:00"
    small = {
        "category": "MIN_5",
        "last_date": latest,
        "divergences": [{"direction": side, "date": latest, "confirmed_date": None}],
    }
    large = {
        "category": "MIN_30",
        "last_date": "2026-09-30 09:30:00",
        "divergences": [],
        "above_ma10": side == "up",
        "price": 12 if side == "up" else 8,
        "ma10": 10,
        "pairs": {"macd": {"fast": 2 if side == "up" else -2, "slow": 1 if side == "up" else -1}},
    }
    monkeypatch.setattr(
        module,
        "observe",
        lambda frame, category, **kw: dict(small if category == "MIN_5" else large),
    )
    request = StudyRequest(
        as_of=datetime(2026, 9, 30, 10),
        series=[
            {"code": "300450", "category": category, "bars": study_bars()}
            for category in ["MIN_5", "MIN_30"]
        ],
    )
    assert len(observations(request)["conflicts"]) == 1
    small["divergences"][0]["date"] = "2026-09-29 09:55:00"
    assert observations(request)["conflicts"] == []


def test_context_observations_keep_thresholds_and_do_not_promote_trades():
    from easy_tdx.chanlun.observations import observe

    frame = pd.DataFrame(
        [
            {
                "datetime": datetime(2026, 1, 1) + timedelta(days=i),
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.0,
                "vol": 100.0,
                "amount": 1000.0,
            }
            for i in range(160)
        ]
    )
    frame.loc[159, ["close", "high", "low", "vol"]] = [20, 21, 8, 300]
    result = observe(frame, "DAY")
    text = " ".join(result["observations"])
    assert "三组快慢线差值同时增加" in text
    assert "BOLL 带宽扩张" in text
    assert "3.00 倍" in text and "放量突破" in text and "未形成负向 MACD 柱" in text
    assert not result["eligible_for_trading"]
    assert "放量突破" not in " ".join(observe(frame, "DAY", volume_multiple=4)["observations"])
    frame.loc[159, ["close", "high", "low", "vol"]] = [9, 10, 8, 50]
    assert any("缩量回调" in note for note in observe(frame, "DAY")["observations"])
