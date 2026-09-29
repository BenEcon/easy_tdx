"""Whole proof atoms and unresolved base runs must cover sources exactly once."""
from copy import deepcopy

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.extension_recursion import extension_hierarchy
from easy_tdx.chanlun.mixed_sources import mixed_source_cover
from easy_tdx.chanlun.regrouping_versions import regrouping_versions
from tests.unit.test_chanlun_anchors import bars_for
from tests.unit.test_chanlun_extension_recursion import oscillation
from tests.unit.test_chanlun_regrouping_starts import PRICES
from tests.unit.test_chanlun_structure import segments


def cover(items, proofs=None, roles=None):
    return mixed_source_cover(
        items, extension_hierarchy(items)['proofs'] if proofs is None else proofs,
        {s.index: 'pending_tail' for s in items} if roles is None else roles,
        items[-1].confirmed_index if items else 0, 'case:v1')


def assert_coverage(result):
    assert result['status'] == 'covered'
    assert [i for b in result['blocks'] for i in b['source_segment_indices']] == (
        result['source_segment_indices'])
    for block in result['blocks']:
        assert [i for role in block['role_spans'] for i in role['source_segment_indices']] == (
            block['source_segment_indices'])
        assert block['known_index'] <= result['as_of_index']
        assert not block['natural_type_complete']
    assert not result['eligible_for_recursive_input'] and not result['natural_type_complete']


@pytest.mark.parametrize('count,level', [(8, 0), (9, 2), (26, 2), (27, 3), (81, 4)])
def test_nine_27_81_proofs_replace_children_without_double_ownership(count, level):
    result = cover(oscillation(count))
    assert_coverage(result)
    proofs = [b for b in result['blocks'] if b['kind'] == 'extension_proof']
    assert [b['level'] for b in proofs] == ([level] if level else [])
    if level:
        assert len(proofs[0]['source_segment_indices']) == 3 ** level


def test_disjoint_proofs_are_kept_in_order_even_if_input_is_reversed():
    items = oscillation(81)
    proofs = extension_hierarchy(items)['proofs'][-1]['children']
    result = cover(items, proofs=list(reversed(proofs)))
    assert_coverage(result)
    assert [b['source_segment_indices'][0] for b in result['blocks']] == [0, 27, 54]


def test_parent_not_yet_known_cannot_hide_visible_child_or_base_tail():
    items = oscillation(81)
    proofs = extension_hierarchy(items)['proofs']
    result = cover(items[:26], proofs=proofs)
    assert_coverage(result)
    assert [b['level'] for b in result['blocks']] == [2, 0]
    assert result['blocks'][1]['source_segment_indices'] == list(range(9, 26))


def test_role_boundary_does_not_slice_an_indivisible_proof():
    items = oscillation(27)
    roles = {s.index: ('retained_prefix' if s.index < 3 else
                       'unresolved_selection' if s.index < 18 else 'pending_tail') for s in items}
    result = cover(items, roles=roles)
    assert_coverage(result)
    assert len(result['blocks']) == 1
    block = result['blocks'][0]
    assert block['crosses_role_boundary'] and result['joint_regrouping_required']
    assert [r['source_segment_indices'] for r in block['role_spans']] == [
        list(range(3)), list(range(3, 18)), list(range(18, 27))]


@pytest.mark.parametrize('side', ['left', 'right'])
def test_window_cannot_clip_a_known_proof_into_fake_base_sources(side):
    items = oscillation(9)
    proof = extension_hierarchy(items)['proofs'][0]
    part = items[1:] if side == 'left' else items[:-1]
    result = mixed_source_cover(part, [proof], {s.index: 'pending_tail' for s in part},
                                proof['known_index'], 'case:v1')
    assert result['status'] == 'blocked' and result['blocks'] == []
    assert result['source_segment_indices'] == [s.index for s in part]
    assert result['conflicts'][0]['source_segment_indices'] == list(range(9))
    assert result['conflicts'][0]['reason'] == 'proof_crosses_window'


def test_non_nested_overlapping_proofs_block_instead_of_greedy_selection():
    items = oscillation(12)
    proof = extension_hierarchy(items)['proofs'][0]
    other = {**proof, 'id': 'conflicting', 'source_segment_indices': list(range(3, 12))}
    result = cover(items, proofs=[proof, other])
    assert result['status'] == 'blocked' and not result['blocks']
    assert result['conflicts'][0]['reason'] == 'overlapping_proofs'


@pytest.mark.parametrize('offset', [0, 37])
@pytest.mark.parametrize('sign', [1, -1])
def test_shifted_interpretation_covers_prefix_parts_and_tail_and_keeps_history(offset, sign):
    items = segments([sign * p for p in PRICES])
    for s in items:
        s.index += offset
    result = regrouping_versions(items)
    for case in result['cases']:
        assert_coverage(case['mixed_source_cover'])
        current = case['revisions'][-1]
        assert case['mixed_source_cover']['source_segment_indices'] == (
            current['retained_prefix_segment_indices'] + current['source_segment_indices']
            + case['pending_segment_indices'])
        for r in case['revisions']:
            assert_coverage(r['mixed_source_cover'])
            assert r['mixed_source_cover']['interpretation_id'] == r['id']
            assert r['mixed_source_cover']['as_of_index'] == r['known_index']
    case = next(c for c in result['cases']
                if c['candidate_id'] == f'expansion:{6+offset}:{15+offset}')
    assert [b['role_spans'][0]['role'] for b in case['mixed_source_cover']['blocks']] == [
        'retained_prefix', 'part_0', 'part_1', 'part_2', 'pending_tail']


def test_outputs_are_independent_and_api_dates_do_not_change_original_evidence():
    items = oscillation(27)
    proofs = extension_hierarchy(items)['proofs']
    original = deepcopy(proofs)
    first = cover(items, proofs)
    first['blocks'][0]['source_segment_indices'].append(999)
    first['blocks'][0]['role_spans'][0]['source_segment_indices'].append(999)
    assert proofs == original
    assert_coverage(cover(items, proofs))
    items = segments(PRICES)
    result = ChanlunResult(frequency='5min', xds=items, klines=bars_for(items))
    payload = result.to_dict()
    for c in payload['regrouping_versions']['cases']:
        covers = [c['mixed_source_cover'], *(r['mixed_source_cover'] for r in c['revisions'])]
        for source_cover in covers:
            assert source_cover['as_of_date'] == result._fmt_dt(
                result.klines[source_cover['as_of_index']].date)
            for b in source_cover['blocks']:
                assert b['known_date'] == result._fmt_dt(result.klines[b['known_index']].date)
    assert not payload['mmds'] and not payload['structure_metadata']['recursive_levels_ready']


def test_empty_cover():
    result = cover([])
    assert_coverage(result)
    assert result['blocks'] == result['source_segment_indices'] == []
