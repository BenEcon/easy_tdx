"""Deep recursion must not read an unobservable indicator or segment suffix.

Synthetic confirmed-segment inputs exercise the actual geometry/MACD engine;
these are causal regression checks, not real-market or natural-closure claims.
"""
from copy import deepcopy
from dataclasses import replace
from random import Random

import pytest

from easy_tdx.chanlun.engineering_trends import engineering_movement_hierarchy
from easy_tdx.chanlun.layered_ownership import layered_movement_ownership
from easy_tdx.chanlun.ownership_history import summarize_ownership_history
from tests.unit.test_chanlun_deep_dependencies import audit_dependencies, fourth_fixture
from tests.unit.test_chanlun_nested_ownership import (
    final_internal_snapshot,
    nested_fixture,
    triple_fixture,
)


class ObservableValues(list):
    """Keep the real full length but fail on any access beyond the replay cut."""

    def __init__(self, values, count):
        super().__init__(values)
        self.count = count

    def __getitem__(self, key):
        indices = range(*key.indices(len(self))) if isinstance(key, slice) else (
            key if key >= 0 else len(self) + key,)
        assert all(0 <= index < self.count for index in indices), 'future MACD read'
        return super().__getitem__(key)

    def __iter__(self):
        for index in range(len(self)):
            yield self[index]


@pytest.mark.parametrize('depth', [3, 4])
@pytest.mark.parametrize('mirror', [False, True])
def test_deep_confirmation_prefix_never_reads_future_indicators_or_segments(depth, mirror):
    items, bars, macd = (triple_fixture if depth == 3 else fourth_fixture)(mirror)
    confirmation = 2280 if depth == 3 else 11055
    for count in (confirmation, confirmation + 1):
        expected = final_internal_snapshot(items, bars[:count], macd)
        assert expected['highest_completed_movement_level'] == depth - (count == confirmation)
        guarded = {key: ObservableValues(values, count) for key, values in macd.items()}
        assert final_internal_snapshot(items, bars[:count], guarded) == expected
        poisoned = {key: values[:count] + [float('nan')] * (len(values) - count)
                    for key, values in macd.items()}
        assert final_internal_snapshot(items, bars[:count], poisoned) == expected
        changed = deepcopy(items)
        for item in changed:
            if item.confirmed_index >= count:
                item.confirmed_index += 10000
                item.low = -1e12
                item.high = 1e12
        assert final_internal_snapshot(changed, bars[:count], guarded) == expected
        audit_dependencies(expected, items, bars[:count], macd)


@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('seed', [55, 550])
def test_irregular_confirmation_times_keep_causal_m3_dependencies(mirror, seed):
    items, bars, macd = triple_fixture(mirror)
    rng = Random(seed)
    previous = 0
    for item in items:
        item.confirmed_index = max(previous, item.confirmed_index - rng.randrange(5))
        previous = item.confirmed_index
    result = final_internal_snapshot(items, bars, macd)
    assert result['highest_completed_movement_level'] == 3
    audit_dependencies(result, items, bars, macd)
    confirmation = result['levels'][2]['types'][0]['known_index']
    before = final_internal_snapshot(items, bars[:confirmation], macd)
    assert before['highest_completed_movement_level'] == 2
    audit_dependencies(before, items, bars[:confirmation], macd)


@pytest.mark.parametrize('history', ['full', 'summary'])
@pytest.mark.parametrize('mirror', [False, True])
def test_actual_owner_history_and_cache_are_independent_of_future_suffix(history, mirror):
    items, bars, macd = nested_fixture(mirror, offset=37)
    count = 501  # Before the final M2 confirmation, after several expansions.
    visible = bars[:count]
    flat = engineering_movement_hierarchy(items, visible, macd)
    expected = layered_movement_ownership(items, visible, macd, flat, nested=True)
    if history == 'summary':
        expected = summarize_ownership_history(expected)
    guarded = {key: ObservableValues(values, count) for key, values in macd.items()}
    assert layered_movement_ownership(items, visible, guarded, flat, nested=True,
                                      ownership_history=history) == expected
    # Loading new prices after the cut cannot alter the earlier full snapshots.
    altered_bars = visible + [replace(bar, low=-1e12, high=1e12) for bar in bars[count:]]
    altered_macd = {key: values[:count] + [0.] * (len(values) - count)
                    for key, values in macd.items()}
    changed_flat = engineering_movement_hierarchy(items, altered_bars, altered_macd)
    later = layered_movement_ownership(items, altered_bars, altered_macd, changed_flat,
                                       nested=True, ownership_history=history)
    field = 'history_summaries' if history == 'summary' else 'versions'
    earlier = [version for version in later[field] if version['known_index'] < count]
    assert earlier == expected[field]


def test_future_read_guard_catches_scalar_slice_negative_index_and_iteration():
    values = ObservableValues([1., 2., 3., 4.], 2)
    assert values[:2] == [1., 2.]
    for read in (lambda: values[2], lambda: values[-1],
                 lambda: values[1:3], lambda: list(values)):
        with pytest.raises(AssertionError, match='future MACD read'):
            read()
