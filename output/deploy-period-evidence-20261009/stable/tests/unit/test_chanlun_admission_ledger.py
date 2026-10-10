"""A segment's own confirmation is not the time it joined a centre."""

from copy import deepcopy
from random import Random

import pytest

from easy_tdx.chanlun.extension_recursion import extension_hierarchy
from easy_tdx.chanlun.structure import find_structural_centres
from tests.unit.test_chanlun_structure import segments


@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("offset", [0, 21])
def test_ninth_departure_admitted_at_return_not_own_confirmation(sign, offset):
    items = segments([sign * p for p in [0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 4]])
    for item in items:
        item.index += offset
    before = deepcopy(items)
    centre = find_structural_centres(items[:9])[0]
    assert offset + 8 not in [e["segment_index"] for e in centre.member_admissions]
    (proof,) = extension_hierarchy(items)["proofs"]
    last = proof["member_admissions"][-1]
    assert last == dict(
        segment_index=offset + 8,
        segment_confirmed_index=140,
        admitted_index=145,
        admission_segment_index=offset + 9,
        reason="failed_departure_return",
    )
    assert proof["known_index"] == last["admitted_index"]
    assert not proof["natural_type_complete"]
    assert items == before


def test_seed_and_extensions_have_distinct_admission_causes():
    items = segments([0, 10, 2, 8, 4, 7])
    admissions = find_structural_centres(items)[0].member_admissions
    assert [e["segment_index"] for e in admissions] == list(range(5))
    assert [e["admitted_index"] for e in admissions] == [110, 110, 110, 115, 120]
    assert [e["segment_confirmed_index"] for e in admissions] == [100, 105, 110, 115, 120]
    assert [e["reason"] for e in admissions] == ["seed_formation"] * 3 + ["extension"] * 2


def test_successful_departure_and_return_are_not_admitted_to_old_centre():
    items = segments([0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 9])
    centre = find_structural_centres(items)[0]
    assert centre.state == "exited"
    assert [e["segment_index"] for e in centre.member_admissions] == list(range(8))
    assert not extension_hierarchy(items)["proofs"]


def test_ledger_exactly_matches_slow_prefix_first_observation():
    rng = Random(210928)
    for _ in range(50):
        prices = [100]
        for i in range(35):
            prices.append(prices[-1] + (1 if i % 2 == 0 else -1) * rng.randint(1, 12))
        items = segments(prices)
        observed = {}
        for count in range(3, len(items) + 1):
            centres = find_structural_centres(items[:count])
            for centre in centres:
                for index in centre.member_segments:
                    observed.setdefault((centre.index, index), items[count - 1].confirmed_index)
                assert [e["segment_index"] for e in centre.member_admissions] == (
                    centre.member_segments
                )
                for entry in centre.member_admissions:
                    assert entry["admitted_index"] == observed[centre.index, entry["segment_index"]]
                    assert entry["admitted_index"] >= entry["segment_confirmed_index"]


def test_unknown_suffix_cannot_supply_return_admission():
    items = segments([0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 4])
    items[-1].confirmed_index = None
    assert not extension_hierarchy(items)["proofs"]
    assert len(find_structural_centres(items)[0].member_admissions) == 8


def test_api_preserves_two_dates_for_delayed_admission():
    from datetime import datetime, timedelta

    from easy_tdx.chanlun.analyser import ChanlunResult
    from easy_tdx.chanlun.types import Kline

    items = segments([0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 4])
    bars = [
        Kline(i, datetime(2026, 1, 1) + timedelta(minutes=i), 5, 5, 12, 0, 1) for i in range(146)
    ]
    result = ChanlunResult(frequency="5min", klines=bars, xds=items).to_dict()
    proof = result["extension_hierarchy"]["proofs"][0]
    row = proof["member_admissions"][-1]
    assert row["segment_confirmed_date"] == "2026-01-01 02:20"
    assert row["admitted_date"] == proof["known_date"] == "2026-01-01 02:25"
    assert not result["mmds"]
    assert not result["structure_metadata"]["recursive_levels_ready"]
