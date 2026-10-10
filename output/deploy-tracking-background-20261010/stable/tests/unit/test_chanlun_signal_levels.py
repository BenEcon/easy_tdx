"""An admitted extension cannot impersonate a peer base centre in trend signals."""

from copy import deepcopy
from importlib import import_module

import pandas as pd
import pytest

from easy_tdx.chanlun.analyser import ChanlunAnalyser, ChanlunResult
from easy_tdx.chanlun.anchors import extreme_index
from easy_tdx.chanlun.divergence_signals import segment_evidence
from easy_tdx.chanlun.extension_recursion import centre_extension_proof, extension_hierarchy
from easy_tdx.chanlun.structure import iter_structural_steps
from easy_tdx.chanlun.structure_signals import structure_signals, to_chart_signals
from easy_tdx.chanlun.types import Kline
from tests.unit.test_chanlun_structure import segments, signal_fixture

PREVIOUS = [30, 40, 32, 38, 32, 38, 32, 38, 32, 38, 20, 26, 22, 25, 18, 28, 26]
CURRENT = [30, 40, 32, 38, 20, 26, 22, 25, 22, 25, 22, 25, 22, 25, 18, 28, 26]
LATER = [30, 40, 32, 38, 20, 26, 22, 25, 22, 25, 22, 25, 18, 24, 17]


def fixture(prices, entry, departure, mirror=False):
    items, bars, _ = signal_fixture(prices)
    macd = {"dif": [-0.5] * len(bars), "dea": [-0.4] * len(bars), "hist": [0.1] * len(bars)}
    for segment_id, values in [(entry, (-3, -2.5, -2)), (departure, (-1.5, -1.2, -0.5))]:
        line = items[segment_id]
        for i in range(extreme_index(line.start), extreme_index(line.end) + 1):
            for key, value in zip(("dif", "dea", "hist"), values, strict=True):
                macd[key][i] = value
    if mirror:
        items = segments([100 - p for p in prices])
        bars = [
            Kline(b.index, b.date, 100 - b.open, 100 - b.close, 100 - b.low, 100 - b.high, b.amount)
            for b in bars
        ]
        macd = {key: [-v for v in values] for key, values in macd.items()}
    a, c = items[entry], items[departure]
    assert segment_evidence(
        bars,
        macd,
        (extreme_index(a.start), extreme_index(a.end)),
        (extreme_index(c.start), extreme_index(c.end)),
        c.direction.value,
    )
    return items, bars, macd


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("offset", [0, 37])
@pytest.mark.parametrize("prices,entry,promoted", [(PREVIOUS, 9, 0), (CURRENT, 3, 1)])
def test_either_promoted_centre_blocks_first_and_derived_second_not_independent_third(
    prices, entry, promoted, mirror, offset
):
    items, bars, macd = fixture(prices, entry, 13, mirror)
    for item in items:
        item.index += offset
    proofs = extension_hierarchy(items)["proofs"]
    assert any(p["base_centre_index"] == promoted and p["known_index"] < 165 for p in proofs)
    events = structure_signals(items, bars, macd)
    assert not any(e.signal_type in ("1buy", "1sell", "2buy", "2sell") for e in events)
    assert any(
        e.signal_type == ("3sell" if mirror else "3buy") and e.segment_index == offset + 15
        for e in events
    )
    mmds, divergences = to_chart_signals(events, items)
    assert all(m.mmd_type.value.startswith("3") for m in mmds)
    assert not divergences  # No downgraded consolidation label for the rejected trend pair.


@pytest.mark.parametrize("mirror", [False, True])
def test_later_upgrade_preserves_earlier_first_but_stops_its_later_second(mirror):
    items, bars, macd = fixture(LATER, 3, 11, mirror)
    proof = extension_hierarchy(items)["proofs"][0]
    assert proof["known_index"] == 160
    events = structure_signals(items, bars, macd)
    first = next(e for e in events if e.signal_type == ("1sell" if mirror else "1buy"))
    assert first.segment_index == 11 and first.confirmed_index == 155
    assert not any(e.signal_type in ("2buy", "2sell") for e in events)
    for count in sorted(
        {0, *(s.confirmed_index for s in items), *(s.confirmed_index + 1 for s in items)}
    ):
        prefix = structure_signals(items, bars[:count], macd)
        assert prefix == [e for e in events if e.confirmed_index < count]


