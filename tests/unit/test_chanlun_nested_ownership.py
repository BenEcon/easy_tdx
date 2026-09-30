"""A promoted/expanding M layer can retain its internal completed next layer."""
import json
from copy import deepcopy
from datetime import datetime, timedelta
from importlib import import_module

import pytest

from easy_tdx.chanlun.engineering_trends import _chains, engineering_movement_hierarchy
from easy_tdx.chanlun.layered_ownership import layered_movement_ownership
from easy_tdx.chanlun.nested_recursion import nested_candidates
from easy_tdx.chanlun.types import Kline
from tests.unit.test_chanlun_engineering_movements import CONSOLIDATION
from tests.unit.test_chanlun_layered_ownership import PRICES, current
from tests.unit.test_chanlun_signal_levels import fixture
from tests.unit.test_chanlun_structure import signal_fixture


def nested_fixture(mirror=False, offset=0):
    """Lift the real blocked 10..14 base example into sixteen completed M1s."""
    prices = [-200, 300, -100, 250, -50]
    pattern = CONSOLIDATION[:-1]
    for a, b in zip(PRICES, PRICES[1:]):
        prices.extend(a + (b-a) * (p-pattern[0]) / (pattern[-1]-pattern[0])
                      for p in pattern[:-1])
    prices += [PRICES[-1], PRICES[-1]-1]
    if mirror:
        prices = [400-p for p in prices]
    items, _, _ = signal_fixture(prices)
    for item in items:
        item.index += offset
    count = 101 + len(items)*5
    bars = [Kline(i, datetime(2026, 1, 1)+timedelta(days=i),
                  *[prices[min(i//4, len(prices)-1)]]*4, 0) for i in range(count)]
    amplitudes = [0.] * 5
    for child in range(len(PRICES)-1):
        amplitude = 10 if child == 10 else .5 if child == 14 else 30
        amplitudes.extend(amplitude*(1 if k == 0 else .5 if k == 4 else .3) for k in range(5))
    amplitudes.append(.001)
    values = [(1 if items[min(max(0, (i-1)//4), len(items)-1)].direction.value == 'up' else -1)
              * amplitudes[min(max(0, (i-1)//4), len(items)-1)] for i in range(count)]
    return items, bars, {'dif': values, 'dea': [v*.8 for v in values],
                         'hist': [v*.4 for v in values]}


def run(items, bars, macd, nested=True):
    return layered_movement_ownership(items, bars, macd,
                                      engineering_movement_hierarchy(items, bars, macd),
                                      nested=nested)


@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('offset', [0, 37])
def test_real_m1_conflict_no_longer_erases_internal_m2(mirror, offset):
    items, bars, macd = nested_fixture(mirror, offset)
    before = deepcopy((items, bars, macd))
    original = current(run(items, bars, macd, False))[0]
    assert original['highest_completed_internal_level'] == 1
    owner = current(run(items, bars, macd))[0]
    lower, higher = owner['levels']
    assert len(lower['types']) == 16
    assert len(higher['types']) == 1
    parent = higher['types'][0]
    assert parent['source_segment_indices'] == list(range(offset+55, offset+80))
    assert parent['known_index'] == parent['original_known_index'] == 525
    assert parent['direction'] == ('up' if mirror else 'down')
    assert 0 < parent['macd_evidence']['area_ratio'] < 1
    domain = owner['nested_owners'][0]
    assert domain['input_level'] == 1 and domain['parent_owner_id'] == owner['id']
    assert domain['source_segment_indices'] == list(range(offset+5, offset+80))
    assert parent['owner_id'] == domain['id']
    assert parent['child_ids'] == [t['id'] for t in lower['types'][10:15]]
    assert parent['opposite_id'] == lower['types'][15]['id']
    assert parent['opposite_id'] not in domain['source_unit_ids']  # External witness, not source.
    for child in lower['types'][10:15]:
        assert child['current_owner_id'] == domain['id']
        assert child['id'] not in owner['frontier_ids']
        assert child['ownership_transfers'][0]['known_index'] >= child['known_index']
        assert child['current_owner_known_index'] >= child['known_index']
    assert parent['id'] in owner['frontier_ids']
    assert not domain['natural_type_complete'] and not parent['eligible_for_external_recursion']
    assert (items, bars, macd) == before


@pytest.mark.parametrize('mirror', [False, True])
def test_recursive_owner_versions_are_prefix_causal_and_frontier_disjoint(mirror):
    items, bars, macd = nested_fixture(mirror)
    full = run(items, bars, macd)
    for count in (140, 375, 400, 425, 500, 525, 526, len(bars)):
        prefix = run(items, bars[:count], macd)
        assert prefix['versions'] == [v for v in full['versions'] if v['known_index'] < count]
        for owner in current(prefix):
            records = {t['id']: t for level in owner['levels'] for t in level['types']}
            covered = [i for identity in owner['frontier_ids']
                       for i in records[identity]['source_segment_indices']]
            assert len(covered) == len(set(covered))
            for domain in owner['nested_owners']:
                assert domain['known_index'] < count
                assert set(domain['source_segment_indices']) <= set(owner['source_segment_indices'])
                assert all(a['admitted_index'] < count for a in domain['member_admissions'])
            for record in records.values():
                assert record['known_index'] < count
    assert current(run(items, bars[:525], macd))[0]['highest_completed_internal_level'] == 1


def test_recursive_closure_still_requires_macd_and_reverse():
    items, bars, macd = nested_fixture()
    assert all(not v['levels'] for v in run(items, bars, {})['versions'])
    items[-1].confirmed_index = None
    assert current(run(items, bars, macd))[0]['highest_completed_internal_level'] == 1


def records_for(items):
    return {s.index: {'id': f'input:{s.index}', 'source_segment_indices': [s.index],
                     'known_index': s.confirmed_index, 'current_owner_id': 'root'} for s in items}


def test_different_ownership_splits_otherwise_connected_recursive_input():
    items, _, _ = signal_fixture([40, 30, 38, 32])
    records = records_for(items)
    records[1]['current_owner_id'] = 'child'
    assert len(_chains(items, records)) == 1
    assert [len(chain) for chain in _chains(items, records, respect_ownership=True)] == [1, 1, 1]


@pytest.mark.parametrize('fault', ['partial', 'witness'])
def test_cross_owner_candidates_and_other_owner_witnesses_are_rejected(monkeypatch, fault):
    items, bars, macd = fixture(CONSOLIDATION, 0, 4)
    claims = [{'key': 'a', 'kind': 'expansion',
               'sources': [2, 3] if fault == 'partial' else list(range(5))}]
    if fault == 'witness':
        claims.append({'key': 'b', 'kind': 'expansion', 'sources': [5]})
    module = import_module('easy_tdx.chanlun.layered_ownership')
    monkeypatch.setattr(module, '_claim_events', lambda _: {125: claims})
    candidates, _, blocked = nested_candidates(items, bars, macd, records_for(items), 1, 'root')
    assert not candidates
    assert blocked[0]['reason'] == ('crosses_current_ownership_boundary' if fault == 'partial'
                                   else 'opposite_witness_owned_by_another_domain')


def test_later_ownership_delays_availability_without_rewriting_original_completion(monkeypatch):
    items, bars, macd = fixture(CONSOLIDATION, 0, 4)
    module = import_module('easy_tdx.chanlun.layered_ownership')
    monkeypatch.setattr(module, '_claim_events', lambda _: {
        150: [{'key': 'later', 'kind': 'promotion', 'sources': list(range(5))}]})
    candidates, owners, _ = nested_candidates(items, bars, macd, records_for(items), 2, 'outer')
    assert candidates[0]['original_known_index'] == 125
    assert candidates[0]['known_index'] == candidates[0]['ownership_known_index'] == 150
    assert owners[0]['input_level'] == 2


def test_api_isolation_dates_and_preserved_v1():
    from easy_tdx.chanlun.analyser import ChanlunResult
    items, bars, macd = nested_fixture()
    result = ChanlunResult(xds=items, klines=bars, macd=macd)
    payload = result.to_dict()
    assert payload['layered_movement_ownership']['rule'] == 'layered_internal_ownership_v1'
    original = current(payload['layered_movement_ownership'])[0]
    assert original['highest_completed_internal_level'] == 1
    recursive = payload['recursive_movement_ownership']
    assert recursive['rule'] == 'layered_recursive_ownership_v2'
    owner = current(recursive)[0]
    assert owner['levels'][1]['types'][0]['known_date'] == result._fmt_dt(bars[525].date)
    assert 'known_date' in owner['levels'][0]['types'][0]['ownership_transfers'][0]
    assert not payload['structure_metadata']['recursive_levels_ready']
    assert not payload['mmds'] and not payload['bcs']
    json.dumps(recursive, allow_nan=False)
    owner['nested_owners'].clear()
    assert current(result.to_dict()['recursive_movement_ownership'])[0]['nested_owners']


def triple_fixture(mirror=False):
    """Lift the previous example again; every low-level closure uses real MACD."""
    old, _, old_macd = nested_fixture()
    targets = [s.start.val for s in old] + [old[-1].end.val]
    prices, amplitudes = [-1000, 1000, -800, 800, -600, 600], [0.] * 6
    pattern = CONSOLIDATION[:-1]
    for i, (a, b) in enumerate(zip(targets, targets[1:])):
        prices.extend(a+(b-a)*(p-pattern[0])/(pattern[-1]-pattern[0]) for p in pattern[:-1])
        amplitude = max(abs(old_macd['dif'][4*i+1]), .0001)
        amplitudes.extend(amplitude*(1 if k == 0 else .5 if k == 4 else .3) for k in range(5))
    prices += [targets[-1], targets[-1]+1]
    amplitudes.append(.000001)
    if mirror:
        prices = [2000-p for p in prices]
    items, _, _ = signal_fixture(prices)
    count = 101 + len(items)*5
    bars = [Kline(i, datetime(2020, 1, 1)+timedelta(days=i),
                  *[prices[min(i//4, len(prices)-1)]]*4, 0) for i in range(count)]
    values = [(1 if items[min(max(0, (i-1)//4), len(items)-1)].direction.value == 'up' else -1)
              * amplitudes[min(max(0, (i-1)//4), len(items)-1)] for i in range(count)]
    return items, bars, {'dif': values, 'dea': [v*.8 for v in values],
                         'hist': [v*.4 for v in values]}


def final_internal_snapshot(items, bars, macd, nested=True):
    """Test one engine snapshot, without serializing hundreds of API revisions."""
    from easy_tdx.chanlun.engineering_consolidations import consolidation_candidates
    from easy_tdx.chanlun.engineering_trends import _candidates, _hierarchy
    from easy_tdx.chanlun.extension_recursion import promoted_member_times
    from easy_tdx.chanlun.structure import confirmed_segment_prefix
    available = confirmed_segment_prefix(items, len(bars))
    times = promoted_member_times(available)
    local = consolidation_candidates(available, bars, macd)
    local += [{**c, 'kind': 'trend'} for c in _candidates(available, bars, macd, internal=True)]
    seed = []
    for candidate in local:
        indices = range(candidate['start_unit_index'], candidate['end_unit_index']+1)
        if not all(i in times for i in indices):
            continue
        ownership = max(times[i] for i in indices)
        seed.append({**candidate, 'original_known_index': candidate['known_index'],
                     'ownership_known_index': ownership,
                     'known_index': max(candidate['known_index'], ownership)})
    owner_id = (f'owner:{available[0].index}:{available[-1].index}'
                f':at:{available[-1].confirmed_index}') if available else 'owner:0:0:at:0'
    return _hierarchy(available, bars, macd, mixed=True, internal_seed=seed,
                      owner_id=owner_id, nested=nested)


@pytest.mark.parametrize('mirror', [False, True])
def test_real_three_levels_include_two_nested_ownership_generations(mirror):
    items, bars, macd = triple_fixture(mirror)
    result = final_internal_snapshot(items, bars, macd)
    assert [(level['level'], len(level['types'])) for level in result['levels']] == [
        (1, 86), (2, 16), (3, 1)]
    first, second = result['nested_owners']
    assert first['input_level'] == 1 and second['input_level'] == 2
    assert second['parent_owner_id'] == first['id']
    parent = result['levels'][2]['types'][0]
    assert parent['source_segment_indices'] == list(range(281, 406))
    assert parent['owner_id'] == second['id']
    assert parent['known_index'] == 2280
    assert 0 < parent['macd_evidence']['area_ratio'] < 1
    lookup = {t['id']: t for level in result['levels'] for t in level['types']}
    assert parent['source_segment_indices'] == [
        i for child in parent['child_ids'] for i in lookup[child]['source_segment_indices']]
    assert lookup[parent['opposite_id']]['known_index'] == 2280
    assert final_internal_snapshot(items, bars[:2280], macd)[
        'highest_completed_movement_level'] == 2
    assert final_internal_snapshot(items, bars, macd, False)[
        'highest_completed_movement_level'] == 1
