"""Nested geometry records its actual admission witnesses without owning them."""
from copy import deepcopy

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.extension_recursion import extension_hierarchy
from easy_tdx.chanlun.structure import find_structural_centres
from tests.unit.test_chanlun_anchors import bars_for
from tests.unit.test_chanlun_structure import segments


def delayed_chain(count=27, sign=1, offset=0):
    prices = [0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 4]
    for i in range(10, count):
        prices.append(8 if i % 2 == 0 else 2)
    items = segments([sign * p for p in prices])
    for item in items:
        item.index += offset
    return items


def nodes(proof):
    yield proof
    for child in proof['children']:
        yield from nodes(child)


@pytest.mark.parametrize('count', [27, 81])
@pytest.mark.parametrize('sign', [1, -1])
@pytest.mark.parametrize('offset', [0, 17])
def test_every_nested_node_has_exact_members_and_actual_witnesses(count, sign, offset):
    items = delayed_chain(count, sign, offset)
    lookup = {item.index: item for item in items}
    before = deepcopy(items)
    hierarchy = extension_hierarchy(items)
    for root in hierarchy['proofs']:
        for node in nodes(root):
            ledger = node['member_admissions']
            assert [entry['segment_index'] for entry in ledger] == node['source_segment_indices']
            assert node['known_index'] == max(entry['admitted_index'] for entry in ledger)
            for entry in ledger:
                witness = lookup[entry['admission_segment_index']]
                assert witness.confirmed_index == entry['admitted_index']
                assert entry['segment_confirmed_index'] <= entry['admitted_index']
                if entry['reason'] == 'seed_formation':
                    assert witness.index == offset + 2
                elif entry['reason'] == 'extension':
                    assert witness.index == entry['segment_index']
                else:
                    assert entry['reason'] == 'failed_departure_return'
                    assert witness.index == entry['segment_index'] + 1
            assert not node['natural_type_complete']
    first = hierarchy['proofs'][0]
    assert first['member_admissions'][-1]['admission_segment_index'] == offset + 9
    assert offset + 9 not in first['source_segment_indices']
    assert first['known_index'] == items[9].confirmed_index == 145
    assert hierarchy['proofs'][1]['children'][0]['member_admissions'] == first['member_admissions']
    assert items == before


def test_witness_is_not_inferred_from_timestamp_when_confirmations_tie():
    items = delayed_chain()
    for item in items:
        item.confirmed_index = 300
    ledger = find_structural_centres(items)[0].member_admissions
    assert [row['admission_segment_index'] for row in ledger[:3]] == [2, 2, 2]
    assert ledger[8]['admission_segment_index'] == 9
    assert ledger[9]['admission_segment_index'] == 9
    assert ledger[10]['admission_segment_index'] == 10


def test_later_parent_never_backdates_or_revises_an_earlier_proof():
    items = delayed_chain()
    final = extension_hierarchy(items)['proofs']
    for count in range(1, len(items) + 1):
        known = items[count - 1].confirmed_index
        assert extension_hierarchy(items, known + 1)['proofs'] == [
            root for root in final if root['known_index'] <= known]
    assert not extension_hierarchy(items, 145)['proofs']
    assert extension_hierarchy(items, 146)['proofs'][0]['known_index'] == 145


def test_unconfirmed_or_broken_return_cannot_become_a_witness():
    for fault in ('unknown', 'broken'):
        items = delayed_chain()
        if fault == 'unknown':
            items[9].confirmed_index = None
        else:
            items[9].start = deepcopy(items[9].start)
            items[9].start.k.k_index += 1
        assert not extension_hierarchy(items)['proofs']
        ledger = find_structural_centres(items)[0].member_admissions
        assert all(row['admission_segment_index'] < 9 for row in ledger)
        assert len(ledger) == 8


def test_admission_rows_are_independent_between_root_child_and_other_roots():
    roots = extension_hierarchy(delayed_chain())['proofs']
    first, parent = roots
    expected = deepcopy(parent)
    first['member_admissions'][0]['admission_segment_index'] = 999
    first['children'][0]['member_admissions'][0]['admitted_index'] = 999
    assert parent == expected
    parent['children'][0]['member_admissions'][0]['admitted_index'] = 888
    assert parent['member_admissions'][0]['admitted_index'] == 110
    assert parent['children'][0]['children'][0]['member_admissions'][0]['admitted_index'] == 110


def test_api_dates_exist_on_all_nested_admissions_without_enabling_trading():
    items = delayed_chain()
    bars = bars_for(items)
    result = ChanlunResult(frequency='5min', klines=bars, xds=items).to_dict()
    root = result['extension_hierarchy']['proofs'][-1]
    for node in nodes(root):
        for row in node['member_admissions']:
            confirmed = bars[row['segment_confirmed_index']].date.strftime('%Y-%m-%d %H:%M')
            admitted = bars[row['admitted_index']].date.strftime('%Y-%m-%d %H:%M')
            assert row['segment_confirmed_date'] == confirmed
            assert row['admitted_date'] == admitted
    assert root['children'][0]['member_admissions'][-1]['admitted_date'] == '2026-01-01 02:25'
    assert not result['structure_metadata']['recursive_levels_ready']
    assert not result['mmds']
