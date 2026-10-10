"""Mixed engineering recursion retains causal evidence and disjoint sources."""

from copy import deepcopy
from datetime import datetime, timedelta
from importlib import import_module

import pytest

from easy_tdx.chanlun.engineering_consolidations import (
    conflict_member_times,
    consolidation_candidates,
)
from easy_tdx.chanlun.engineering_trends import engineering_movement_hierarchy
from easy_tdx.chanlun.types import Kline
from tests.unit.test_chanlun_engineering_trends import PRICES
from tests.unit.test_chanlun_signal_levels import fixture
from tests.unit.test_chanlun_structure import signal_fixture

CONSOLIDATION = [40, 30, 38, 32, 37, 20, 28]


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("offset", [0, 37])
def test_real_consolidation_has_separate_entry_centre_exit_and_confirmation(mirror, offset):
    items, bars, macd = fixture(CONSOLIDATION, 0, 4, mirror)
    for item in items:
        item.index += offset
    before = deepcopy((items, bars, macd))
    result = engineering_movement_hierarchy(items, bars, macd)
    record = result["levels"][0]["types"][0]
    assert record["kind"] == "consolidation"
    assert record["source_segment_indices"] == list(range(offset, offset + 5))
    assert record["centres"][0]["source_unit_indices"] == list(range(offset + 1, offset + 4))
    assert record["a_unit_index"] == offset and record["c_unit_index"] == offset + 4
    assert record["opposite_id"] == f"segment:{offset + 5}"
    assert record["known_index"] == items[5].confirmed_index
    assert record["direction"] == ("up" if mirror else "down")
    assert record["eligible_for_movement_recursion"]
    assert not result["natural_type_recursion_ready"]
    assert result["remaining_input_ids"] == [record["id"]]
    assert (items, bars, macd) == before
    for count in range(len(bars) + 1):
        now = engineering_movement_hierarchy(items, bars[:count], macd)
        assert [t for lev in now["levels"] for t in lev["types"]] == (
            [record] if count > record["known_index"] else []
        )


@pytest.mark.parametrize("fault", ["area", "dea", "missing", "reverse", "suffix", "new_low"])
def test_each_consolidation_gate_can_block_completion(fault):
    items, bars, macd = fixture(CONSOLIDATION, 0, 4)
    if fault == "area":
        macd["hist"] = [-2.0] * len(bars)
    elif fault == "dea":
        macd["dea"] = [-2.0] * len(bars)
    elif fault == "missing":
        macd = {}
    elif fault == "reverse":
        items[-1].confirmed_index = None
    elif fault == "suffix":
        items[3].index += 10
    else:
        # Keep valid geometry, but C no longer breaks the A low.
        items, bars, _ = signal_fixture([40, 30, 38, 32, 37, 31, 38])
    assert not engineering_movement_hierarchy(items, bars, macd)["levels"]


