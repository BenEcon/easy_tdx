"""Opposite base segments are traceable, not three independent completed types."""

from copy import deepcopy

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.anchors import extreme_index
from easy_tdx.chanlun.expansion_regrouping import expansion_regrouping
from tests.unit.test_chanlun_anchors import attach_extreme, bars_for
from tests.unit.test_chanlun_expansion_regrouping import LATER_VALID_PRICES, PRICES
from tests.unit.test_chanlun_structure import segments


@pytest.mark.parametrize("offset", [0, 23])
@pytest.mark.parametrize("sign", [1, -1])
def test_opposite_sources_distinguish_reused_partitions_from_external_continuation(offset, sign):
    items = segments([sign * p for p in PRICES])
    for item in items:
        item.index += offset
    before = deepcopy(items)
    result = expansion_regrouping(items)
    event = result["candidates"][0]
    audits = result["completion_audits"][0]["parts"]
    assert [a["opposite_evidence"]["source_part_index"] for a in audits] == [1, 2, None]
    for ordinal, audit in enumerate(audits):
        part = event["parts"][ordinal]
        evidence = audit["opposite_evidence"]
        line = next(s for s in items if s.index == evidence["segment_index"])
        assert evidence == {
            "segment_index": line.index,
            "direction": line.direction.value,
            "start_index": extreme_index(line.start),
            "end_index": extreme_index(line.end),
            "start_value": line.start.val,
            "end_value": line.end.val,
            "known_index": line.confirmed_index,
            "source_part_index": ordinal + 1 if ordinal < 2 else None,
        }
        assert evidence["start_index"] == part["end_index"]
        assert evidence["start_value"] == part["end_value"]
        assert evidence["segment_index"] == audit["opposite_segment_index"]
        assert evidence["known_index"] == audit["opposite_known_index"]
        assert not audit["natural_type_complete"]
        assert "same_level_completion_unproven" in audit["blocking_reasons"]
    assert not result["completion_audits"][0]["eligible_for_recursive_input"]
    assert items == before


def test_first_opposite_is_observed_only_at_its_confirmation_and_is_not_replaced():
    items = segments(PRICES)
    before = expansion_regrouping(items, 155)
    at = expansion_regrouping(items, 156)
    final = expansion_regrouping(items)
    assert before["candidates"][0] == at["candidates"][0] == final["candidates"][0]
    assert before["completion_audits"][0]["parts"][2]["opposite_evidence"] is None
    assert at["completion_audits"][0]["parts"][2]["opposite_evidence"]["segment_index"] == 11
    for size in range(12, len(items) + 1):
        now = expansion_regrouping(items[:size])
        assert now["completion_audits"][0]["parts"] == final["completion_audits"][0]["parts"]


@pytest.mark.parametrize("fault", ["unconfirmed", "disconnected", "raw_anchor"])
def test_invalid_first_reverse_cannot_be_replaced_by_a_later_valid_one(fault):
    items = segments(PRICES)
    if fault == "unconfirmed":
        items[11].confirmed_index = None
    elif fault == "disconnected":
        items[11].index += 1
    else:
        items[11].start = deepcopy(items[11].start)
        items[11].start.k.k_index += 1
    audit = expansion_regrouping(items)["completion_audits"][0]["parts"][2]
    assert audit["opposite_segment_index"] is None
    assert audit["opposite_evidence"] is None


def test_raw_extreme_dates_and_prices_match_the_actual_source_not_merged_tail():
    items = segments(PRICES)
    bars = bars_for(items)
    for point in (items[11].start, items[11].end):
        attach_extreme(point, bars)
    result = ChanlunResult(frequency="5min", klines=bars, xds=items).to_dict()
    audit = result["expansion_regrouping"]["completion_audits"][0]["parts"][2]
    evidence = audit["opposite_evidence"]
    for key, point in (("start", items[11].start), ("end", items[11].end)):
        raw = point.k.k_index - 1
        assert evidence[f"{key}_index"] == raw
        assert evidence[f"{key}_date"] == bars[raw].date.strftime("%Y-%m-%d %H:%M")
    assert evidence["known_date"] == audit["opposite_known_date"]
    assert evidence["known_index"] == 155
    assert not result["mmds"]
    assert not result["structure_metadata"]["recursive_levels_ready"]


def test_evidence_is_a_snapshot_not_a_shared_segment_or_candidate_object():
    items = segments(PRICES)
    result = expansion_regrouping(items)
    original = deepcopy(result)
    items[11].confirmed_index = 999
    assert result == original
    result["completion_audits"][0]["parts"][0]["opposite_evidence"]["start_value"] = 999
    assert result["candidates"] == original["candidates"]
    assert (
        result["completion_audits"][0]["parts"][1:]
        == (original["completion_audits"][0]["parts"][1:])
    )


def test_endpoint_preferred_candidates_keep_the_same_dependency_boundary():
    items = segments(LATER_VALID_PRICES)
    result = expansion_regrouping(items)
    event = next(
        e
        for e in result["candidates"]
        if e["partition_selection"] == "endpoint_consistent_preferred"
    )
    audit = next(a for a in result["completion_audits"] if a["candidate_id"] == event["id"])
    assert [p["opposite_evidence"]["source_part_index"] for p in audit["parts"]] == [1, 2, None]
    assert not audit["eligible_for_recursive_input"]
