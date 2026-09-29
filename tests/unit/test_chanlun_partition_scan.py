"""Rolling search matches independent batch snapshots without live-state leaks."""
from copy import deepcopy
from importlib import import_module
from random import Random

import pytest

from easy_tdx.chanlun.anchors import extreme_index
from easy_tdx.chanlun.expansion_regrouping import (
    _component_prefixes,
    _partition,
    expansion_regrouping,
)
from easy_tdx.chanlun.structure import find_structural_centres
from tests.unit.test_chanlun_anchors import attach_extreme, bars_for
from tests.unit.test_chanlun_expansion_regrouping import LATER_VALID_PRICES, PRICES
from tests.unit.test_chanlun_extension_recursion import oscillation
from tests.unit.test_chanlun_structure import segments


def batch_component(chunk):
    """Original independent whole-slice definition, with all public fields."""
    first, last = chunk[0], chunk[-1]
    if first.start.val == last.end.val:
        return None
    direction = 'up' if first.start.val < last.end.val else 'down'
    if first.direction.value != direction or last.direction.value != direction:
        return None
    centres = find_structural_centres(chunk)
    if len(centres) != 1 or len(centres[0].member_segments) >= 9:
        return None
    centre = centres[0]
    return {
        'seed_segment_indices': list(centre.seed_segments),
        'start_index': extreme_index(first.start), 'end_index': extreme_index(last.end),
        'start_value': first.start.val, 'end_value': last.end.val, 'direction': direction,
        'known_index': last.confirmed_index,
        'low': min(item.low for item in chunk), 'high': max(item.high for item in chunk),
        'zd': centre.zd, 'zg': centre.zg, 'natural_type_complete': False,
    }


@pytest.mark.parametrize('sign', [1, -1])
@pytest.mark.parametrize('offset', [0, 17])
def test_all_component_fields_match_independent_batch_slices(sign, offset):
    rng = Random(2802)
    samples = [PRICES, LATER_VALID_PRICES, [10, 12, 8, 10, 7, 9],
               [0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 4]]
    for _ in range(10):
        prices = [100]
        for i in range(20):
            prices.append(prices[-1] + (1 if i % 2 == 0 else -1) * rng.randint(1, 20))
        samples.append(prices)
    for sample, prices in enumerate(samples):
        items = segments([sign * price for price in prices])
        for item in items:
            item.index += offset
        if sample % 2:
            bars = bars_for(items)
            for point in [s.start for s in items] + [items[-1].end]:
                attach_extreme(point, bars)
        before = deepcopy(items)
        for start in range(len(items)):
            summaries = _component_prefixes(items, start)
            for stop in range(start + 1, len(items) + 1):
                assert summaries.get(stop) == batch_component(items[start:stop])
        assert items == before


@pytest.mark.parametrize('prices', [
    [0, 10, 2, 8, 2, 8, 2, 8, 2, 8],  # Ninth admission disqualifies future ranges.
    [0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 4],  # Ninth waits for failed return.
    [14, 10, 12, 8, 20, 16, 22, 18],  # Second centre disqualifies future ranges.
])
def test_later_disqualification_cannot_erase_earlier_snapshots(prices):
    items = segments(prices)
    final = _component_prefixes(items, 0)
    assert final
    for count in range(1, len(items) + 1):
        assert _component_prefixes(items[:count], 0) == {
            stop: summary for stop, summary in final.items() if stop <= count}
    assert len(items) not in final


def test_each_needed_start_is_walked_once_without_rebuilding_batch_centres(monkeypatch):
    module = import_module('easy_tdx.chanlun.expansion_regrouping')
    original = module.iter_structural_steps
    walks, visits = [], []

    def counted(chunk):
        walks.append(chunk[0].index)
        for step in original(chunk):
            visits.append(step[0].index)
            yield step

    def forbidden(_):
        pytest.fail('Candidate search must not rebuild whole-slice centres')

    monkeypatch.setattr(module, 'iter_structural_steps', counted)
    monkeypatch.setattr(module, 'find_structural_centres', forbidden)
    items = segments(LATER_VALID_PRICES)
    _partition(items)
    assert walks
    assert len(walks) == len(set(walks))
    assert len(visits) <= len(items) * (len(items) + 1) // 2


@pytest.mark.parametrize('prices', [PRICES[:12], LATER_VALID_PRICES[15:27]])
def test_short_windows_do_not_precompute_unused_suffixes(monkeypatch, prices):
    module = import_module('easy_tdx.chanlun.expansion_regrouping')

    def forbidden(*_):
        pytest.fail('Short searches should retain their lightweight slice path')

    monkeypatch.setattr(module, '_component_prefixes', forbidden)
    assert _partition(segments(prices))


@pytest.mark.parametrize('fault', ['missing', 'raw_anchor', 'confirmation', 'direction'])
def test_regrouping_validates_whole_source_before_search_without_suffix_bridging(fault):
    items = segments(PRICES)[:11]
    assert _partition(items)
    if fault == 'missing':
        items[5].index += 1
    elif fault == 'raw_anchor':
        items[5].start = deepcopy(items[5].start)
        items[5].start.k.k_index += 1
    elif fault == 'confirmation':
        items[5].confirmed_index = None
    else:
        items[5].direction = items[4].direction
    actual = expansion_regrouping(items)
    expected = expansion_regrouping(items[:5])
    assert actual['accepted_segment_count'] == 5
    assert actual['rejected_suffix_count'] == 6
    assert actual['candidates'] == expected['candidates']
    assert actual['completion_audits'] == expected['completion_audits']


def test_cache_does_not_survive_a_call_or_mutate_prior_selected_partition():
    items = segments(PRICES)[:11]
    first = _partition(items)
    expected = deepcopy(first)
    first[0]['seed_segment_indices'].clear()
    assert _partition(items) == expected
    original = deepcopy(expected)
    _partition(segments(LATER_VALID_PRICES)[15:26])
    assert expected == original


def test_early_extension_stop_preserves_shorter_components():
    items = oscillation(81)
    summaries = _component_prefixes(items, 0)
    assert summaries == {stop: batch_component(items[:stop]) for stop in (3, 5, 7)}
    assert not _partition(items)
