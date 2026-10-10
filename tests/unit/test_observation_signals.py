"""Display projections retain authoritative signals, chronology and independent M1."""

from datetime import datetime, timedelta
from types import SimpleNamespace as NS

from easy_tdx.chanlun.observation_signals import observation_signals


def fixture():
    bars = [
        NS(date=datetime(2026, 1, 1) + timedelta(days=i), low=10 + i, high=11 + i) for i in range(8)
    ]
    end = NS(k=NS(klines=[], k_index=1), val=11, fx_type="di")
    point = NS(
        bi=NS(end=end),
        confirmed_index=5,
        mmd_type=NS(value="2buy"),
        source="confirmed_segment_base_v1",
        msg="弱势回试",
        evidence={"strength": "weak_new_extreme"},
    )
    wave = NS(
        bc=True,
        bc_type=NS(value="macd_wave"),
        status="confirmed",
        direction="up",
        signal_index=2,
        confirmed_index=6,
        evidence={"a": 1},
    )
    return NS(klines=bars, mmds=[point], bcs=[wave])


def test_new_confirmation_keeps_old_extremum_and_distinct_m1():
    result = fixture()
    points = observation_signals(result, "2026-01-05")
    assert len(points) == 2
    structure = next(p for p in points if p["family"] == "structure")
    assert structure["date"] == "2026-01-02 00:00:00"
    assert structure["confirmed_date"] == "2026-01-06 00:00:00"
    assert structure["type"] == "2buy" and structure["price"] == 11
    assert structure["reason"] == "弱势回试"
    structure["evidence"]["strength"] = "changed"
    assert result.mmds[0].evidence["strength"] == "weak_new_extreme"
    assert points[0]["type"] == "M1" and points[0]["side"] == "sell"
    assert points[0]["price"] == 13
    assert observation_signals(result, "2026-01-08") == []


def test_never_invent_unconfirmed_points_or_promote_other_divergence_families():
    for kind, status in [
        ("macd", "confirmed"),
        ("macd_wave_special", "confirmed"),
        ("macd_wave_nonstandard", "confirmed"),
        ("macd_wave", "candidate"),
        ("macd_wave", "superseded"),
    ]:
        result = fixture()
        result.mmds[0].confirmed_index = None
        result.bcs[0].bc_type.value = kind
        result.bcs[0].status = status
        assert observation_signals(result, "2026-01-01") == []
    result = fixture()
    result.mmds[0].confirmed_index = 20
    result.bcs[0].confirmed_index = result.bcs[0].signal_index
    assert observation_signals(result, "2026-01-01") == []
