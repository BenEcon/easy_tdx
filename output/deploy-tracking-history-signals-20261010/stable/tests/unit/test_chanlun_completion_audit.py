"""Reject premature completion without changing frozen regrouping candidates."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.expansion_regrouping import expansion_regrouping
from easy_tdx.chanlun.types import Kline
from tests.unit.test_chanlun_expansion_regrouping import PRICES
from tests.unit.test_chanlun_structure import segments


def test_identifies_internal_extrema_without_rewriting_geometric_candidate():
    result = expansion_regrouping(segments(PRICES))
    event = result["candidates"][0]
    audit = result["completion_audits"][0]
    assert event["candidate_core"] == [101, 113]
    assert [p["status"] for p in audit["parts"]] == [
        "awaiting_same_level_completion",
        "endpoint_conflict",
        "endpoint_conflict",
    ]
    assert audit["parts"][1]["start_extreme"] == 116
    assert not audit["parts"][1]["start_is_extreme"]
    assert audit["parts"][2]["end_extreme"] == 113
    assert not audit["parts"][2]["end_is_extreme"]
    assert not audit["eligible_for_recursive_input"]
    assert all(not p["natural_type_complete"] for p in audit["parts"])


def test_continuation_updates_audit_only_when_next_segment_confirmed():
    items = segments(PRICES)
    before = expansion_regrouping(items, items[11].confirmed_index)
    at = expansion_regrouping(items, items[11].confirmed_index + 1)
    assert before["candidates"][0] == at["candidates"][0]
    a = before["completion_audits"][0]["parts"][-1]
    b = at["completion_audits"][0]["parts"][-1]
    assert a["opposite_segment_index"] is None
    assert a["opposite_known_index"] is None
    assert "no_confirmed_opposite_lower_unit" in a["blocking_reasons"]
    assert b["opposite_segment_index"] == 11
    assert b["opposite_known_index"] == items[11].confirmed_index
    assert b["status"] == "endpoint_conflict"
    assert "same_level_completion_unproven" in b["blocking_reasons"]


def test_empty_unformed_and_invalid_suffix_do_not_fabricate_evidence():
    assert not expansion_regrouping([])["completion_audits"]
    items = segments(PRICES)
    assert not expansion_regrouping(items[:10])["completion_audits"]
    items[11].confirmed_index = None
    audit = expansion_regrouping(items)["completion_audits"][0]
    assert audit["as_of_index"] == items[10].confirmed_index
    assert audit["parts"][-1]["opposite_segment_index"] is None


@pytest.mark.parametrize("offset", [0, 23])
def test_mirror_nonzero_ids_and_no_mutation(offset):
    left = segments(PRICES)
    right = segments([-p for p in PRICES])
    for item in left + right:
        item.index += offset
    saved = deepcopy(left)
    a = expansion_regrouping(left)["completion_audits"][0]
    b = expansion_regrouping(right)["completion_audits"][0]
    assert saved == left
    for p, q in zip(a["parts"], b["parts"], strict=True):
        assert p["status"] == q["status"]
        assert p["blocking_reasons"] == q["blocking_reasons"]
        assert p["start_extreme"] == -q["start_extreme"]
        assert p["end_extreme"] == -q["end_extreme"]
        assert p["opposite_segment_index"] == q["opposite_segment_index"]
        assert p["source_segment_indices"] == q["source_segment_indices"]


def test_api_dates_and_flags_stay_distinct_from_partition_formation():
    items = segments(PRICES)
    bars = [
        Kline(i, datetime(2026, 1, 1) + timedelta(minutes=i), 100, 100, 125, 90, 1)
        for i in range(items[-1].confirmed_index + 1)
    ]
    result = ChanlunResult(frequency="5min", klines=bars, xds=items).to_dict()
    regrouping = result["expansion_regrouping"]
    event, audit = regrouping["candidates"][0], regrouping["completion_audits"][0]
    assert event["known_index"] == 150
    assert audit["as_of_index"] == items[-1].confirmed_index
    part = audit["parts"][-1]
    assert part["opposite_known_date"] == bars[155].date.strftime("%Y-%m-%d %H:%M")
    assert not result["structure_metadata"]["recursive_levels_ready"]
    assert not result["mmds"]
