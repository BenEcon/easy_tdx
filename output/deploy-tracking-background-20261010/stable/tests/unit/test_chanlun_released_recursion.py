"""Whole-domain release: real geometry/indicator examples and adversarial gates."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from easy_tdx.chanlun.released_recursion import (
    _finalize_placements,
    _ownership_domains,
    _placement,
    _requirements,
    released_movement_snapshot,
)
from easy_tdx.chanlun.types import Kline
from tests.unit.test_chanlun_engineering_movements import CONSOLIDATION, mixed_fixture
from tests.unit.test_chanlun_nested_ownership import run, triple_fixture
from tests.unit.test_chanlun_structure import signal_fixture


@pytest.mark.parametrize("count,required", [(9, 2), (27, 3), (81, 4)])
@pytest.mark.parametrize("input_level", [0, 2])
def test_release_respects_the_strongest_actual_upgrade(count, required, input_level):
    from tests.unit.test_chanlun_extension_recursion import oscillation

    items = oscillation(count)
    records = {
        s.index: {"id": f"unit:{s.index}", "source_segment_indices": [s.index]} for s in items
    }
    owners = _ownership_domains(items, records, input_level)
    assert owners
    assert max(d["required_parent_level"] for d in owners) == input_level + required
    assert all(d["natural_type_complete"] is False for d in owners)
    assert all(d["known_index"] <= items[-1].confirmed_index for d in owners)


@pytest.mark.parametrize("mirror", [False, True])
def test_four_level_release_reads_only_observable_macd_and_keeps_full_cover(mirror):
    from tests.unit.test_chanlun_recursive_causality import ObservableValues

    items, bars, macd = lift_fixture(lift_fixture(release_fixture(mirror), tail_step=10))
    complete = released_movement_snapshot(items, bars, macd)
    confirmation = complete["levels"][-1]["types"][0]["known_index"]
    for count in (confirmation, confirmation + 1):
        guarded = {k: ObservableValues(v, count) for k, v in macd.items()}
        actual = released_movement_snapshot(items, bars[:count], guarded)
        expected = released_movement_snapshot(
            items, bars[:count], {k: v[:count] for k, v in macd.items()}
        )
        assert actual == expected
        cover = [i for b in actual["source_cover"] for i in b["source_segment_indices"]]
        assert len(cover) == len(set(cover)) == actual["accepted_segment_count"]
        assert all(
            r["current_placement"]["known_index"] < count
            for layer in actual["levels"]
            for r in layer["types"]
        )


def release_fixture(mirror=False, offset=0, middle=65, reverse=90):
    """Actual expansion 24..31 spans child boundaries; completed M2 covers 0..32.

    Re-map two legs of the mixed example, retaining its synthetic MACD series.
    Neither claims, local completion nor indicator comparison is mocked.
    """
    old, bars, macd, widths = mixed_fixture()
    original = [100, 60, 90, 70, 85, 20, 150]
    targets = [100, 60, 90, middle, 85, 20, reverse]
    prices, start = [], 0
    for i, width in enumerate(widths):
        a, b = original[i : i + 2]
        x, y = targets[i : i + 2]
        prices.extend(x + (s.start.val - a) / (b - a) * (y - x) for s in old[start : start + width])
        start += width
    prices += [reverse, reverse - 1]
    if mirror:
        prices = [200 - p for p in prices]
        macd = {key: [-value for value in values] for key, values in macd.items()}
    items, _, _ = signal_fixture(prices)
    for item in items:
        item.index += offset
    changed = []
    for bar in bars:
        value = prices[min(bar.index // 4, len(prices) - 1)]
        changed.append(replace(bar, open=value, close=value, high=value, low=value))
    return items, changed, macd


def domain(identity, first, last, required=2):
    return {
        "id": identity,
        "source_segment_indices": list(range(first, last + 1)),
        "required_parent_level": required,
        "known_index": 100,
        "context_known_index": 80,
        "member_admissions": [
            {"source_segment_indices": [i], "admitted_index": 80} for i in range(first, last + 1)
        ],
    }


def record(first, last, level=2, known=150, required=()):
    return {
        "level": level,
        "source_segment_indices": list(range(first, last + 1)),
        "known_index": known,
        "original_known_index": known,
        "required_domain_ids": list(required),
    }


def test_late_higher_owner_is_repropagated_through_a_remote_witness():
    # Dependency-graph unit test: the owner is discovered after local children.
    # Geometry/MACD completion is covered separately by actual positive fixtures.
    bases = {str(i): {**record(i, i, 0), "id": str(i)} for i in range(16)}
    child = {
        **record(0, 3, 1),
        "id": "child",
        "child_ids": ["0", "1", "2", "3"],
        "opposite_id": "4",
    }
    reverse = {
        **record(4, 7, 1),
        "id": "reverse",
        "child_ids": ["4", "5", "6", "7"],
        "opposite_id": "8",
    }
    parent = {**record(0, 3, 2), "id": "parent", "child_ids": ["child"], "opposite_id": "reverse"}
    owner = domain("new-higher-owner", 8, 15, required=3)
    owner["known_index"] = owner["context_known_index"] = 200
    for admission in owner["member_admissions"]:
        admission["admitted_index"] = 200
    levels = [{"types": [child, reverse]}, {"types": [parent]}]
    records = {**bases, **{r["id"]: r for r in (child, reverse, parent)}}
    assert _placement(parent, reverse, [owner])["accepted"]
    _finalize_placements(levels, records, [owner])
    assert reverse["required_domain_ids"] == parent["required_domain_ids"] == [owner["id"]]
    assert not parent["eligible_for_external_recursion"]
    assert parent["current_placement"]["known_index"] >= reverse["current_placement"]["known_index"]
    assert parent["current_placement"]["known_index"] == 200


def lift_fixture(data, tail_step=1):
    """Replace each source leg by a complete local five-leg consolidation."""
    old, _, macd = data
    targets = [s.start.val for s in old] + [old[-1].end.val]
    pattern = CONSOLIDATION[:-1]
    prices, amplitudes = [], []
    for i, (a, b) in enumerate(zip(targets, targets[1:])):
        prices.extend(
            a + (b - a) * (p - pattern[0]) / (pattern[-1] - pattern[0]) for p in pattern[:-1]
        )
        amplitude = max(abs(macd["dif"][4 * i + 1]), 0.00001)
        amplitudes.extend(amplitude * (1 if k == 0 else 0.5 if k == 4 else 0.3) for k in range(5))
    reverse = 1 if old[-1].direction.value == "down" else -1
    prices += [targets[-1], targets[-1] + reverse * tail_step]
    amplitudes.append(0.00000001)
    items, _, _ = signal_fixture(prices)
    count = 101 + len(items) * 5
    bars = [
        Kline(
            i,
            datetime(2020, 1, 1) + timedelta(days=i),
            *[prices[min(i // 4, len(prices) - 1)]] * 4,
            0,
        )
        for i in range(count)
    ]
    values = [
        (1 if items[min(max(0, (i - 1) // 4), len(items) - 1)].direction.value == "up" else -1)
        * amplitudes[min(max(0, (i - 1) // 4), len(items) - 1)]
        for i in range(count)
    ]
    return (
        items,
        bars,
        {"dif": values, "dea": [v * 0.8 for v in values], "hist": [v * 0.4 for v in values]},
    )


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("offset", [0, 37])
def test_real_expansion_is_released_only_by_an_independently_completed_parent(mirror, offset):
    items, bars, macd = release_fixture(mirror, offset)
    inputs = deepcopy((items, bars, macd))
    result = released_movement_snapshot(items, bars, macd)
    assert [(lev["level"], len(lev["types"])) for lev in result["levels"]] == [(1, 6), (2, 1)]
    (owner,) = result["domains"]
    (parent,) = result["levels"][1]["types"]
    assert owner["source_segment_indices"] == list(range(offset + 24, offset + 32))
    assert owner["claim_kinds"] == ["expansion"]
    assert owner["status"] == "released_by_parent"
    assert owner["released_by_id"] == parent["id"]
    assert parent["source_segment_indices"] == list(range(offset, offset + 33))
    assert parent["known_index"] == 310
    assert parent["eligible_for_external_recursion"]
    assert not parent["required_domain_ids"]
    assert parent["direction"] == ("up" if mirror else "down")
    assert parent["id"] in result["external_frontier_ids"]
    assert all(
        not child["on_frontier"] and not child["eligible_for_external_recursion"]
        for child in result["levels"][0]["types"][:5]
    )
    conditional = [child for child in result["levels"][0]["types"] if child["required_domain_ids"]]
    assert conditional
    assert all(not child["eligible_for_external_recursion"] for child in conditional)
    covered = [
        i
        for lev in result["levels"]
        for r in lev["types"]
        if r["on_frontier"]
        for i in r["source_segment_indices"]
    ]
    assert len(covered) == len(set(covered))
    assert sorted(covered + result["unresolved_segment_indices"]) == [s.index for s in items]
    assert (items, bars, macd) == inputs
    assert not result["theory_equivalence_claim"] and not result["eligible_for_trading"]
    legacy = run(items, bars, macd)
    assert all(not v["eligible_for_external_recursion"] for v in legacy["versions"])


@pytest.mark.parametrize("fault", ["area", "dea", "reverse", "missing", "gap"])
def test_missing_parent_prerequisite_never_releases_owned_children(fault):
    items, bars, macd = release_fixture()
    if fault in ("area", "dea"):
        macd["hist" if fault == "area" else "dea"] = [-1.0] * len(bars)
    elif fault == "reverse":
        items[42].confirmed_index = None
    elif fault == "missing":
        macd = {}
    else:
        items[31].index += 1
    result = released_movement_snapshot(items, bars, macd)
    assert not any(d["released_by_id"] for d in result["domains"])


@pytest.mark.parametrize("mirror", [False, True])
def test_real_partial_domain_and_witness_dependency_are_not_silently_released(mirror):
    result = released_movement_snapshot(*release_fixture(mirror, middle=61, reverse=150))
    assert result["highest_completed_level"] == 2
    assert result["domains"][0]["source_segment_indices"] == list(range(19, 37))
    parent = result["levels"][1]["types"][0]
    assert parent["id"] not in result["external_frontier_ids"]
    assert not parent["on_frontier"]  # Deferred parent cannot hide legal children.
    assert result["levels"][0]["types"][0]["id"] in result["external_frontier_ids"]
    assert not result["domains"][0]["released_by_id"]
    assert parent["required_domain_ids"]
    assert parent["current_placement"]["reason"] == "partial_domain_coverage"


def test_all_conflicts_propagate_including_a_foreign_grandchild_witness():
    domains = [domain("a", 2, 5), domain("b", 10, 13)]
    child, witness = record(0, 3, 1), record(10, 10, 0)
    placement = _placement(child, witness, domains)
    assert [c["domain_id"] for c in placement["conflicts"]] == ["a", "b"]
    child["required_domain_ids"] = _requirements(child, witness, [], domains, placement)
    parent, parent_witness = record(0, 8), record(9, 9, 1)
    check = _placement(parent, parent_witness, domains)
    assert check["accepted"]  # Own geometry alone cannot detect child witness b.
    assert _requirements(parent, parent_witness, [child], domains, check) == ["b"]
    enclosing = record(0, 13, 3)
    check = _placement(enclosing, record(14, 14, 2), domains)
    assert _requirements(enclosing, record(14, 14, 2), [child], domains, check) == []


@pytest.mark.parametrize("case", ["partial", "level", "witness", "higher_owner"])
def test_non_release_gates(case):
    domains = [domain("a", 2, 8)]
    parent, witness = record(0, 10), record(11, 15, 1)
    if case == "partial":
        domains[0] = domain("a", 2, 12)
    elif case == "level":
        domains[0]["required_parent_level"] = 3
    elif case == "witness":
        domains.append(domain("b", 11, 20))
    else:
        domains.append(domain("higher", 0, 20, 3))
    result = _placement(parent, witness, domains)
    assert not result["eligible_for_external_recursion"]


def test_multiple_whole_domains_and_independently_released_witness_are_allowed():
    domains = [domain("a", 1, 4), domain("b", 6, 9), domain("reverse", 11, 15)]
    check = _placement(record(0, 10, 3), record(11, 16, 2), domains)
    assert check["accepted"] and check["eligible_for_external_recursion"]
    assert check["released_domain_ids"] == ["a", "b"]


@pytest.mark.parametrize("mirror", [False, True])
def test_confirmation_prefixes_future_suffixes_and_output_mutation(mirror):
    items, bars, macd = release_fixture(mirror)
    before = released_movement_snapshot(items, bars[:310], macd)
    assert not any(d["released_by_id"] for d in before["domains"])
    confirmed = released_movement_snapshot(items, bars[:311], macd)
    assert any(d["released_by_id"] for d in confirmed["domains"])
    frozen = deepcopy((before, confirmed))
    later = released_movement_snapshot(items, bars, macd)
    later["domains"][0]["member_admissions"].clear()
    later["levels"][0]["types"][0]["macd_evidence"].clear()
    assert (before, confirmed) == frozen
    assert confirmed == released_movement_snapshot(items, bars[:311], macd)
    changed = {
        key: values[:311] + [float("nan")] * (len(values) - 311) for key, values in macd.items()
    }
    assert confirmed == released_movement_snapshot(items, bars[:311], changed)


@pytest.mark.parametrize("mirror", [False, True])
def test_internal_three_levels_survive_later_domain_growth(mirror):
    result = released_movement_snapshot(*triple_fixture(mirror))
    assert [(lev["level"], len(lev["types"])) for lev in result["levels"]] == [
        (1, 86),
        (2, 16),
        (3, 1),
    ]
    assert not result["external_frontier_ids"]
    assert result["levels"][2]["types"][0]["known_index"] == 2280


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("depth", [1, 2])
def test_released_parents_form_third_and_fourth_levels_with_real_claims(depth, mirror):
    data = release_fixture(mirror)
    for step in range(depth):
        data = lift_fixture(data, tail_step=10 if step == 0 and depth == 2 else 1)
    result = released_movement_snapshot(*data)
    assert result["highest_completed_level"] == depth + 2
    (parent,) = result["levels"][-1]["types"]
    assert parent["id"] in result["external_frontier_ids"]
    assert parent["source_segment_indices"] == list(range(33 * 5**depth))
    assert any(
        d["input_level"] == depth and d["released_by_id"] == parent["id"] for d in result["domains"]
    )
    lookup = {r["id"]: r for lev in result["levels"] for r in lev["types"]}
    for r in lookup.values():
        if r["level"] > 1:
            children = [lookup[i] for i in r["child_ids"]]
            assert all(c["level"] == r["level"] - 1 for c in children)
            assert [i for c in children for i in c["source_segment_indices"]] == (
                r["source_segment_indices"]
            )
            assert r["known_index"] >= max(
                lookup[r["opposite_id"]]["known_index"], *(c["known_index"] for c in children)
            )
        assert r["known_index"] < len(data[1])
    earlier = released_movement_snapshot(data[0], data[1][: parent["known_index"]], data[2])
    assert not any(parent["id"] == identity for identity in earlier["external_frontier_ids"])


@pytest.mark.parametrize("mirror", [False, True])
def test_fourth_level_does_not_lose_a_remote_confirmation_dependency(mirror):
    result = released_movement_snapshot(*lift_fixture(lift_fixture(release_fixture(mirror))))
    (parent,) = result["levels"][-1]["types"]
    assert parent["level"] == 4 and parent["current_placement"]["accepted"]
    # The direct reverse is whole, but its own confirmation ultimately relies
    # on an unresolved owner beyond both the parent and its direct reverse.
    (required,) = parent["required_domain_ids"]
    owner = next(d for d in result["domains"] if d["id"] == required)
    assert owner["source_segment_indices"] == list(range(1060, 1080))
    assert not parent["on_frontier"] and not parent["eligible_for_external_recursion"]
    assert parent["id"] not in result["external_frontier_ids"]
