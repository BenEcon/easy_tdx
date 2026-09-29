"""Raw anchors must not contradict a superficially connected merged chain."""
from copy import deepcopy

import pytest

from easy_tdx.chanlun.decomposition import decompose_base_chain
from easy_tdx.chanlun.expansion_regrouping import expansion_regrouping
from easy_tdx.chanlun.extension_recursion import extension_hierarchy
from easy_tdx.chanlun.structure import confirmed_segment_prefix, find_structural_centres
from easy_tdx.chanlun.structure_signals import structure_signals
from easy_tdx.chanlun.types import Kline
from tests.unit.test_chanlun_anchors import attach_extreme, bars_for
from tests.unit.test_chanlun_expansion_regrouping import LATER_VALID_PRICES
from tests.unit.test_chanlun_extension_recursion import oscillation
from tests.unit.test_chanlun_structure import segments, signal_fixture


def raw_anchor(point, index):
    point.k.klines = [Kline(index, point.k.date, point.val, point.val,
                           point.val, point.val, 0)]


@pytest.mark.parametrize('fault', ['future', 'negative', 'fractional', 'boolean',
                                  'backwards', 'overlapping_merged_ranges'])
@pytest.mark.parametrize('sign', [1, -1])
def test_bad_ninth_endpoint_cannot_manufacture_an_upgrade(fault, sign):
    base = oscillation(9)
    items = segments([sign * item.start.val for item in base] + [sign * base[-1].end.val])
    for item in items:
        item.index += 17
    last = items[-1]
    if fault == 'backwards':
        last.end.k.k_index = last.start.k.k_index - 1
    elif fault == 'overlapping_merged_ranges':
        raw_anchor(last.end, last.start.k.k_index)
    else:
        raw_anchor(last.end, {'future': 999, 'negative': -1,
                              'fractional': 35.5, 'boolean': True}[fault])
    before = deepcopy(items)
    assert confirmed_segment_prefix(items, 150) == items[:8]
    for fn in (decompose_base_chain, extension_hierarchy, expansion_regrouping):
        result = fn(items, 150)
        expected = fn(items[:8], 150)
        assert result['accepted_segment_count'] == 8
        assert result['rejected_suffix_count'] == 1
        for key, value in expected.items():
            if key not in ('input_segment_count', 'rejected_suffix_count'):
                assert result[key] == value
    assert not extension_hierarchy(items)['proofs']
    assert items == before


@pytest.mark.parametrize('fault', ['tail_identity', 'extreme_identity'])
def test_shared_endpoint_must_agree_on_raw_position_not_object_identity(fault):
    items = oscillation(12)
    for item in items:
        attach_extreme(item.start, bars_for(items))
    original = deepcopy(items)
    items[9].start = deepcopy(items[9].start)
    # Separate objects with equal raw locations are valid.
    assert confirmed_segment_prefix(items) == items
    if fault == 'tail_identity':
        items[9].start.k.k_index += 1
    else:
        raw_anchor(items[9].start, items[9].start.k.k_index)
    assert confirmed_segment_prefix(items) == items[:9]
    assert extension_hierarchy(items)['proofs'] == extension_hierarchy(original[:9])['proofs']


@pytest.mark.parametrize('field', ['index', 'k_index'])
@pytest.mark.parametrize('value', [None, -1, True, 1.5])
def test_invalid_merged_indices_stop_without_exception(field, value):
    items = oscillation(9)
    setattr(items[8].end.k, field, value)
    assert confirmed_segment_prefix(items) == items[:8]


@pytest.mark.parametrize('sign', [1, -1])
def test_bad_shared_anchor_preserves_earlier_signals(sign):
    prices = [sign * p for p in [30, 40, 32, 38, 20, 26, 22, 25, 18, 28, 26]]
    items, bars, macd = signal_fixture(prices)
    expected = structure_signals(items[:8], bars, macd)
    items[8].start = deepcopy(items[8].start)
    items[8].start.k.k_index += 1
    assert structure_signals(items, bars, macd) == expected
    assert find_structural_centres(items) == find_structural_centres(items[:8])


def test_bad_suffix_preserves_mature_cross_centre_candidate():
    items = segments(LATER_VALID_PRICES)
    expected = expansion_regrouping(items[:-1])
    assert any(event['parts'] for event in expected['candidates'])
    raw_anchor(items[-1].end, 999)
    actual = expansion_regrouping(items)
    assert actual['candidates'] == expected['candidates']
    assert actual['completion_audits'] == expected['completion_audits']
    assert actual['rejected_suffix_count'] == 1


def test_real_extreme_before_merged_tail_and_replay_boundary_remain_valid():
    items = oscillation(27)
    bars = bars_for(items)
    for point in [item.start for item in items] + [items[-1].end]:
        attach_extreme(point, bars)
    original = deepcopy(items)
    result = extension_hierarchy(items)
    assert result['highest_proven_level'] == 3
    for proof in result['proofs']:
        assert proof['end_index'] < proof['known_index']
        before = extension_hierarchy(items, proof['known_index'])['proofs']
        at = extension_hierarchy(items, proof['known_index'] + 1)['proofs']
        assert proof not in before
        assert proof in at
    assert items == original
