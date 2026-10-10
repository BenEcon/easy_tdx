"""Independent boundary and causal acceptance tests for the October 4 rules."""

from copy import deepcopy
from datetime import datetime, timedelta

import pandas as pd
import pytest

from easy_tdx.chanlun.analyser import ChanlunResult, _df_to_klines
from easy_tdx.chanlun.bi import find_bis
from easy_tdx.chanlun.divergence_signals import (
    indicator_events,
    segment_evidence,
    special_wave_events,
    wave_events,
)
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.kline_merge import merge_klines
from easy_tdx.web.bar_snapshot import mark_indicator_closed_bars
from easy_tdx.web.routers.chanlun_replay import ReplayBar
from tests.unit.test_october_second_divergence import reverse_pen_sample, sample
from tests.unit.test_wave_families import snapshot, special_distinct_extrema_sample


@pytest.mark.parametrize("top", [False, True])
def test_full_a_is_not_trimmed_and_only_bc_must_remain_on_axis_side(top):
    bars, macd = sample(top)
    sign = -1 if top else 1
    macd["dif"][1] = 0.2 * sign
    macd["dea"][1] = 0.3 * sign
    (standard,) = wave_events(bars, macd)
    (nonstandard,) = wave_events(bars, macd, family="nonstandard")
    assert standard.evidence["a_start"] == 2
    assert nonstandard.evidence["a_start"] == 1
    assert nonstandard.evidence["a_area"] == 3
    assert standard.evidence["a_area"] == 1
    for family in ("standard", "nonstandard"):
        for line in ("dif", "dea"):
            for index in (3, 5):
                changed = deepcopy(macd)
                changed[line][index] = 0
                assert not wave_events(bars, changed, family=family, legacy_standard=True)
                assert bool(wave_events(bars, changed, family=family)) == (
                    family == "standard" and line == "dif" and index == 3
                )


@pytest.mark.parametrize("top", [False, True])
def test_c_first_bar_cannot_supply_b_pullback(top):
    bars, macd = sample(top)
    sign = -1 if top else 1
    macd["dea"][1:7] = [v * sign for v in [-2, -2, -2.2, -2.1, -1, -1.1]]
    for family in ("standard", "nonstandard"):
        audit = []
        assert not wave_events(bars, macd, family=family, diagnostics=audit)
        report = next(r for r in audit if r["c_start"] == 5)
        check = next(c for c in report["checks"] if c["gate"] == "dea_centre_pullback")
        assert not check["passed"] and check["values"]["pullback"] == -2.1 * sign
    # Structural evidence deliberately retains its separately approved scope.
    assert segment_evidence(bars, macd, (1, 2), (5, 6), "up" if top else "down")


@pytest.mark.parametrize("top", [False, True])
def test_special_equal_price_is_one_candidate_not_a_zero_area_c(top):
    bars, macd = special_distinct_extrema_sample(top)
    key = "high" if top else "low"
    setattr(bars[9], key, getattr(bars[1], key))
    setattr(bars[10], key, getattr(bars[1], key))
    events = special_wave_events(bars[:11], {k: v[:11] for k, v in macd.items()})
    assert [e.signal_index for e in events] == [9]
    assert "c_area" not in events[0].evidence
    assert not any(
        e.signal_index == 9
        for e in indicator_events(bars[:11], {k: v[:11] for k, v in macd.items()})
    )


@pytest.mark.parametrize("detector", [indicator_events, special_wave_events])
@pytest.mark.parametrize("top", [False, True])
def test_first_formed_witness_is_causal_and_does_not_unlock_structural_pen(detector, top):
    bars, macd = special_distinct_extrema_sample(top)
    before = deepcopy(find_bis(find_fractals(merge_klines(bars[:15]))))
    full = detector(bars, macd)
    event = (
        next(e for e in full if e.signal_index == 9) if detector == special_wave_events else None
    )
    if detector == indicator_events:
        bars, macd = reverse_pen_sample(top)
        full = detector(bars, macd)
        event = full[0]
    assert event.confirmed_index == 14
    pens = find_bis(find_fractals(merge_klines(bars[:15])))
    assert pens[-1].confirmed_index is None
    assert (
        find_bis(find_fractals(merge_klines(special_distinct_extrema_sample(top)[0][:15])))
        == before
    )
    for n in range(10, 20):
        current = next(
            e
            for e in detector(bars[:n], {k: v[:n] for k, v in macd.items()})
            if e.signal_index == 9
        )
        assert current.confirmed_index == (14 if n > 14 else None)
        if n > 14:
            assert current == event
    changed = deepcopy(macd)
    changed["dif"][16] = changed["dif"][1]
    assert next(e for e in detector(bars, changed) if e.signal_index == 9) == event


