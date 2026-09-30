"""Versioned internal ownership cannot spend a source both inside and outside."""
import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from easy_tdx.chanlun.engineering_consolidations import conflict_member_times
from easy_tdx.chanlun.engineering_trends import engineering_movement_hierarchy
from easy_tdx.chanlun.layered_ownership import _domains, layered_movement_ownership
from tests.unit.test_chanlun_engineering_movements import mixed_fixture
from tests.unit.test_chanlun_signal_levels import fixture
from tests.unit.test_chanlun_structure import signal_fixture

PRICES = [40, 30, 38, 32, 37, 20, 29, 22, 28, 18, 35, 25, 34, 20, 32, 15, 30]


def run(items, bars, macd):
    return layered_movement_ownership(items, bars, macd,
                                      engineering_movement_hierarchy(items, bars, macd))


def current(result):
    return [v for v in result['versions'] if v['id'] in result['current_owner_ids']]


def owned_mixed_fixture(mirror=False):
    """Six real mixed children live inside one broad promoted base centre."""
    old, bars, macd, _ = mixed_fixture()
    prices = [-200, 300, -100, 250, -50] + [s.start.val for s in old] + [old[-1].end.val]
    if mirror:
        prices = [400 - p for p in prices]
    items, _, _ = signal_fixture(prices)
    count = 101 + 5 * len(items)
    bars = [replace(bars[0], index=i, date=datetime(2026, 1, 1) + timedelta(days=i),
                    open=prices[min(i//4, len(prices)-1)], close=prices[min(i//4, len(prices)-1)],
                    high=prices[min(i//4, len(prices)-1)], low=prices[min(i//4, len(prices)-1)])
            for i in range(count)]
    macd = {key: [(-v if mirror else v) for v in ([0.] * 20 + values + [values[-1]] * 10)[:count]]
            for key, values in macd.items()}
    return items, bars, macd


@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('offset', [0, 37])
def test_real_locally_complete_type_is_kept_inside_not_exported(mirror, offset):
    items, bars, macd = fixture(PRICES, 10, 14, mirror)
    for item in items:
        item.index += offset
    flat = engineering_movement_hierarchy(items, bars, macd)
    assert not flat['levels']  # Original conservative interpretation is preserved.
    result = layered_movement_ownership(items, bars, macd, flat)
    owners = current(result)
    assert len(owners) == 1
    owner = owners[0]
    assert owner['source_segment_indices'] == list(range(offset, offset + 15))
    records = owner['levels'][0]['types']
    assert len(records) == 1
    record = records[0]
    assert record['source_segment_indices'] == list(range(offset + 10, offset + 15))
    assert record['original_known_index'] == record['known_index'] == 175
    assert record['ownership_known_index'] == 175
    assert record['opposite_id'] == f'segment:{offset + 15}'
    assert record['eligible_for_internal_recursion']
    assert not record['eligible_for_external_recursion']
    assert not record['eligible_for_movement_recursion']
    assert not result['external_m1_ids']
    assert not owner['natural_type_complete']
    assert record['direction'] == ('up' if mirror else 'down')


@pytest.mark.parametrize('mirror', [False, True])
def test_real_internal_children_form_parent_with_independent_gates(mirror):
    items, bars, macd = owned_mixed_fixture(mirror)
    result = run(items, bars, macd)
    owner = current(result)[0]
    assert owner['highest_completed_internal_level'] == 2
    children = owner['levels'][0]['types']
    parent = owner['levels'][1]['types'][0]
    assert {r['kind'] for r in children} == {'trend', 'consolidation'}
    assert parent['source_segment_indices'] == list(range(5, 38))
    assert parent['known_index'] == 335
    assert parent['opposite_id'] == children[-1]['id']
    assert parent['child_ids'] == [r['id'] for r in children[:5]]
    assert 0 < parent['macd_evidence']['area_ratio'] < 1
    assert set(owner['frontier_ids']) == {parent['id'], children[-1]['id']}
    assert not set(parent['child_ids']).intersection(owner['frontier_ids'])
    assert not owner['natural_type_complete']  # Internal parent is NOT the whole owner.
    assert not result['external_m1_ids']
    assert not result['natural_type_recursion_ready']
    before = run(items, bars[:335], macd)
    assert current(before)[0]['highest_completed_internal_level'] == 1


@pytest.mark.parametrize('mirror', [False, True])
def test_every_owner_version_is_causal_and_prefix_immutable(mirror):
    items, bars, macd = owned_mixed_fixture(mirror)
    full = run(items, bars, macd)
    for count in range(135, len(bars) + 1, 5):
        prefix = run(items, bars[:count], macd)
        assert prefix['versions'] == [v for v in full['versions'] if v['known_index'] < count]
        for owner in current(prefix):
            for level in owner['levels']:
                sources = [i for r in level['types'] for i in r['source_segment_indices']]
                assert len(sources) == len(set(sources))
                for record in level['types']:
                    assert record['known_index'] <= owner['known_index'] < count
                    assert set(record['source_segment_indices']) <= set(
                        owner['source_segment_indices'])


@pytest.mark.parametrize('fault', ['hist', 'dea', 'missing', 'reverse'])
def test_internal_ownership_does_not_waive_completion_gates(fault):
    items, bars, macd = fixture(PRICES, 10, 14)
    if fault == 'missing':
        macd = {}
    elif fault == 'reverse':
        items[-1].confirmed_index = None
    else:
        macd[fault] = [-3.] * len(bars)
    assert all(not v['levels'] for v in run(items, bars, macd)['versions'])


def test_claim_union_merges_overlap_but_not_adjacent_owners():
    claims = {str(i): {'key': str(i), 'sources': list(range(a, b + 1))}
              for i, (a, b) in enumerate([(0, 9), (5, 14), (15, 20), (3, 7)])}
    domains = _domains(claims)
    assert [d['sources'] for d in domains] == [list(range(15)), list(range(15, 21))]


def test_owner_coverage_exactly_matches_existing_time_aware_guard():
    from random import Random
    rng = Random(45)
    for _ in range(15):
        prices = [100.]
        for i in range(25):
            prices.append(prices[-1] + (1 if i % 2 else -1) * rng.uniform(1, 30))
        items, bars, macd = signal_fixture(prices)
        for count in (145, 165, 190, 200):
            result = run(items, bars[:count], macd)
            available = [s for s in items if s.confirmed_index < count]
            expected = conflict_member_times(available)
            sources = [i for v in current(result) for i in v['source_segment_indices']]
            assert len(sources) == len(set(sources))
            assert set(sources) == set(expected)
            times = {entry['segment_index']: entry['admitted_index'] for v in current(result)
                     for entry in v['member_admissions']}
            assert times == expected


def test_same_confirmation_batch_no_partial_owner_or_early_internal_type():
    items, bars, macd = fixture(PRICES, 10, 14)
    for item in items:
        item.confirmed_index = 180
    assert not run(items, bars[:180], macd)['versions']
    result = run(items, bars[:181], macd)
    assert len(result['versions']) == 1
    assert current(result)[0]['levels'][0]['types'][0]['known_index'] == 180


def test_no_owner_keeps_external_types_and_unresolved_sources():
    items, bars, macd, _ = mixed_fixture()
    flat = engineering_movement_hierarchy(items, bars, macd)
    result = layered_movement_ownership(items, bars, macd, flat)
    assert not result['versions']
    assert result['external_m1_ids'] == [r['id'] for r in flat['levels'][0]['types']]
    assert result['external_unresolved_segment_indices'] == [42]


def test_history_before_later_ownership_is_retained_but_not_spent_externally():
    from tests.unit.test_chanlun_engineering_completion import matching_fixture
    items, bars, macd = matching_fixture()
    flat = engineering_movement_hierarchy(items, bars, macd)
    result = layered_movement_ownership(items, bars, macd, flat)
    historical = next(r for r in flat['levels'][0]['types'] if r['start_unit_index'] == 3)
    assert historical['known_index'] == 140
    assert historical['id'] not in result['external_m1_ids']
    records = [r for v in result['versions'] for level in v['levels'] for r in level['types']
               if r['level'] == 1 and r['source_segment_indices'] == list(range(3, 8))]
    assert records
    assert all(r['original_known_index'] == 140 and r['known_index'] >= 140 for r in records)


def test_result_isolation_json_and_api_integration():
    from easy_tdx.chanlun.analyser import ChanlunResult
    items, bars, macd = fixture(PRICES, 10, 14)
    before = deepcopy((items, bars, macd))
    result = ChanlunResult(xds=items, klines=bars, macd=macd)
    payload = result.to_dict()
    owner = current(payload['layered_movement_ownership'])[0]
    assert owner['known_date'] == result._fmt_dt(bars[175].date)
    assert owner['levels'][0]['types'][0]['original_known_date'] == result._fmt_dt(bars[175].date)
    assert payload['engineering_movement_hierarchy']['levels'] == []
    assert not payload['structure_metadata']['recursive_levels_ready']
    assert not payload['mmds'] and not payload['bcs']
    json.dumps(payload['layered_movement_ownership'], allow_nan=False)
    payload['layered_movement_ownership']['versions'].clear()
    assert result.to_dict()['layered_movement_ownership']['versions']
    assert (items, bars, macd) == before


@pytest.mark.parametrize('mirror', [False, True])
def test_all_six_children_do_not_complete_parent_without_parent_macd(mirror):
    items, bars, macd = owned_mixed_fixture(mirror)
    # Amplify the fifth/sixth child while preserving each child's own A/C
    # reduction. Parent C is now stronger than parent A and must fail.
    for values in macd.values():
        for i in range(133, len(values)):
            values[i] *= 10000
    owner = current(run(items, bars, macd))[0]
    assert len(owner['levels'][0]['types']) == 6
    assert owner['highest_completed_internal_level'] == 1
    assert len(owner['frontier_ids']) == 6


def test_separate_owners_do_not_join_until_causal_merge_and_keep_old_versions(monkeypatch):
    from importlib import import_module
    items, bars, macd = owned_mixed_fixture()
    prices = [s.start.val for s in items] + [items[-1].end.val, 160.]
    items, _, _ = signal_fixture(prices)
    bars += [replace(bars[-1], index=i) for i in range(len(bars), 350)]
    for values in macd.values():
        values += [values[-1]] * (350 - len(values))
    # Isolate domain merging from the structural detector. Each claim contains
    # only already confirmed sources; MACD and parent closure remain real.
    events = {220: [{'key': 'a', 'kind': 'expansion', 'sources': list(range(5, 24))}],
              330: [{'key': 'b', 'kind': 'expansion', 'sources': list(range(24, 47))}],
              340: [{'key': 'bridge', 'kind': 'expansion', 'sources': [23, 24]}]}
    module = import_module('easy_tdx.chanlun.layered_ownership')
    monkeypatch.setattr(module, '_claim_events', lambda _: deepcopy(events))
    before = run(items, bars[:340], macd)
    assert len(current(before)) == 2
    assert all(v['highest_completed_internal_level'] == 1 for v in current(before))
    after = run(items, bars, macd)
    owner = current(after)[0]
    assert len(owner['previous_owner_ids']) == 2
    assert owner['context_known_index'] == 340
    assert owner['levels'][1]['types'][0]['known_index'] == 340
    assert after['versions'][:-1] == before['versions']
