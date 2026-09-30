"""Fourth-level engineering recursion: exact dependencies, never natural closure.

This is a single engine snapshot built from confirmed segments and synthetic
chart/MACD data, not an HTTP-sized snapshot or raw-candle-to-segment validation.
"""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from easy_tdx.chanlun.anchors import extreme_index
from easy_tdx.chanlun.divergence_signals import segment_evidence
from easy_tdx.chanlun.layered_ownership import _frontier
from easy_tdx.chanlun.structure import confirmed_segment_prefix
from easy_tdx.chanlun.types import Kline
from tests.unit.test_chanlun_engineering_movements import CONSOLIDATION
from tests.unit.test_chanlun_nested_ownership import final_internal_snapshot, triple_fixture
from tests.unit.test_chanlun_structure import signal_fixture


def fourth_fixture(mirror=False, offset=0):
    """Lift every M3-fixture leg into a separately confirmed five-segment unit."""
    old, _, old_macd = triple_fixture()
    targets = [s.start.val for s in old] + [old[-1].end.val]
    prices, amplitudes = [-10000, 10000, -8000, 8000, -6000, 6000], [0.] * 6
    pattern = CONSOLIDATION[:-1]
    for i, (a, b) in enumerate(zip(targets, targets[1:])):
        prices.extend(a + (b-a) * (p-pattern[0]) / (pattern[-1]-pattern[0])
                      for p in pattern[:-1])
        amplitude = max(abs(old_macd['dif'][4*i+1]), .0000001)
        amplitudes.extend(amplitude * (1 if k == 0 else .5 if k == 4 else .3)
                          for k in range(5))
    prices += [targets[-1], targets[-1]-1]
    amplitudes.append(.000000001)
    if mirror:
        prices = [20000-p for p in prices]
    items, _, _ = signal_fixture(prices)
    for item in items:
        item.index += offset
    count = 101 + len(items)*5
    bars = [Kline(i, datetime(1990, 1, 1) + timedelta(days=i),
                  *[prices[min(i//4, len(prices)-1)]]*4, 0) for i in range(count)]
    values = [(1 if items[min(max(0, (i-1)//4), len(items)-1)].direction.value == 'up' else -1)
              * amplitudes[min(max(0, (i-1)//4), len(items)-1)] for i in range(count)]
    return items, bars, {'dif': values, 'dea': [v*.8 for v in values],
                         'hist': [v*.4 for v in values]}


def audit_dependencies(result, items, bars, macd):
    """Independent graph/source assertions, not just expected layer counts."""
    available = confirmed_segment_prefix(items, len(bars))
    base = {s.index: s for s in available}
    root = (f'owner:{available[0].index}:{available[-1].index}'
            f':at:{available[-1].confirmed_index}')
    records = {r['id']: r for level in result['levels'] for r in level['types']}
    assert len(records) == sum(len(level['types']) for level in result['levels'])
    owners = {owner['id']: owner for owner in result['nested_owners']}
    assert len(owners) == len(result['nested_owners'])
    owner_ids = {root, *owners}
    for owner in owners.values():
        assert owner['parent_owner_id'] in owner_ids
        sources = [i for identity in owner['source_unit_ids']
                   for i in records[identity]['source_segment_indices']]
        assert sources == owner['source_segment_indices']
        assert len(sources) == len(set(sources))
        assert all(records[identity]['level'] == owner['input_level']
                   for identity in owner['source_unit_ids'])
        assert owner['known_index'] < len(bars)
        parent = owners.get(owner['parent_owner_id'])
        if parent:
            assert owner['input_level'] > parent['input_level']
            assert set(sources) <= set(parent['source_segment_indices'])
            assert owner['known_index'] >= parent['known_index']
        for admission in owner['member_admissions']:
            assert (records[admission['unit_id']]['known_index']
                    <= admission['admitted_index'] < len(bars))
        assert not owner['natural_type_complete']
        assert not owner['eligible_for_external_recursion']
    for level in result['levels']:
        used = [i for r in level['types'] for i in r['source_segment_indices']]
        assert len(used) == len(set(used))
        for record in level['types']:
            sources = record['source_segment_indices']
            assert sources == list(range(sources[0], sources[-1]+1))
            assert record['start_index'] == extreme_index(base[sources[0]].start)
            assert record['end_index'] == extreme_index(base[sources[-1]].end)
            assert record['start_value'] == base[sources[0]].start.val
            assert record['end_value'] == base[sources[-1]].end.val
            assert record['low'] == min(base[i].low for i in sources)
            assert record['high'] == max(base[i].high for i in sources)
            assert (record['original_known_index'] <= record['known_index'] < len(bars))
            assert record['ownership_known_index'] <= record['known_index']
            assert record['known_index'] <= record['current_owner_known_index'] < len(bars)
            assert record['owner_id'] in owner_ids
            assert record['current_owner_id'] in owner_ids
            if record['current_owner_id'] in owners:
                assert set(sources) <= set(owners[record['current_owner_id']][
                    'source_segment_indices'])
            if record['level'] == 1:
                assert record['child_ids'] == [f'segment:{i}' for i in sources]
                witness = base[int(record['opposite_id'].split(':')[1])]
                assert witness.index not in sources
                assert witness.confirmed_index <= record['known_index']
            else:
                children = [records[identity] for identity in record['child_ids']]
                witness = records[record['opposite_id']]
                assert sources == [i for child in children for i in child['source_segment_indices']]
                assert not set(sources).intersection(witness['source_segment_indices'])
                for child in children + [witness]:
                    assert child['level'] + 1 == record['level']
                    assert child['known_index'] <= record['known_index']
                for child in children:
                    assert child['current_owner_known_index'] <= record['known_index']
                    assert child['current_owner_id'] == record['owner_id']
                # An unowned external witness is allowed, a foreign nested one isn't.
                assert witness['current_owner_id'] in (
                    record['owner_id'], owners[record['owner_id']]['parent_owner_id'])
            evidence = record['macd_evidence']
            assert segment_evidence(bars, macd, (evidence['a_start'], evidence['a_end']),
                                    (evidence['c_start'], evidence['c_end']),
                                    record['direction']) == evidence
            assert not record['eligible_for_external_recursion']
    frontier = _frontier(result['levels'])
    used = [i for identity in frontier for i in records[identity]['source_segment_indices']]
    assert len(used) == len(set(used))
    assert set(used) == {i for r in result['levels'][0]['types']
                         for i in r['source_segment_indices']}
    assert not result['natural_type_recursion_ready']


@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('offset', [0, 37])
def test_four_levels_keep_exact_price_sources_and_causal_dependencies(mirror, offset):
    items, bars, macd = fourth_fixture(mirror, offset)
    before = deepcopy((items, bars, macd))
    result = final_internal_snapshot(items, bars, macd)
    assert [len(level['types']) for level in result['levels']] == [437, 86, 16, 1]
    parent = result['levels'][3]['types'][0]
    assert parent['source_segment_indices'] == list(range(offset+1411, offset+2036))
    assert parent['known_index'] == 11055
    assert parent['direction'] == ('up' if mirror else 'down')
    assert [o['input_level'] for o in result['nested_owners']] == [1, 2, 3]
    audit_dependencies(result, items, bars, macd)
    assert (items, bars, macd) == before


@pytest.mark.parametrize('mirror', [False, True])
def test_m4_appears_only_after_its_complete_reverse_dependency_chain(mirror):
    items, bars, macd = fourth_fixture(mirror)
    for count, expected in ((11055, 3), (11056, 4)):
        result = final_internal_snapshot(items, bars[:count], macd)
        assert result['highest_completed_movement_level'] == expected
        audit_dependencies(result, items, bars[:count], macd)
    items[-1].confirmed_index = None
    assert final_internal_snapshot(items, bars, macd)['highest_completed_movement_level'] == 3


def test_missing_macd_never_creates_higher_completion():
    items, bars, _ = fourth_fixture()
    result = final_internal_snapshot(items, bars, {})
    assert not result['levels']
    assert not result['natural_type_recursion_ready']


@pytest.fixture(scope='module')
def fourth_snapshot():
    items, bars, macd = fourth_fixture()
    return final_internal_snapshot(items, bars, macd), items, bars, macd


@pytest.mark.parametrize('fault', ['future', 'early_parent', 'source', 'missing_child',
                                  'self_witness', 'unknown_owner', 'orphan_owner',
                                  'macd', 'natural_flag'])
def test_dependency_audit_rejects_corrupted_deep_snapshots(fourth_snapshot, fault):
    original, items, bars, macd = fourth_snapshot
    damaged = deepcopy(original)
    top = damaged['levels'][3]['types'][0]
    if fault == 'future':
        top['known_index'] = len(bars)
    elif fault == 'early_parent':
        top['known_index'] -= 1
    elif fault == 'source':
        top['source_segment_indices'].pop()
    elif fault == 'missing_child':
        top['child_ids'][0] = 'missing-child'
    elif fault == 'self_witness':
        top['opposite_id'] = top['id']
    elif fault == 'unknown_owner':
        top['current_owner_id'] = 'unknown-owner'
    elif fault == 'orphan_owner':
        damaged['nested_owners'][2]['parent_owner_id'] = 'missing-parent'
    elif fault == 'macd':
        top['macd_evidence']['area_ratio'] += .1
    else:
        damaged['natural_type_recursion_ready'] = True
    with pytest.raises((AssertionError, KeyError)):
        audit_dependencies(damaged, items, bars, macd)
    # The deliberately corrupted copy must not poison later verification.
    audit_dependencies(original, items, bars, macd)