def test_open_right_candle_never_confirms_and_flag_survives_replay():
    bars, macd = reverse_pen_sample()
    bars[14].is_closed = False
    (event,) = indicator_events(bars[:15], {k: v[:15] for k, v in macd.items()})
    assert event.confirmed_index is None
    frame = pd.DataFrame(
        [
            {
                "datetime": b.date,
                "open": b.open,
                "close": b.close,
                "high": b.high,
                "low": b.low,
                "is_closed": b.is_closed,
            }
            for b in bars[:15]
        ]
    )
    assert not _df_to_klines(frame)[-1].is_closed
    assert not ReplayBar(**frame.to_dict("records")[-1]).is_closed
    bounded = mark_indicator_closed_bars(frame, "DAY", datetime(2026, 1, 15, 14))
    assert not bounded.iloc[-1]["is_closed"]
    wave_bars, wave_macd = sample()
    wave_bars[-1].is_closed = False
    assert wave_events(wave_bars, wave_macd)[0].status == "candidate"


def test_dual_blocked_evidence_and_failure_are_serializable_and_explainable():
    bars, macd = reverse_pen_sample()
    macd["dif"][9] = macd["dif"][1]
    audit = []
    assert not indicator_events(bars, macd, diagnostics=audit)
    record = next(r for r in audit if r["c_start"] == 9 and r["direction"] == "down")
    assert record["status"] == "blocked"
    assert any(c["gate"] == "dual_dif_improves" and not c["passed"] for c in record["checks"])
    result = ChanlunResult(klines=bars, wave_diagnostics=audit).to_dict()
    assert result["wave_diagnostics"][-1]["dates"]["known_index"]


@pytest.mark.parametrize("family", ["standard", "nonstandard"])
def test_wave_equal_low_keeps_first_anchor_on_every_prefix(family):
    bars, macd = sample()
    bars[6].low = bars[5].low
    for n in (6, 7, 8):
        (event,) = wave_events(bars[:n], {k: v[:n] for k, v in macd.items()}, family=family)
        assert event.signal_index == 5


def test_full_a_price_is_not_silently_replaced_by_effective_a_price():
    bars, macd = sample()
    macd["dif"][1], macd["dea"][1] = 0.2, 0.3
    bars[1].low = 18
    assert wave_events(bars, macd)[0].status == "confirmed"
    audit = []
    (event,) = wave_events(bars, macd, family="nonstandard", diagnostics=audit)
    assert event.evidence["previous_price"] == 18
    assert event.evidence["c_price_reaches_a"] == 0
    record = next(r for r in audit if r["c_start"] == 5)
    price = next(c for c in record["checks"] if c["gate"] == "c_price_unrestricted")
    assert price["values"]["a_price"] == 18 and price["passed"]


@pytest.mark.parametrize("family", ["standard", "nonstandard"])
def test_equal_price_in_a_different_wave_remains_a_separate_event(family):
    bars, macd = sample()
    later = deepcopy(bars)
    for b in later:
        b.index += 8
        b.date += timedelta(days=8)
    events = wave_events(bars + later, {k: v + v for k, v in macd.items()}, family=family)
    confirmed = [e for e in events if e.status == "confirmed" and e.direction == "down"]
    assert [e.signal_index for e in confirmed] == [5, 13]


def test_short_history_exposes_missing_references_instead_of_silence():
    bars, macd = sample()
    audit = []
    indicator_events(bars[:3], {k: v[:3] for k, v in macd.items()}, diagnostics=audit)
    assert any(c["gate"] == "dual_reference_available" for r in audit for c in r["checks"])
    audit = []
    special_wave_events(bars[:3], {k: v[:3] for k, v in macd.items()}, diagnostics=audit)
    assert any(c["gate"] == "special_complete_a" for r in audit for c in r["checks"])


def test_real_special_every_prefix_around_first_confirmation():
    bars, macd = snapshot("603936-min60-qfq-20261003")
    at = next(i for i, b in enumerate(bars) if str(b.date) == "2026-09-22 11:30:00")
    final = next(e for e in special_wave_events(bars, macd) if e.signal_index == at)
    assert str(bars[final.confirmed_index].date) == "2026-09-28 15:00:00"
    for n in range(at + 1, len(bars) + 1):
        event = next(
            e
            for e in special_wave_events(bars[:n], {k: v[:n] for k, v in macd.items()})
            if e.signal_index == at
        )
        if n <= final.confirmed_index:
            assert event.status == "candidate" and event.confirmed_index is None
        else:
            assert event == final
