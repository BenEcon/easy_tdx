"""Independent waves, causal axis redefinition and unformed-candidate diagnostics."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.divergence_signals import _pivot_candidates, wave_events
from easy_tdx.chanlun.macd import calc_macd
from easy_tdx.chanlun.types import Kline


def sample(top=False):
    prices = [25, 10, 20, 22, 23, 19, 19.5, 21]
    bars = [
        Kline(i, datetime(2026, 1, 1) + timedelta(days=i), p + 0.5, p + 0.5, p + 1, p, 100)
        for i, p in enumerate(prices)
    ]
    macd = {
        "dif": [0.1, 0.1, -2, -1, -0.5, -1.5, -1.4, -1.3],
        "dea": [0.1, 0.1, -1.7, -1.2, -0.9, -1.3, -1.2, -1.1],
        "hist": [0.2, -20, -1, 0.3, 0.2, -0.5, -0.2, 0.1],
    }
    if top:
        bars = [
            Kline(b.index, b.date, 100 - b.open, 100 - b.close, 100 - b.low, 100 - b.high, 100)
            for b in bars
        ]
        macd = {k: [-v for v in values] for k, values in macd.items()}
    return bars, macd


@pytest.mark.parametrize("top", [False, True])
def test_all_statistics_use_effective_a_not_excluded_prefix(top):
    bars, macd = sample(top)
    (event,) = wave_events(bars, macd)
    assert event.evidence["a_start"] == 2 and event.evidence["original_a_start"] == 1
    assert event.reference_index == 2  # Excluded price 10 must not remain the reference.
    assert event.evidence["a_area"] == 1  # Excluded area 20 cannot make a false positive.
    assert event.evidence["c_area"] == pytest.approx(0.7)
    macd["hist"][5] = 2 if top else -2
    assert not wave_events(bars, macd)


@pytest.mark.parametrize("top", [False, True])
@pytest.mark.parametrize("index", [3, 4, 5, 6])
def test_b_or_c_crossings_cannot_be_trimmed_away(top, index):
    bars, macd = sample(top)
    macd["dea"][index] = 0
    audit = []
    events = wave_events(bars, macd, diagnostics=audit)
    assert not [e for e in events if e.status == "confirmed"]
    report = next(r for r in audit if r["c_start"] == 5)
    assert report["status"] == "blocked"
    assert any(g["gate"] == "dea_whole_abc_zero_axis" and not g["passed"] for g in report["checks"])
    assert report["rejections"]


def test_both_lines_must_enter_axis_and_missing_values_are_not_trimmed():
    bars, macd = sample()
    macd["dea"][2] = 0.1
    audit = []
    assert not wave_events(bars, macd, diagnostics=audit)
    assert any(not g["passed"] and g["gate"] == "a_axis_suffix" for g in audit[-2]["checks"])
    macd["dea"][2] = -1.7
    macd["dif"][1] = float("nan")
    audit = []
    assert not wave_events(bars, macd, diagnostics=audit)
    assert any(not g["passed"] and g["gate"] == "original_abc_finite" for g in audit[-2]["checks"])


def test_first_wave_still_not_a_and_failed_candidate_traces_serialize_independently():
    bars, macd = sample()
    audit = []
    assert not wave_events(bars[1:], {k: v[1:] for k, v in macd.items()}, diagnostics=audit)
    assert any(g["gate"] == "complete_colour_abc" and not g["passed"] for g in audit[-2]["checks"])
    macd["hist"][5] = -3
    audit = []
    wave_events(bars, macd, diagnostics=audit)
    report = next(r for r in audit if r["c_start"] == 5)
    assert report["first_candidate_index"] is None
    assert report["rejections"][0]["from_index"] == 5
    assert report["rejections"][0]["through_index"] == 7
    result = ChanlunResult(klines=bars, wave_diagnostics=audit)
    payload = result.to_dict()["wave_diagnostics"]
    assert payload[-2]["dates"]["a_start"] == "2026-01-03"
    assert payload[-2]["rejections"][0]["from_date"] == "2026-01-06"
    payload[-2]["checks"].clear()
    assert report["checks"]


@pytest.mark.parametrize("count", [600, 800])
@pytest.mark.parametrize("top", [False, True])
def test_frozen_lead_intelligent_cases_prefixes_and_mirrored_top(count, top):
    raw = json.loads(
        (Path(__file__).parents[1] / "fixtures/chanlun/300450-qfq-20261002.json").read_text()
    )
    assert raw["metadata"]["actual_adjust"] == "QFQ" and raw["metadata"]["source"] == "MAC"
    rows = raw["data"][-count:]
    bars = [
        Kline(
            i,
            datetime.fromisoformat(r["date"]),
            r["open"],
            r["close"],
            r["high"],
            r["low"],
            r["amount"],
        )
        for i, r in enumerate(rows)
    ]
    macd = calc_macd([b.close for b in bars], 12, 26, 9)
    if top:
        bars = [
            Kline(b.index, b.date, 200 - b.open, 200 - b.close, 200 - b.low, 200 - b.high, b.amount)
            for b in bars
        ]
        macd = {k: [-v for v in values] for k, values in macd.items()}

    def date(i):
        return bars[i].date.strftime("%Y-%m-%d") if i is not None else None

    direction = "up" if top else "down"
    # Local-pivot detector deliberately remains independent and fails these dates.
    assert not [
        e
        for e in _pivot_candidates(bars, macd)
        if e.direction == direction and date(e.signal_index) in ("2025-12-16", "2026-09-11")
    ]
    full = wave_events(bars, macd)
    for signal, confirmation, start, area in [
        ("2025-12-16", "2025-12-22", "2025-11-14", 12.6582789928),
        ("2026-09-11", "2026-09-16", "2026-06-26", 12.4928900854),
    ]:
        final = next(e for e in full if date(e.signal_index) == signal and e.direction == direction)
        assert final.status == "confirmed" and date(final.confirmed_index) == confirmation
        assert date(final.evidence["a_start"]) == start
        assert final.evidence["a_area"] == pytest.approx(area)
        # Every prefix from first candidate until confirmation proves no backdating.
        for n in range(final.signal_index + 1, final.confirmed_index + 2):
            current = next(
                e
                for e in wave_events(bars[:n], {k: v[:n] for k, v in macd.items()})
                if date(e.signal_index) == signal and e.direction == direction
            )
            assert current.confirmed_index == (
                final.confirmed_index if n > final.confirmed_index else None
            )
            assert current.status == ("confirmed" if n > final.confirmed_index else "candidate")
        payload = ChanlunResult(klines=bars, bcs=[final]).to_dict()["bcs"][0]
        assert payload["curr_date"] == signal and payload["confirmed_date"] == confirmation
    first = next(
        e for e in full if date(e.signal_index) == "2026-09-10" and e.direction == direction
    )
    assert first.status == "superseded" and date(first.invalidated_index) == "2026-09-11"
