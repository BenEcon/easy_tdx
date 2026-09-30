"""Nested ownership keeps its actual admission history, not only the final placement."""
from copy import deepcopy
from importlib import import_module

import pytest

from easy_tdx.chanlun.nested_recursion import _NestedScanCache, nested_candidates
from tests.unit.test_chanlun_engineering_movements import CONSOLIDATION
from tests.unit.test_chanlun_nested_ownership import records_for
from tests.unit.test_chanlun_signal_levels import fixture


def lifecycle_case(monkeypatch, mirror=False, offset=0, reverse=False):
    items, bars, macd = fixture(CONSOLIDATION + [22, 27, 21, 25, 19], 0, 4, mirror)
    for item in items:
        item.index += offset
    events = {
        125: [{'key': 'a', 'kind': 'promotion', 'sources': list(range(offset, offset+3))},
              {'key': 'b', 'kind': 'promotion', 'sources': list(range(offset+5, offset+8))}],
        140: [{'key': 'a', 'kind': 'promotion', 'sources': list(range(offset, offset+5))}],
        145: [{'key': 'join', 'kind': 'expansion', 'sources': [offset+4, offset+5]}],
        150: [{'key': 'extra-proof', 'kind': 'promotion', 'sources': [offset+1, offset+2]}],
    }
    # Both initial claims are causally visible in the same batch.
    for item in items[5:8]:
        item.confirmed_index = 125
    if reverse:
        events[125].reverse()
    module = import_module('easy_tdx.chanlun.layered_ownership')
    monkeypatch.setattr(module, '_claim_events', lambda chain: deepcopy({
        k: v for k, v in events.items() if k <= chain[-1].confirmed_index}))
    return items, bars, macd


@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('offset', [0, 37])
def test_formation_extension_and_merge_preserve_the_original_admission_path(
        monkeypatch, mirror, offset):
    items, bars, macd = lifecycle_case(monkeypatch, mirror, offset)
    records = records_for(items)
    _, owners, _ = nested_candidates(items, bars, macd, records, 1, 'root')
    assert len(owners) == 1
    owner = owners[0]
    events = owner['lifecycle_events']
    assert [e['known_index'] for e in events] == [125, 125, 140, 145]
    assert [e['kind'] for e in events] == ['formed', 'formed', 'expanded', 'merged']
    assert [e['source_unit_count'] for e in events] == [3, 3, 5, 8]
    assert events[2]['previous_owner_ids'] == [events[0]['id']]
    assert events[3]['previous_owner_ids'] == [events[2]['id'], events[1]['id']]
    assert events[3]['id'] == owner['id']
    assert events[2]['added_unit_ids'] == [f'input:{offset+3}', f'input:{offset+4}']
    assert events[3]['added_unit_ids'] == []  # Merge inherits, rather than newly admits, units.
    assert sorted(i for e in events for i in e['added_unit_ids']) == sorted(
        f'input:{offset+i}' for i in range(8))
    assert owner['known_index'] == 145
    assert records[offset]['ownership_transfers'][0]['known_index'] == 145
    assert events[0]['known_index'] == 125  # Earlier history was not replaced by the merge.
    assert not owner['natural_type_complete']


def test_same_batch_claim_order_does_not_change_history(monkeypatch):
    outputs = []
    for reverse in (False, True):
        items, bars, macd = lifecycle_case(monkeypatch, reverse=reverse)
        outputs.append(nested_candidates(items, bars, macd, records_for(items), 1, 'root'))
    assert outputs[0] == outputs[1]


def test_cached_scans_rebuild_detached_history_for_each_context(monkeypatch):
    items, bars, macd = lifecycle_case(monkeypatch)
    cache = _NestedScanCache(bars, macd)
    first = nested_candidates(items, bars, macd, records_for(items), 1, 'first', scan_cache=cache)
    second = nested_candidates(items, bars, macd, records_for(items), 1, 'second', scan_cache=cache)
    assert first[1][0]['lifecycle_events'][0]['id'].startswith('first/')
    assert second[1][0]['lifecycle_events'][0]['id'].startswith('second/')
    expected = deepcopy(second)
    first[1][0]['lifecycle_events'][0]['added_unit_ids'].clear()
    assert second == expected
    assert nested_candidates(items, bars, macd, records_for(items), 1, 'second',
                             scan_cache=cache) == expected


@pytest.mark.parametrize('cached', [False, True])
def test_prefixes_only_contain_observed_events_and_old_records_do_not_change(monkeypatch, cached):
    items, bars, macd = lifecycle_case(monkeypatch)
    cache = _NestedScanCache(bars, macd) if cached else None
    snapshots = []
    for known in (125, 140, 145, 150):
        visible = [item for item in items if item.confirmed_index <= known]
        _, owners, _ = nested_candidates(visible, bars[:known+1], macd, records_for(visible),
                                         1, 'root', scan_cache=cache)
        snapshots.append(owners)
        assert all(e['known_index'] <= known for owner in owners for e in owner['lifecycle_events'])
    final = snapshots[-1][0]['lifecycle_events']
    assert [len(owners) for owners in snapshots] == [2, 2, 1, 1]
    assert snapshots[-2] == snapshots[-1]  # No fake migration for an extra proof in the same range.
    for owners in snapshots:
        for owner in owners:
            assert all(event in final for event in owner['lifecycle_events'])
    earlier = deepcopy(snapshots[0])
    final[0]['added_unit_ids'].clear()
    assert snapshots[0] == earlier


def test_real_nested_api_has_dated_history_and_summary_matches_full():
    from easy_tdx.chanlun.analyser import ChanlunResult
    from easy_tdx.chanlun.ownership_history import summarize_ownership_history
    from tests.unit.test_chanlun_nested_ownership import nested_fixture

    items, bars, macd = nested_fixture()
    result = ChanlunResult(xds=items, klines=bars, macd=macd)
    full = result.to_dict()['recursive_movement_ownership']
    summary = result.to_dict(ownership_history='summary')['recursive_movement_ownership']
    assert summary == summarize_ownership_history(full)
    events = summary['versions'][0]['nested_owners'][0]['lifecycle_events']
    assert events and all(e['known_date'] == result._fmt_dt(bars[e['known_index']].date)
                          for e in events)
    assert len({i for e in events for i in e['added_unit_ids']}) == 15
