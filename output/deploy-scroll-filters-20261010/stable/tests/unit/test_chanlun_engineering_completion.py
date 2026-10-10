"""Historical M1 evidence is exact, time-bound and never clears natural blockers."""

from copy import deepcopy
from random import Random

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.engineering_completion import link_engineering_completions
from easy_tdx.chanlun.engineering_trends import engineering_movement_hierarchy
from easy_tdx.chanlun.expansion_regrouping import _completion_audit
from easy_tdx.chanlun.regrouping_versions import regrouping_versions
from tests.unit.test_chanlun_engineering_trends import PRICES as TREND_PRICES
from tests.unit.test_chanlun_signal_levels import fixture


def matching_fixture(mirror=False, offset=0):
    rng = Random(44)
    for _ in range(13):
        prices = [100.0]
        for i in range(28):
            prices.append(prices[-1] + (1 if i % 2 == 0 else -1) * rng.uniform(1, 15))
    # 20 units are enough to observe a genuine B -> A boundary revision.
    items, bars, macd = fixture(prices[:21], 3, 7, mirror)
    for item in items:
        item.index += offset
    return items, bars, macd


def all_audits(versions):
    for case in versions["cases"]:
        yield case["completion_audit"]
        yield from (r["completion_audit"] for r in case["revisions"])


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("offset", [0, 37])
def test_real_match_follows_source_across_changed_partition_roles(mirror, offset):
    items, bars, macd = matching_fixture(mirror, offset)
    original = regrouping_versions(items)
    hierarchy = engineering_movement_hierarchy(items, bars, macd)
    saved = deepcopy((original, hierarchy))
    linked = link_engineering_completions(original, hierarchy)
    case = linked["cases"][0]
    first, second = case["revisions"][:2]
    a = first["completion_audit"]["parts"][1]["engineering_completion"]
    b = second["completion_audit"]["parts"][0]["engineering_completion"]
    assert a and b and a["movement_id"] == b["movement_id"]
    assert a["source_segment_indices"] == list(range(3 + offset, 8 + offset))
    assert a["known_index"] == b["known_index"] == 140
    assert a["as_of_index"] == first["known_index"] < b["as_of_index"]
    assert a["direction"] == ("up" if mirror else "down")
    assert 0 < a["macd_evidence"]["area_ratio"] < 1
    for audit in all_audits(linked):
        assert not audit["natural_type_complete"] and not audit["eligible_for_recursive_input"]
        assert "same_level_completion_unproven" in audit["blocking_reasons"]
        for part in audit["parts"]:
            part.pop("engineering_completion")
    assert linked == original  # No existing fields, blockers or revisions changed.
    assert (original, hierarchy) == saved


def one_part_case(items, part, length):
    available = items[:length]
    revision = {"id": "test:v1", "parts": [deepcopy(part)]}
    audit = _completion_audit(revision, available, {s.index: i for i, s in enumerate(available)})
    audit["interpretation_id"] = audit.pop("candidate_id")
    revision["completion_audit"] = deepcopy(audit)
    return {
        "cases": [
            {
                "current_revision_id": revision["id"],
                "revisions": [revision],
                "completion_audit": audit,
            }
        ]
    }


def test_future_completion_cannot_leak_into_historical_audit():
    items, bars, macd = matching_fixture()
    hierarchy = engineering_movement_hierarchy(items, bars, macd)
    part = regrouping_versions(items)["cases"][0]["revisions"][0]["parts"][1]
    before = link_engineering_completions(one_part_case(items, part, 8), hierarchy)
    at = link_engineering_completions(one_part_case(items, part, 9), hierarchy)
    assert before["cases"][0]["completion_audit"]["parts"][0]["engineering_completion"] is None
    match = at["cases"][0]["completion_audit"]["parts"][0]["engineering_completion"]
    assert match["known_index"] == 140


@pytest.mark.parametrize("mirror", [False, True])
def test_exact_trend_part_links_but_not_as_a_single_centre_consolidation(mirror):
    items, bars, macd = fixture(TREND_PRICES, 4, 8, mirror)
    hierarchy = engineering_movement_hierarchy(items, bars, macd)
    record = hierarchy["levels"][0]["types"][0]
    assert record["kind"] == "trend"
    part = {**record, "component_kind": "trend_candidate", "known_index": items[8].confirmed_index}
    versions = one_part_case(items, part, 10)
    linked = link_engineering_completions(versions, hierarchy)
    assert (
        linked["cases"][0]["completion_audit"]["parts"][0]["engineering_completion"]["kind"]
        == "trend"
    )
    versions["cases"][0]["revisions"][0]["parts"][0].pop("component_kind")
    unlinked = link_engineering_completions(versions, hierarchy)
    assert unlinked["cases"][0]["completion_audit"]["parts"][0]["engineering_completion"] is None


@pytest.mark.parametrize(
    "fault",
    [
        "kind",
        "direction",
        "start",
        "end",
        "price",
        "range",
        "source",
        "level",
        "rule",
        "eligible",
        "opposite",
        "duplicate",
    ],
)
def test_similar_or_invalid_record_cannot_be_used_as_exact_evidence(fault):
    items, bars, macd = matching_fixture()
    hierarchy = engineering_movement_hierarchy(items, bars, macd)
    record = hierarchy["levels"][0]["types"][0]
    if fault == "kind":
        record["kind"] = "trend"
    elif fault == "direction":
        record["direction"] = "up"
    elif fault in ("start", "end"):
        record[f"{fault}_index"] += 1
    elif fault == "price":
        record["start_value"] += 1
    elif fault == "range":
        record["low"] -= 1
    elif fault == "source":
        record["source_segment_indices"] = [2, 3, 4, 5, 6]
    elif fault == "level":
        record["level"] = 2
    elif fault == "rule":
        hierarchy["rule"] = "unsupported"
    elif fault == "eligible":
        record["eligible_for_movement_recursion"] = False
    elif fault == "opposite":
        record["opposite_id"] = "segment:9"
    else:
        hierarchy["levels"][0]["types"].append(deepcopy(record))
    linked = link_engineering_completions(regrouping_versions(items), hierarchy)
    assert all(p["engineering_completion"] is None for a in all_audits(linked) for p in a["parts"])


def test_api_dates_prefixes_and_result_isolation():
    items, bars, macd = matching_fixture()
    result = ChanlunResult(xds=items, klines=bars, macd=macd)
    final = result.to_dict()
    linked = final["regrouping_versions"]["cases"][0]["revisions"][0]["completion_audit"]["parts"][
        1
    ]["engineering_completion"]
    assert linked["known_date"] == result._fmt_dt(bars[140].date)
    saved = deepcopy(final["regrouping_versions"])
    linked["macd_evidence"].clear()
    assert result.to_dict()["regrouping_versions"] == saved
    for known in (170, 175, 185, 195):
        for count in (known, known + 1):
            prefix = ChanlunResult(xds=items, klines=bars[:count], macd=macd).to_dict()
            for case in prefix["regrouping_versions"]["cases"]:
                full_case = next(
                    c for c in saved["cases"] if c["candidate_id"] == case["candidate_id"]
                )
                assert case["revisions"] == [
                    r for r in full_case["revisions"] if r["known_index"] < count
                ]
                for audit in [
                    case["completion_audit"],
                    *[r["completion_audit"] for r in case["revisions"]],
                ]:
                    for part in audit["parts"]:
                        match = part["engineering_completion"]
                        assert match is None or match["known_index"] <= audit["as_of_index"] < count
