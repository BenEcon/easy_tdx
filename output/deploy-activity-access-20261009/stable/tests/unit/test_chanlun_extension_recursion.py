"""No count-only promotion, causal regrouping and multi-level provenance."""

from copy import deepcopy

import pytest

from easy_tdx.chanlun.extension_recursion import extension_hierarchy
from tests.unit.test_chanlun_structure import segments


def oscillation(count):
    return segments([0, 10] + [2 if i % 2 == 0 else 8 for i in range(count - 1)])


@pytest.mark.parametrize(
    "count,levels", [(0, []), (3, []), (8, []), (9, [2]), (26, [2]), (27, [2, 3]), (81, [2, 3, 4])]
)
def test_extension_thresholds(count, levels):
    items = oscillation(count) if count else []
    result = extension_hierarchy(items)
    assert [p["level"] for p in result["proofs"]] == levels
    assert not result["natural_type_recursion_ready"]


def test_nine_is_not_nine_arbitrary_segments():
    items = segments([14, 10, 12, 8, 20, 16, 22, 18, 30, 26, 32, 28])
    assert not extension_hierarchy(items)["proofs"]


def test_proof_partitions_each_source_once_and_uses_whole_child_ranges():
    items = oscillation(27)
    root = extension_hierarchy(items)["proofs"][-1]

    def check(node):
        assert node["known_index"] >= max(
            items[i].confirmed_index for i in node["source_segment_indices"]
        )
        assert node["zd"] == max(low for low, _ in node["child_ranges"])
        assert node["zg"] == min(high for _, high in node["child_ranges"])
        assert node["zd"] < node["zg"]
        assert not node["natural_type_complete"]
        if node["children"]:
            flattened = [i for child in node["children"] for i in child["source_segment_indices"]]
            assert flattened == node["source_segment_indices"]
            for child in node["children"]:
                check(child)

    check(root)
    assert root["known_index"] == items[26].confirmed_index


def test_prefix_proofs_are_not_backdated_or_revised():
    items = oscillation(30)
    final = extension_hierarchy(items)["proofs"]
    for size in range(len(items) + 1):
        now = extension_hierarchy(items[:size])["proofs"]
        cutoff = items[size - 1].confirmed_index if size else -1
        assert now == [p for p in final if p["known_index"] <= cutoff]


def test_pending_ninth_departure_waits_for_failed_return():
    # First eight extend [2, 8]; ninth leaves upward, tenth returns to it.
    items = segments([0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 4])
    assert not extension_hierarchy(items[:9])["proofs"]
    proof = extension_hierarchy(items)["proofs"][0]
    assert proof["source_segment_indices"] == list(range(9))
    assert proof["known_index"] == items[9].confirmed_index


def test_successful_exit_does_not_supply_missing_ninth_member():
    items = segments([0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 9])
    assert not extension_hierarchy(items)["proofs"]


def test_cutoff_invalid_suffix_nonzero_ids_and_no_mutation():
    items = oscillation(12)
    for item in items:
        item.index += 20
    before = deepcopy(items)
    assert not extension_hierarchy(items, items[8].confirmed_index)["proofs"]
    proof = extension_hierarchy(items, items[8].confirmed_index + 1)["proofs"][0]
    assert proof["source_segment_indices"] == list(range(20, 29))
    assert items == before
    items[7].confirmed_index = None
    result = extension_hierarchy(items)
    assert result["accepted_segment_count"] == 7
    assert result["rejected_suffix_count"] == 5
    assert not result["proofs"]


def test_up_down_mirror():
    up = oscillation(27)
    down = segments([-item.start.val for item in up] + [-up[-1].end.val])
    left = extension_hierarchy(up)["proofs"]
    right = extension_hierarchy(down)["proofs"]
    for a, b in zip(left, right, strict=True):
        assert a["source_segment_indices"] == b["source_segment_indices"]
        assert a["known_index"] == b["known_index"]
        assert (a["zd"], a["zg"]) == (-b["zg"], -b["zd"])


def test_repeated_proof_has_same_known_time_when_nested():
    first, higher = extension_hierarchy(oscillation(27))["proofs"]
    nested = higher["children"][0]
    assert first["id"] == nested["id"]
    assert first["known_index"] == nested["known_index"]
    assert first["children"] == nested["children"]


def test_api_serialization_has_proof_dates_without_enabling_natural_recursion():
    from datetime import datetime, timedelta

    from easy_tdx.chanlun.analyser import ChanlunResult
    from easy_tdx.chanlun.types import Kline

    items = oscillation(27)
    bars = [
        Kline(i, datetime(2026, 1, 1) + timedelta(minutes=i), 5, 5, 10, 0, 1)
        for i in range(items[-1].confirmed_index + 1)
    ]
    result = ChanlunResult(frequency="5min", klines=bars, xds=items).to_dict()
    assert result["structure_metadata"]["extension_regrouping_ready"]
    assert not result["structure_metadata"]["recursive_levels_ready"]
    proof = result["extension_hierarchy"]["proofs"][0]
    assert proof["known_date"] == bars[items[8].confirmed_index].date.strftime("%Y-%m-%d %H:%M")
    assert proof["children"][0]["known_date"]
    assert not result["mmds"]


def test_proof_endpoint_uses_extreme_raw_bar_not_last_merged_bar():
    from datetime import datetime

    from easy_tdx.chanlun.types import Kline

    items = oscillation(9)
    point = items[0].start
    point.k.klines = [
        Kline(0, datetime(2026, 1, 1), 1, 1, 2, point.val, 1),
        Kline(1, datetime(2026, 1, 2), 1, 1, 2, 1, 1),
    ]
    proof = extension_hierarchy(items)["proofs"][0]
    assert proof["start_index"] == 0
    assert point.k.k_index == 1