def test_equal_confirmation_batch_checks_upgrade_before_publishing_first():
    items, bars, macd = fixture(LATER, 3, 11)
    for item in items:
        item.confirmed_index = 190
    assert not structure_signals(items, bars[:190], macd)
    events = structure_signals(items, bars[:191], macd)
    assert events and not any(e.signal_type in ("1buy", "2buy") for e in events)
    assert events == structure_signals(items, bars, macd)


def test_gate_requires_actual_proof_not_only_nine_count(monkeypatch):
    module = import_module("easy_tdx.chanlun.structure_signals")
    items, bars, macd = fixture(CURRENT, 3, 13)
    monkeypatch.setattr(module, "centre_extension_proof", lambda *_: None)
    events = structure_signals(items, bars, macd)
    assert {"1buy", "2buy", "3buy"} <= {e.signal_type for e in events}


@pytest.mark.parametrize("fault", ["gap", "unconfirmed", "raw_future"])
def test_invalid_tail_cannot_supply_upgrade_evidence(fault):
    items, bars, macd = fixture(LATER, 3, 11)
    expected = structure_signals(items[:12], bars, macd)
    assert any(e.signal_type == "1buy" for e in expected)
    if fault == "gap":
        items[12].index += 1
    elif fault == "unconfirmed":
        items[12].confirmed_index = None
    else:
        items[12].end = deepcopy(items[12].end)
        items[12].end.k.k_index = 9999
    assert structure_signals(items, bars, macd) == expected


def test_waiting_ninth_member_does_not_promote_until_failed_return_admits_it():
    items = segments([0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 4])
    lookup = {s.index: s for s in items}
    seen = []
    for current, centre, _ in iter_structural_steps(items):
        proof = centre_extension_proof(centre, lookup) if centre else None
        seen.append(proof)
        if current.index == 8:
            assert centre.departure_segment == 8
            assert proof is None
    assert all(p is None for p in seen[:-1])
    assert seen[-1] == extension_hierarchy(items)["proofs"][0]
    assert seen[-1]["known_index"] == items[9].confirmed_index
    assert seen[-1]["source_segment_indices"] == list(range(9))


def test_rejected_trend_does_not_reach_serialized_chart_and_policy_is_explicit():
    items, bars, macd = fixture(CURRENT, 3, 13)
    events = structure_signals(items, bars, macd)
    mmds, bcs = to_chart_signals(events, items)
    result = ChanlunResult(
        frequency="daily",
        xds=items,
        klines=bars,
        macd=macd,
        structural_signals=events,
        mmds=mmds,
        bcs=bcs,
    )
    payload = result.to_dict()
    assert payload["structure_metadata"]["trend_signal_level_policy"] == (
        "unpromoted_centres_at_confirmation_v1"
    )
    assert not payload["structure_metadata"]["recursive_levels_ready"]
    assert all(e["type"].startswith("3") for e in payload["mmds"])
    assert not payload["bcs"]


@pytest.mark.parametrize("mirror", [False, True])
def test_factor_and_strategy_consume_filtered_events_but_keep_third_class(monkeypatch, mirror):
    from easy_tdx.backtest.strategies.builtin import _chanlun_mmd_signal_arrays
    from easy_tdx.factor.builtin.chanlun import ChanlunMMD

    items, bars, macd = fixture(CURRENT, 3, 13, mirror)
    events = structure_signals(items, bars, macd)
    mmds, bcs = to_chart_signals(events, items)
    result = ChanlunResult(xds=items, klines=bars, mmds=mmds, bcs=bcs)
    monkeypatch.setattr(ChanlunAnalyser, "process_klines", lambda *_: result)
    values = ChanlunMMD().compute(pd.DataFrame(index=range(len(bars))))
    assert set(values.unique()) <= {0, 3, -3}
    assert values.iloc[175] == (-3 if mirror else 3)
    flat = [10.0] * len(bars)
    for ordinal in ("一", "二"):
        buy, sell = _chanlun_mmd_signal_arrays(
            flat,
            flat,
            flat,
            flat,
            flat,
            bi_rule="新笔",
            zs_min_lines=3,
            entry=f"{ordinal}类买点",
            exit_=f"{ordinal}类卖点",
        )
        assert not buy.any() and not sell.any()
    buy, sell = _chanlun_mmd_signal_arrays(
        flat,
        flat,
        flat,
        flat,
        flat,
        bi_rule="新笔",
        zs_min_lines=3,
        entry="三类买点",
        exit_="三类卖点",
    )
    assert (sell if mirror else buy)[175]
