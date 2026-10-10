"""Exported research evidence must never write through to an analysis snapshot."""

from copy import deepcopy
from dataclasses import fields, is_dataclass

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.structure import find_structural_centres
from easy_tdx.chanlun.structure_signals import structure_signals, to_chart_signals
from tests.unit.test_chanlun_anchors import bars_for
from tests.unit.test_chanlun_expansion_regrouping import PRICES
from tests.unit.test_chanlun_structure import segments, signal_fixture

SIGNAL_PRICES = [30, 40, 32, 38, 20, 26, 22, 25, 18, 28, 26, 30, 24, 31, 23, 32]


def snapshot(kind="signals", sign=1):
    if kind == "signals":
        items, bars, macd = signal_fixture(SIGNAL_PRICES)
        if sign < 0:
            items = segments([-p for p in SIGNAL_PRICES])
            for bar in bars:
                bar.open, bar.close = -bar.open, -bar.close
                bar.high, bar.low = -bar.low, -bar.high
            macd = {key: [-value for value in values] for key, values in macd.items()}
        signals = structure_signals(items, bars, macd)
    else:
        prices = PRICES if kind == "expansion" else [0, 10] + [2, 8] * 40
        items = segments([sign * p for p in prices])
        bars, macd, signals = bars_for(items), {}, []
    mmds, bcs = to_chart_signals(signals, items)
    # A nested feature-sequence shape, including intentional shared input evidence.
    items[0].evidence = {
        "features": [{"source_pen_indices": [0, 2, 4], "range": [items[0].low, items[0].high]}]
    }
    pending = deepcopy(items[-1])
    pending.confirmed_index = None
    pending.evidence = items[0].evidence
    return ChanlunResult(
        frequency="5min",
        klines=bars,
        xds=items,
        unfinished_xd=pending,
        macd=macd,
        structural_centres=find_structural_centres(items),
        structural_signals=signals,
        mmds=mmds,
        bcs=bcs,
    )


def mutable_ids(value, seen=None):
    """Walk dataclasses as well as JSON containers, without revisiting shared nodes."""
    seen = set() if seen is None else seen
    if id(value) in seen:
        return set()
    seen.add(id(value))
    if isinstance(value, dict):
        children, own = value.values(), {id(value)}
    elif isinstance(value, list | set):
        children, own = value, {id(value)}
    elif isinstance(value, tuple):
        children, own = value, set()
    elif is_dataclass(value) and not isinstance(value, type):
        children, own = (getattr(value, f.name) for f in fields(value)), set()
    else:
        return set()
    for child in children:
        own.update(mutable_ids(child, seen))
    return own


@pytest.mark.parametrize("kind", ["signals", "extension", "expansion"])
@pytest.mark.parametrize("sign", [1, -1])
def test_exports_share_no_mutable_container_with_source_or_other_exports(kind, sign):
    result = snapshot(kind, sign)
    first, second = result.to_dict(), result.to_dict()
    assert first == second
    assert not mutable_ids(first) & mutable_ids(result)
    assert not mutable_ids(first) & mutable_ids(second)
    assert not first["structure_metadata"]["recursive_levels_ready"]
    assert not first["extension_hierarchy"]["natural_type_recursion_ready"]


@pytest.mark.parametrize(
    "field", ["xds", "unfinished_xd", "mmds", "bcs", "structural_centres", "structural_signals"]
)
def test_editing_exported_evidence_preserves_source_and_repeat_serialization(field):
    result = snapshot()
    original = deepcopy(result)
    exported = result.to_dict()
    baseline = deepcopy(exported)
    if field == "structural_centres":
        centre = next(c for c in exported[field] if c["relation_history"])
        centre["relation_history"][0]["member_segments"].append(999)
        centre["relation_history"][0]["previous_envelope"][0] = -999
    elif field == "unfinished_xd":
        exported[field]["evidence"]["features"][0]["source_pen_indices"].append(999)
    elif field == "xds":
        exported[field][0]["evidence"]["features"][0]["range"][0] = -999
    elif field == "mmds":
        event = next(e for e in exported[field] if "b_segments" in e["evidence"])
        event["evidence"]["b_segments"].append(999)
    elif field == "structural_signals":
        event = next(e for e in exported[field] if "b_segments" in e["evidence"])
        event["evidence"]["b_segments"].clear()
    else:
        assert exported[field]
        exported[field][0]["evidence"]["a_start"] = 999
    assert result == original
    assert result.to_dict() == baseline


def test_exported_sibling_evidence_is_independent_even_if_source_is_shared():
    result = snapshot()
    assert result.xds[0].evidence is result.unfinished_xd.evidence
    exported = result.to_dict()
    before = deepcopy(exported["unfinished_xd"])
    exported["xds"][0]["evidence"]["features"][0]["source_pen_indices"].clear()
    assert exported["unfinished_xd"] == before


@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("edit_source", [False, True])
def test_chart_conversion_detaches_nested_evidence_in_both_directions(sign, edit_source):
    result = snapshot(sign=sign)
    events = result.structural_signals
    first = next(e for e in events if e.signal_type in ("1buy", "1sell"))
    # Future nested evidence remains protected too; copying only b_segments is insufficient.
    first.evidence["audit"] = {"sources": [{"indices": [1, 2, 3]}]}
    source_before = deepcopy(events)
    mmds, bcs = to_chart_signals(events, result.xds)
    mmd = next(m for m in mmds if "audit" in m.evidence)
    output_before = deepcopy((mmds, bcs))
    assert not mutable_ids(mmd.evidence) & mutable_ids(first.evidence)
    if edit_source:
        first.evidence["audit"]["sources"][0]["indices"].clear()
        first.evidence["b_segments"].clear()
        assert (mmds, bcs) == output_before
    else:
        mmd.evidence["audit"]["sources"][0]["indices"].append(999)
        mmd.evidence["b_segments"].append(999)
        assert events == source_before
        assert to_chart_signals(events, result.xds) == output_before


@pytest.mark.parametrize("kind", ["signals", "extension", "expansion"])
def test_existing_export_remains_stable_when_live_evidence_changes(kind):
    result = snapshot(kind)
    exported = result.to_dict()
    before = deepcopy(exported)
    result.xds[0].evidence["features"][0]["source_pen_indices"].append(999)
    for centre in result.structural_centres:
        for relation in centre.relation_history:
            relation["current_envelope"][0] = -999
    for event in result.mmds + result.bcs:
        event.evidence["new_note"] = {"indices": [999]}
    assert exported == before


def test_empty_result_exports_are_independent_and_serializable():
    import json

    result = ChanlunResult()
    exported = result.to_dict()
    assert json.loads(json.dumps(exported)) == exported
    exported["structure_metadata"]["recursive_levels_ready"] = True
    exported["xds"].append({"evidence": {}})
    assert not result.to_dict()["structure_metadata"]["recursive_levels_ready"]
    assert not result.xds
