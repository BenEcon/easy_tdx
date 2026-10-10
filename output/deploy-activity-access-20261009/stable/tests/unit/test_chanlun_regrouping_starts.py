"""Anchored start revision preserves all sources without inventing completion."""

from copy import deepcopy

import pytest

from easy_tdx.chanlun.regrouping_versions import _search_start, regrouping_versions
from tests.unit.test_chanlun_regrouping_versions import assert_causal
from tests.unit.test_chanlun_structure import segments

PRICES = [
    100,
    112,
    96,
    99,
    83,
    95,
    82,
    92,
    82,
    90,
    83,
    98,
    86,
    98,
    83,
    98,
    90,
    102,
    94,
    106,
    99,
    101,
    90,
    92,
    85,
    90,
    86,
]


@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("offset", [0, 37])
def test_start_revision_retains_detached_sources_and_actual_knowledge(sign, offset):
    items = segments([sign * p for p in PRICES])
    for s in items:
        s.index += offset
    original = deepcopy(items)
    result = regrouping_versions(items)
    case = next(
        c for c in result["cases"] if c["candidate_id"] == f"expansion:{6 + offset}:{15 + offset}"
    )
    assert result["rule"] == "causal_regrouping_versions_v3"
    assert case["origin_start_segment_index"] == 6 + offset
    assert case["start_anchor_segment_indices"] == list(range(6 + offset, 14 + offset))
    revision = case["revisions"][2]
    assert revision["known_index"] == items[21].confirmed_index == 205
    assert revision["reason"] == "start_boundary_regrouping"
    assert revision["status"] == "endpoint_consistent_draft"
    assert revision["source_segment_indices"] == list(range(11 + offset, 22 + offset))
    assert revision["retained_prefix_segment_indices"] == list(range(6 + offset, 11 + offset))
    assert revision["prefix_role"] == "unresolved_prior_sources"
    assert revision["start_change"] == {
        "previous_start_segment_index": 6 + offset,
        "current_start_segment_index": 11 + offset,
        "detached_segment_indices": list(range(6 + offset, 11 + offset)),
        "reincorporated_segment_indices": [],
    }
    assert [len(p["source_segment_indices"]) for p in revision["parts"]] == [3, 5, 3]
    assert revision["candidate_core"] == ([90, 98] if sign == 1 else [-98, -90])
    assert not revision["natural_type_complete"] and not revision["eligible_for_recursive_input"]
    assert case["revisions"][1]["retained_prefix_segment_indices"] == []
    assert case["revisions"][1]["source_segment_indices"][0] == 6 + offset
    assert items == original
    assert_causal(items)


def test_every_snapshot_covers_origin_to_frontier_once_in_three_roles():
    items = segments(PRICES)
    for size in range(len(items) + 1):
        for c in regrouping_versions(items[:size])["cases"]:
            current = c["revisions"][-1]
            combined = (
                current["retained_prefix_segment_indices"]
                + current["source_segment_indices"]
                + c["pending_segment_indices"]
            )
            assert combined == list(range(c["origin_start_segment_index"], size))
            for r in c["revisions"]:
                assert r["source_segment_indices"][0] in c["start_anchor_segment_indices"]
                if r["parts"]:
                    assert [s for p in r["parts"] for s in p["source_segment_indices"]] == (
                        r["source_segment_indices"]
                    )


def test_sources_cannot_slide_outside_original_left_centre_to_find_unrelated_structure():
    items = segments(PRICES)
    # The valid later interpretation begins at 11. Anchoring only to 6..10
    # excludes it even though there is ample later input available.
    start, parts = _search_start(items, list(range(6, 11)), 22)
    assert start == 6
    assert parts is None
    start, parts = _search_start(items, list(range(6, 14)), 22)
    assert start == 11 and parts


def test_original_start_is_preferred_when_it_already_has_consistent_endpoints():
    items = segments(PRICES)
    first, parts = _search_start(items, [11, 12, 13], 22)
    assert first == 11
    assert parts and len(parts) == 3


def test_same_confirmation_group_keeps_only_final_start_change_from_visible_previous_version():
    items = segments(PRICES)
    for item in items:
        item.confirmed_index = 250
    for case in regrouping_versions(items)["cases"]:
        assert len(case["revisions"]) == 1
        revision = case["revisions"][0]
        if revision["start_change"]:
            assert (
                revision["start_change"]["previous_start_segment_index"]
                == (case["origin_start_segment_index"])
            )
    assert_causal(items)


@pytest.mark.parametrize("fault", ["unconfirmed", "gap", "future", "nan"])
def test_invalid_input_cannot_trigger_the_new_start_revision(fault):
    items = segments(PRICES)
    if fault == "unconfirmed":
        items[21].confirmed_index = None
    elif fault == "gap":
        items[21].index += 1
    elif fault == "future":
        items[21].end = deepcopy(items[21].end)
        items[21].end.k.k_index = 999
    else:
        items[21].high = float("nan")
    assert regrouping_versions(items)["cases"] == regrouping_versions(items[:21])["cases"]
