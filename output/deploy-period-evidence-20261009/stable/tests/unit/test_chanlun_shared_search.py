"""Shared cursors preserve every v3 choice, history boundary and owned snapshot."""

from copy import deepcopy
from importlib import import_module
from random import Random

import pytest

from easy_tdx.chanlun.expansion_regrouping import _research_partition
from easy_tdx.chanlun.partition_search import ResearchPartitionSearch
from easy_tdx.chanlun.regrouping_versions import regrouping_versions
from tests.unit.test_chanlun_expansion_regrouping import LATER_VALID_PRICES, PRICES
from tests.unit.test_chanlun_extension_recursion import oscillation
from tests.unit.test_chanlun_regrouping_starts import PRICES as MOVED
from tests.unit.test_chanlun_structure import segments
from tests.unit.test_chanlun_trend_components import INTEGRATION, PARTITION, TREND


class SliceSearch:
    """Previous independent slice algorithm, without shared cursors or cut cache."""

    def __init__(self, items):
        self.items = items

    def partition(self, start, stop):
        return _research_partition(self.items[start:stop])


@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("offset", [0, 29])
def test_all_intervals_in_shuffled_order_match_slice_search(sign, offset):
    rng = Random(3802)
    samples = [PRICES, LATER_VALID_PRICES, MOVED, INTEGRATION, PARTITION, TREND]
    for _ in range(5):
        prices = [100]
        for i in range(24):
            prices.append(prices[-1] + (1 if i % 2 == 0 else -1) * rng.randint(1, 20))
        samples.append(prices)
    for prices in samples:
        items = segments([sign * p for p in prices])
        for item in items:
            item.index += offset
        before = deepcopy(items)
        search = ResearchPartitionSearch(items)
        windows = [(a, b) for a in range(len(items)) for b in range(a, len(items) + 1)]
        rng.shuffle(windows)
        for start, stop in windows:
            assert search.partition(start, stop) == _research_partition(items[start:stop])
        assert items == before


@pytest.mark.parametrize("prices", [PRICES, MOVED, INTEGRATION])
def test_full_versions_match_uncached_engine_at_every_confirmation(monkeypatch, prices):
    module = import_module("easy_tdx.chanlun.regrouping_versions")
    items = segments(prices)
    counts = sorted(
        {0, *(s.confirmed_index for s in items), *(s.confirmed_index + 1 for s in items)}
    )
    actual = [regrouping_versions(items, count) for count in counts]
    monkeypatch.setattr(module, "ResearchPartitionSearch", SliceSearch)
    assert actual == [regrouping_versions(items, count) for count in counts]


def test_lifecycle_steps_are_not_revisited_or_read_beyond_requested_stop(monkeypatch):
    module = import_module("easy_tdx.chanlun.expansion_regrouping")
    original = module.iter_structural_steps
    walks = []

    def counted(items):
        visits = []
        walks.append(visits)
        for step in original(items):
            visits.append(step[0].index)
            yield step

    monkeypatch.setattr(module, "iter_structural_steps", counted)
    items = segments(PARTITION)
    search = ResearchPartitionSearch(items)
    for stop in range(9, len(items) + 1):
        search.partition(0, stop)
        assert all(index < stop for walk in walks for index in walk)
    assert walks and all(walk for walk in walks)
    assert len({walk[0] for walk in walks}) == len(walks)
    assert all(walk == list(range(walk[0], walk[-1] + 1)) for walk in walks)
    before = deepcopy(walks)
    for stop in reversed(range(9, len(items) + 1)):
        search.partition(0, stop)
    assert walks == before


@pytest.mark.parametrize(
    "prices",
    [
        TREND[:10] + [5, 9, 4],
        [0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 4, 15, 8, 20],
    ],
)
def test_later_rejection_does_not_remove_previous_shorter_answers(prices):
    items = segments(prices)
    search = ResearchPartitionSearch(items)
    # Force long-window probes first, then request the old snapshots again.
    for stop in reversed(range(len(items) + 1)):
        assert search.partition(0, stop) == _research_partition(items[:stop])


def test_returned_results_cannot_mutate_cached_plans_or_other_analyses():
    items = segments(PARTITION)
    search = ResearchPartitionSearch(items)
    result = search.partition(0, len(items))
    expected = deepcopy(result)
    assert result and result[0]["component_kind"] == "trend_candidate"
    result[0]["centre_chain"][0]["seed_segment_indices"].clear()
    result[0]["seed_segment_indices"].clear()
    result[0]["source_segment_indices"].append(999)
    result[0]["low"] = -999
    assert search.partition(0, len(items)) == expected
    mirror = segments([-p for p in PARTITION])
    assert ResearchPartitionSearch(mirror).partition(0, len(mirror)) == _research_partition(mirror)
    assert ResearchPartitionSearch(items).partition(0, len(items)) == expected


@pytest.mark.parametrize("fault", ["gap", "unconfirmed", "raw_future"])
def test_shared_engine_only_receives_the_validated_prefix(fault):
    items = segments(INTEGRATION)
    expected = regrouping_versions(items[:20])
    if fault == "gap":
        items[20].index += 1
    elif fault == "unconfirmed":
        items[20].confirmed_index = None
    else:
        items[20].end = deepcopy(items[20].end)
        items[20].end.k.k_index = 9999
    result = regrouping_versions(items)
    assert result["cases"] == expected["cases"]
    assert result["accepted_segment_count"] == 20


def test_same_confirmation_batch_and_upgrade_priority_match_slice_engine(monkeypatch):
    module = import_module("easy_tdx.chanlun.regrouping_versions")
    items = oscillation(81)
    other = segments(INTEGRATION)
    for item in other:
        item.confirmed_index = 300
    actual = [regrouping_versions(items), regrouping_versions(other)]
    monkeypatch.setattr(module, "ResearchPartitionSearch", SliceSearch)
    assert actual == [regrouping_versions(items), regrouping_versions(other)]


def test_empty_short_and_out_of_bounds_windows():
    search = ResearchPartitionSearch([])
    assert search.partition(0, 0) is None
    for start, stop in [(-1, 0), (0, 1), (1, 0)]:
        with pytest.raises(ValueError):
            search.partition(start, stop)
    search = ResearchPartitionSearch(segments(TREND))
    assert search.partition(3, 3) is None
    assert search.partition(3, 5) is None
