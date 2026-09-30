"""The base ownership boundary must enforce the same witness gate as M layers."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from importlib import import_module

import pytest

from tests.unit.test_chanlun_engineering_movements import CONSOLIDATION
from tests.unit.test_chanlun_layered_ownership import PRICES
from tests.unit.test_chanlun_nested_ownership import current, run
from tests.unit.test_chanlun_signal_levels import fixture


def install_base_claims(monkeypatch, items, *, concurrent=False, offset=0, reverse=False):
    module = import_module('easy_tdx.chanlun.layered_ownership')
    original = module._claim_events
    first = {'key': 'a', 'kind': 'expansion', 'sources': list(range(offset, offset+5))}
    second = {'key': 'b', 'kind': 'expansion', 'sources': list(range(offset+5, offset+8))}
    events = {125: [first], 135: [second], 140: [
        {'key': 'merge', 'kind': 'expansion', 'sources': [offset+4, offset+5]}]}
    if concurrent:
        # Both domains exist in the completion batch; their iteration order
        # cannot change eligibility. All claimed units confirm in this batch.
        for item in items[5:8]:
            item.confirmed_index = 125
        events = {125: [second, first] if reverse else [first, second], 140: events[140]}

    def claims(chain):
        if chain and chain[0] is items[0]:
            return deepcopy({k: v for k, v in events.items() if k <= chain[-1].confirmed_index})
        return original(chain)

    monkeypatch.setattr(module, '_claim_events', claims)


@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('offset', [0, 37])
def test_witness_migration_revises_current_owner_without_erasing_history(
        monkeypatch, mirror, offset):
    items, bars, macd = fixture(CONSOLIDATION + [22, 27, 21], 0, 4, mirror)
    for item in items:
        item.index += offset
    install_base_claims(monkeypatch, items, offset=offset)
    before = run(items, bars[:135], macd)
    earlier = current(before)[0]
    record = earlier['levels'][0]['types'][0]
    assert record['original_known_index'] == 125
    assert record['opposite_id'] == f'segment:{offset+5}'
    assert offset+5 not in record['source_segment_indices']

    after = run(items, bars[:140], macd)
    owner = current(after)[0]
    assert owner['source_segment_indices'] == list(range(offset, offset+5))
    assert owner['known_index'] == 135
    assert not owner['levels'] and not owner['frontier_ids']
    assert owner['unresolved_segment_indices'] == list(range(offset, offset+5))
    assert owner['blocked_ownership_candidates'] == [{
        'source_unit_ids': [f'segment:{i}' for i in range(offset, offset+5)],
        'original_known_index': 125, 'reason': 'opposite_witness_owned_by_another_domain',
        'ownership_conflict': {
            'input_level': 0, 'source_segment_indices': list(range(offset, offset+5)),
            'source_domains': [list(range(offset, offset+5))],
            'opposite': {'unit_id': f'segment:{offset+5}',
                         'source_segment_indices': [offset+5], 'known_index': 125,
                         'owner_source_segment_indices': list(range(offset+5, offset+8))},
        }}]
    assert earlier in after['versions']
    assert after['versions'][:len(before['versions'])] == before['versions']
    # Additional price bars without a new confirmation do not fabricate revisions.
    assert after == run(items, bars[:139], macd)

    merged = run(items, bars[:141], macd)
    common = current(merged)[0]
    restored = common['levels'][0]['types'][0]
    assert len(common['previous_owner_ids']) == 2
    assert restored['original_known_index'] == 125
    assert restored['known_index'] == restored['ownership_known_index'] == 140
    assert not common['blocked_ownership_candidates']
    assert merged['versions'][:len(after['versions'])] == after['versions']
    for count in (124, 125, 126, 134, 135, 136, 139, 140, 141):
        prefix = run(items, bars[:count], macd)
        assert prefix['versions'] == [v for v in merged['versions'] if v['known_index'] < count]

    # The preserved first-generation interpretation is deliberately unchanged.
    old = current(run(items, bars[:140], macd, nested=False))[0]
    assert old['levels'][0]['types'][0]['known_index'] == 125
    assert 'blocked_ownership_candidates' not in old


@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_same_batch_other_owner_witness_is_never_admitted(monkeypatch, mirror, reverse):
    items, bars, macd = fixture(CONSOLIDATION + [10, 18, 9], 0, 4, mirror)
    install_base_claims(monkeypatch, items, concurrent=True, reverse=reverse)
    assert current(run(items, bars[:126], macd, nested=False))[0]['levels']
    owners = current(run(items, bars[:126], macd))
    assert len(owners) == 2
    assert all(not owner['levels'] for owner in owners)
    assert owners[0]['blocked_ownership_candidates'][0]['original_known_index'] == 125
    assert not run(items, bars[:125], macd)['versions']


def test_blocked_output_is_detached_and_does_not_change_trading_exports(monkeypatch):
    from easy_tdx.chanlun.analyser import ChanlunResult
    items, bars, macd = fixture(CONSOLIDATION + [22, 27, 21], 0, 4)
    install_base_claims(monkeypatch, items)
    result = ChanlunResult(xds=items, klines=bars[:140], macd=macd)
    payload = result.to_dict()
    owner = current(payload['recursive_movement_ownership'])[0]
    assert owner['known_date'] == result._fmt_dt(bars[135].date)
    assert owner['blocked_ownership_candidates'][0]['original_known_date'] == result._fmt_dt(
        bars[125].date)
    owner['blocked_ownership_candidates'][0]['source_unit_ids'].clear()
    again = result.to_dict()
    assert current(again['recursive_movement_ownership'])[0][
        'blocked_ownership_candidates'][0]['source_unit_ids']
    assert again['mmds'] == payload['mmds'] and again['bcs'] == payload['bcs']
    assert not again['structure_metadata']['recursive_levels_ready']


@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('offset', [0, 37])
def test_real_external_witness_is_quarantined_when_admitted_elsewhere(mirror, offset):
    from easy_tdx.chanlun.engineering_trends import engineering_movement_hierarchy
    from easy_tdx.chanlun.layered_ownership import _claim_events

    # A completed down consolidation 0..4 uses 5 as its reverse witness.
    # A separate, smaller up structure really upgrades over 5..19 later.
    # No monkeypatch: ownership geometry and MACD comparison both run normally.
    prices = CONSOLIDATION[:-2] + [20+(40-p)*.25 for p in PRICES]
    items, bars, macd = fixture(prices, 0, 4, mirror)
    original_count = len(bars)
    bars += [replace(bars[-1], index=i,
                     date=bars[-1].date+timedelta(days=i-original_count+1))
             for i in range(original_count, 250)]
    for values in macd.values():
        values += [values[-1]] * (250-len(values))
    for item in items:
        item.index += offset
    before_inputs = deepcopy((items, bars, macd))
    flat = engineering_movement_hierarchy(items, bars, macd)
    record = flat['levels'][0]['types'][0]
    assert record['source_segment_indices'] == list(range(offset, offset+5))
    assert record['opposite_unit_index'] == offset+5 and record['known_index'] == 125
    assert 0 < record['macd_evidence']['area_ratio'] < 1
    admission = min(known for known, claims in _claim_events(items).items()
                    if any(offset+5 in claim['sources'] for claim in claims))
    assert admission > record['known_index']
    assert record['id'] in run(items, bars[:admission], macd)['external_m1_ids']
    for count in (admission+1, len(bars)):
        new = run(items, bars[:count], macd)
        assert record['id'] not in new['external_m1_ids']
        assert set(range(offset, offset+5)) <= set(new['external_unresolved_segment_indices'])
        assert record['id'] in run(items, bars[:count], macd, nested=False)['external_m1_ids']
        assert not new['natural_type_recursion_ready']
    assert current(run(items, bars, macd))[0]['source_segment_indices'] == list(
        range(offset+5, offset+20))
    assert engineering_movement_hierarchy(items, bars, macd) == flat
    assert (items, bars, macd) == before_inputs
