"""Approved Oct 7 standard rules: causal lifecycle, mirrored prices and B axis."""

import json
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.divergence_signals import link_wave_families, special_wave_events, wave_events
from easy_tdx.chanlun.macd import calc_macd
from easy_tdx.chanlun.types import Kline
from tests.unit.test_wave_rule_comparison import sample


@pytest.mark.parametrize("top", [False, True])
@pytest.mark.parametrize(
    "b,c,passed", [(20, 20, True), (18, 19, False), (18, 18, True), (18, 17, True)]
)
def test_b_unrestricted_c_must_reach_both_a_and_b(top, b, c, passed):
    bars, macd = sample(top)
    key = "high" if top else "low"
    setattr(bars[3], key, 100 - b if top else b)
    for i in (5, 6):
        setattr(bars[i], key, 100 - c if top else c)
    audit = []
    events = wave_events(bars, macd, diagnostics=audit)
    assert bool(events) == passed
    assert not wave_events(bars, macd, legacy_standard=True)
    old = next(r for r in audit if r["c_start"] == 5)["comparisons"][-1]
    assert old["mode"] == "legacy_standard" and not old["passed"]
    if passed:
        assert events[-1].status == "confirmed"
        assert events[-1].evidence["legacy_b_price_passed"] == 0
        assert events[-1].evidence["rule_version"] == 2026100717


def excursion_sample(values, top=False):
    dif = [0.1, -2, -2] + values + [-1.5, -1.4, -1.3]
    dea = [0.1, -1.8, -1.7] + [-1.2] * len(values) + [-1.3, -1.2, -1.4]
    hist = [0.2, -2, -1] + [0.2] * len(values) + [-0.5, -0.2, 0.1]
    prices = [25, 24, 20] + [22] * len(values) + [19, 19.5, 21]
    bars = [
        Kline(i, datetime(2026, 1, 1) + timedelta(days=i), p + 0.5, p + 0.5, p + 1, p, 100)
        for i, p in enumerate(prices)
    ]
    macd = dict(dif=dif, dea=dea, hist=hist)
    if top:
        bars = [
            Kline(b.index, b.date, 100 - b.open, 100 - b.close, 100 - b.low, 100 - b.high, 100)
            for b in bars
        ]
        macd = {k: [-v for v in vs] for k, vs in macd.items()}
    return bars, macd


@pytest.mark.parametrize("top", [False, True])
@pytest.mark.parametrize(
    "values,passed",
    [
        ([-1, 0, 0, 0, 0, 0, -1], True),
        ([0] * 6, False),
        ([0.1] * 5, True),
        ([100] * 5, True),
        ([0.1] * 6, False),
        ([0, -1, 0], False),
        ([-1] * 7, True),
    ],
)
def test_single_b_excursion_touch_counts_and_six_fails(top, values, passed):
    bars, macd = excursion_sample(values, top)
    audit = []
    events = wave_events(bars, macd, diagnostics=audit)
    assert bool(events) == passed
    check = next(
        g
        for r in audit
        if r["c_start"] == 3 + len(values)
        for g in r["checks"]
        if g["gate"] == "b_dif_single_excursion"
    )
    assert check["passed"] == passed
    if passed:
        assert events[-1].confirmed_index == len(bars) - 1
    if any(v >= 0 for v in values):
        assert not wave_events(bars, macd, legacy_standard=True)


@pytest.mark.parametrize("top", [False, True])
@pytest.mark.parametrize("line,index", [("dea", 3), ("dif", 5), ("dea", 5)])
def test_dea_b_and_both_c_axis_still_strict(top, line, index):
    bars, macd = sample(top)
    macd[line][index] = 0
    assert not wave_events(bars, macd)


def actual_case():
    raw = json.loads(
        (Path(__file__).parents[1] / "fixtures/chanlun/600699-qfq-20260929.json").read_text()
    )
    rows = raw["bars"][-600:]
    bars = [
        Kline(
            i,
            datetime.fromisoformat(r.get("datetime", r.get("date"))),
            r["open"],
            r["close"],
            r["high"],
            r["low"],
            r.get("amount", 0),
        )
        for i, r in enumerate(rows)
    ]
    return bars, calc_macd([b.close for b in bars], 12, 26, 9)


@pytest.mark.parametrize("top", [False, True])
def test_600699_confirmation_and_links_never_use_future_bars(top):
    bars, macd = actual_case()
    if top:
        bars = [
            Kline(b.index, b.date, 100 - b.open, 100 - b.close, 100 - b.low, 100 - b.high, b.amount)
            for b in bars
        ]
        macd = {k: [-v for v in vs] for k, vs in macd.items()}
    at = next(i for i, b in enumerate(bars) if str(b.date.date()) == "2026-09-16")
    special_original = special_wave_events(bars, macd)
    all_events = wave_events(bars, macd) + deepcopy(special_original)
    before = [asdict(e) for e in all_events]
    link_wave_families(all_events, bars)
    for e, original in zip(all_events, before):
        updated = asdict(e)
        updated.pop("related_events")
        original.pop("related_events")
        assert updated == original
    target = next(e for e in all_events if e.bc_type.value == "macd_wave" and e.signal_index == at)
    assert target.confirmed_index == at + 1
    assert target.evidence["price"] == pytest.approx(82.20 if top else 17.80)
    assert any(
        r["signal_date"].startswith("2026-09-11") and r["invalidated_date"].startswith("2026-09-15")
        for r in target.related_events
    )
    assert not any(e.signal_index == at for e in wave_events(bars, macd, legacy_standard=True))
    for count in range(at - 3, at + 4):
        prefix = wave_events(bars[:count], {k: v[:count] for k, v in macd.items()})
        assert [e.signal_index for e in prefix if e.status == "confirmed"] == [
            e.signal_index
            for e in all_events
            if e.bc_type.value == "macd_wave"
            and e.confirmed_index is not None
            and e.confirmed_index < count
        ]
        matched = [e for e in prefix if e.signal_index == at]
        if count <= at:
            assert not matched
        else:
            assert matched[-1].status == ("confirmed" if count > at + 1 else "candidate")
    payload = ChanlunResult(klines=bars, bcs=all_events).to_dict()
    exported = next(
        e for e in payload["bcs"] if e["type"] == "macd_wave" and e["signal_index"] == at
    )
    assert exported["related_events"] and exported["confirmed_date"] == "2026-09-17"