def mixed_fixture(mirror=False):
    """Five alternating children with both kinds form a higher consolidation.

    Strong initial entry avoids same-level expansion across child boundaries.
    The final upward child confirms the higher C; an extra unit confirms it.
    """
    targets = [100, 60, 90, 70, 85, 20, 150]
    prices = []
    widths = []
    for i, (a, b) in enumerate(zip(targets, targets[1:])):
        pattern = CONSOLIDATION[:-1] if i % 2 == 0 else PRICES[:-1]
        widths.append(len(pattern) - 1)
        prices.extend(
            a + (b - a) * (p - pattern[0]) / (pattern[-1] - pattern[0]) for p in pattern[:-1]
        )
    prices += [targets[-1], targets[-1] - 1]
    if mirror:
        prices = [200 - p for p in prices]
    items, _, _ = signal_fixture(prices)
    count = 101 + 5 * len(items)
    bars = [
        Kline(
            i,
            datetime(2026, 1, 1) + timedelta(days=i),
            prices[min(i // 4, len(prices) - 1)],
            prices[min(i // 4, len(prices) - 1)],
            prices[min(i // 4, len(prices) - 1)],
            prices[min(i // 4, len(prices) - 1)],
            0,
        )
        for i in range(count)
    ]
    amplitudes = []
    for child, width in enumerate(widths):
        # Trend children must NOT first qualify as a shorter consolidation:
        # their initial A is weak, middle entry strong, final C weaker.
        amplitudes.extend(
            (10 * 0.4**child)
            * (
                (0.1 if unit == 0 else 1 if unit == 4 else 0.5 if unit == 8 else 0.3)
                if width == 9
                else (1 if unit == 0 else 0.5 if unit == 4 else 0.3)
            )
            for unit in range(width)
        )
    amplitudes.append(0.001)
    values = [
        (1 if items[min(max(0, (i - 1) // 4), len(items) - 1)].direction.value == "up" else -1)
        * amplitudes[min(max(0, (i - 1) // 4), len(items) - 1)]
        for i in range(count)
    ]
    macd = {"dif": values, "dea": [v * 0.8 for v in values], "hist": [v * 0.4 for v in values]}
    return items, bars, macd, widths


@pytest.mark.parametrize("mirror", [False, True])
def test_real_mixed_children_recurse_with_exact_provenance(mirror):
    items, bars, macd, widths = mixed_fixture(mirror)
    result = engineering_movement_hierarchy(items, bars, macd)
    assert result["highest_completed_movement_level"] >= 2
    lower, higher = result["levels"][:2]
    top = higher["types"][0]
    lookup = {t["id"]: t for t in lower["types"]}
    children = [lookup[i] for i in top["child_ids"]]
    assert {t["kind"] for t in children} == {"trend", "consolidation"}
    assert top["source_segment_indices"] == list(range(sum(widths[:5])))
    assert top["source_segment_indices"] == [
        i for t in children for i in t["source_segment_indices"]
    ]
    assert top["known_index"] == lookup[top["opposite_id"]]["known_index"]
    assert 0 < top["macd_evidence"]["area_ratio"] < 1
    assert result["structure_layers"][0]["scope"] == "centres_on_completed_engineering_movements"
    full = [t for level in result["levels"] for t in level["types"]]
    for known in sorted({s.confirmed_index for s in items}):
        for count in (known, known + 1):
            prefix = engineering_movement_hierarchy(items, bars[:count], macd)
            assert [t for level in prefix["levels"] for t in level["types"]] == [
                t for t in full if t["known_index"] < count
            ]
    for level in result["levels"]:
        covered = [i for t in level["types"] for i in t["source_segment_indices"]]
        assert len(covered) == len(set(covered))


def test_mixed_api_dates_isolation_old_interpretation_and_signals():
    from easy_tdx.chanlun.analyser import ChanlunResult
    from easy_tdx.chanlun.engineering_trends import engineering_trend_hierarchy

    items, bars, macd, _ = mixed_fixture()
    result = ChanlunResult(xds=items, klines=bars, macd=macd)
    payload = result.to_dict()
    mixed = payload["engineering_movement_hierarchy"]
    top = mixed["levels"][1]["types"][0]
    assert top["known_date"] == result._fmt_dt(bars[top["known_index"]].date)
    centre = mixed["structure_layers"][0]["chains"][0]["centres"][0]
    assert centre["formed_date"] == result._fmt_dt(bars[centre["formed_index"]].date)
    assert centre["id"].startswith("recursive-centre:M1:")
    assert not payload["mmds"] and not payload["bcs"]
    assert payload["structure_metadata"]["engineering_movement_recursion_ready"]
    assert not payload["structure_metadata"]["recursive_levels_ready"]
    old = engineering_trend_hierarchy(items, bars, macd)
    assert payload["engineering_trend_hierarchy"]["rule"] == old["rule"]
    assert (
        payload["engineering_trend_hierarchy"]["highest_completed_trend_level"]
        == old["highest_completed_trend_level"]
    )
    top["child_ids"].clear()
    assert result.to_dict()["engineering_movement_hierarchy"]["levels"][1]["types"][0]["child_ids"]


def test_confirmation_batch_empty_input_and_real_price_reversal_without_macd_is_insufficient():
    items, bars, macd = fixture(CONSOLIDATION, 0, 4)
    for item in items:
        item.confirmed_index = 180
    assert not engineering_movement_hierarchy(items, bars[:180], macd)["levels"]
    record = engineering_movement_hierarchy(items, bars[:181], macd)["levels"][0]["types"][0]
    assert record["known_index"] == record["divergence_known_index"] == 180
    assert not engineering_movement_hierarchy([], [], {})["levels"]
    assert not engineering_movement_hierarchy(items, bars, {})["levels"]


def test_random_prefixes_do_not_rewrite_published_mixed_types(monkeypatch):
    from random import Random

    # Isolate structure/ownership; other tests use the real MACD comparator.
    for name in ("engineering_consolidations", "engineering_trends"):
        monkeypatch.setattr(
            import_module("easy_tdx.chanlun." + name),
            "segment_evidence",
            lambda *args: {"area_ratio": 0.5},
        )
    rng = Random(43)
    for _ in range(20):
        prices = [100.0]
        for i in range(18):
            prices.append(prices[-1] + (1 if i % 2 else -1) * rng.uniform(1, 20))
        items, bars, macd = signal_fixture(prices)
        full = engineering_movement_hierarchy(items, bars, macd)
        records = [t for level in full["levels"] for t in level["types"]]
        for length in range(len(items) + 1):
            now = engineering_movement_hierarchy(items[:length], bars, macd)
            known = items[length - 1].confirmed_index if length else -1
            assert [t for level in now["levels"] for t in level["types"]] == [
                t for t in records if t["known_index"] <= known
            ]


def test_expansion_conflict_times_are_causal_and_local_restarts_cannot_bypass(monkeypatch):
    prices = [40, 30, 38, 32, 37, 20, 29, 22, 28, 18, 35, 25, 34, 20, 32, 15, 30]
    items, bars, macd = signal_fixture(prices)
    for name in ("engineering_consolidations", "engineering_trends"):
        monkeypatch.setattr(
            import_module("easy_tdx.chanlun." + name),
            "segment_evidence",
            lambda *args: {"area_ratio": 0.5},
        )
    protected = conflict_member_times(items)
    assert protected
    raw = consolidation_candidates(items, bars, macd)
    blocked = [
        c
        for c in raw
        if any(
            known <= c["known_index"] and c["start_unit_index"] <= i <= c["end_unit_index"]
            for i, known in protected.items()
        )
    ]
    assert blocked
    result = engineering_movement_hierarchy(items, bars, macd)
    for level in result["levels"][:1]:
        for record in level["types"]:
            assert not any(
                protected.get(i, float("inf")) <= record["known_index"]
                for i in record["source_segment_indices"]
            )
    for count in range(len(items) + 1):
        now = conflict_member_times(items[:count])
        known = items[count - 1].confirmed_index if count else -1
        assert now == {i: t for i, t in protected.items() if t <= known}


def test_later_promotion_keeps_prior_completion_but_same_batch_blocks(monkeypatch):
    module = import_module("easy_tdx.chanlun.engineering_consolidations")
    monkeypatch.setattr(module, "segment_evidence", lambda *args: {"area_ratio": 0.5})
    items, bars, macd = signal_fixture(CONSOLIDATION[:-1] + [36, 25, 36, 25, 36, 25, 36, 25])
    early = engineering_movement_hierarchy(items[:6], bars, macd)
    assert early["levels"]
    later = engineering_movement_hierarchy(items, bars, macd)
    assert later["levels"][0]["types"][0] == early["levels"][0]["types"][0]
    for item in items:
        item.confirmed_index = 190
    assert not engineering_movement_hierarchy(items, bars, macd)["levels"]
