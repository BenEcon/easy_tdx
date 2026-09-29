"""Current interpretations can change; same-input historical revisions cannot."""
from copy import deepcopy
from random import Random

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.expansion_regrouping import expansion_regrouping
from easy_tdx.chanlun.regrouping_versions import _preferred_proofs, regrouping_versions
from tests.unit.test_chanlun_anchors import bars_for
from tests.unit.test_chanlun_expansion_regrouping import LATER_VALID_PRICES, PRICES
from tests.unit.test_chanlun_structure import segments


@pytest.mark.parametrize('sign', [1, -1])
@pytest.mark.parametrize('offset', [0, 31])
def test_new_evidence_replaces_old_conflicting_cuts_not_the_formation(sign, offset):
    items = segments([sign * p for p in PRICES])
    for item in items:
        item.index += offset
    original = deepcopy(items)
    case = regrouping_versions(items)['cases'][0]
    records = case['revisions']
    assert [r['known_index'] for r in records] == [150, 160, 170, 180]
    assert [[len(p['source_segment_indices']) for p in r['parts']] for r in records] == [
        [3, 5, 3], [3, 5, 5], [5, 7, 3], [5, 7, 5]]
    assert records[2]['reason'] == 'endpoint_conflicts_resolved'
    assert records[2]['candidate_core'] == ([100, 116] if sign == 1 else [-116, -100])
    assert records[0]['candidate_core'] == ([101, 113] if sign == 1 else [-113, -101])
    assert case['pending_segment_indices'] == [offset + 17]
    assert case['current_revision_id'] == records[-1]['id']
    frozen = expansion_regrouping(items)['candidates'][0]
    assert frozen['known_index'] == records[0]['known_index']
    assert frozen['parts'] == records[0]['parts']
    for i, record in enumerate(records):
        assert record['version'] == i + 1
        assert record['supersedes'] == (records[i - 1]['id'] if i else None)
        assert not record['natural_type_complete'] and not record['eligible_for_recursive_input']
        assert [s for p in record['parts'] for s in p['source_segment_indices']] == (
            record['source_segment_indices'])
    assert items == original


def assert_causal(items):
    final = regrouping_versions(items)
    final_cases = {c['candidate_id']: c for c in final['cases']}
    for count in sorted({0, *(s.confirmed_index for s in items),
                         *(s.confirmed_index + 1 for s in items)}):
        prefix = regrouping_versions(items, count)
        expected = {key: [r for r in c['revisions'] if r['known_index'] < count]
                    for key, c in final_cases.items() if c['formation_known_index'] < count}
        assert {c['candidate_id']: c['revisions'] for c in prefix['cases']} == expected
        for case in prefix['cases']:
            assert case['current_revision_id'] == case['revisions'][-1]['id']
            assert case['as_of_index'] < count


@pytest.mark.parametrize('prices', [PRICES, LATER_VALID_PRICES])
def test_every_before_and_at_bar_boundary_reconstructs_identical_history(prices):
    assert_causal(segments(prices))


def test_random_prefixes_and_mirrors_do_not_import_future_revisions():
    rng = Random(3301)
    for _ in range(15):
        prices = [100]
        for i in range(26):
            prices.append(prices[-1] + (1 if i % 2 == 0 else -1) * rng.randint(1, 15))
        for sign in (1, -1):
            assert_causal(segments([sign * p for p in prices]))


def test_same_raw_confirmation_is_atomic_and_does_not_emit_fake_intermediate_versions():
    items = segments(PRICES)
    for item in items:
        item.confirmed_index = 200
    result = regrouping_versions(items)
    for case in result['cases']:
        assert len(case['revisions']) == 1
        assert case['revisions'][0]['known_index'] == 200
    assert not regrouping_versions(items, 200)['cases']
    assert regrouping_versions(items, 201) == result


@pytest.mark.parametrize('fault', ['unconfirmed', 'gap', 'raw_future', 'nan'])
def test_invalid_suffix_cannot_repair_a_conflict_or_advance_its_version(fault):
    items = segments(PRICES)
    expected = regrouping_versions(items[:14])
    if fault == 'unconfirmed':
        items[14].confirmed_index = None
    elif fault == 'gap':
        items[14].index += 1
    elif fault == 'raw_future':
        items[14].end = deepcopy(items[14].end)
        items[14].end.k.k_index = 999
    else:
        items[14].low = float('nan')
    result = regrouping_versions(items)
    assert result['cases'] == expected['cases']
    assert result['accepted_segment_count'] == 14
    assert result['rejected_suffix_count'] == len(items) - 14


def test_no_consistent_partition_is_replaced_by_a_later_conflicting_one():
    case = next(c for c in regrouping_versions(segments(LATER_VALID_PRICES))['cases']
                if c['candidate_id'] == 'expansion:15:20')
    assert len(case['revisions']) == 1
    assert case['revisions'][0]['status'] == 'endpoint_consistent_draft'
    assert case['pending_segment_indices'] == [26, 27, 28, 29]


def test_promoted_input_is_not_flattened_into_completed_types():
    prices = [100, 114, 102, 109, 104, 118, 109, 122, 116, 127, 113, 124,
              112, 119, 116, 125, 124, 127, 113]
    case = regrouping_versions(segments(prices))['cases'][0]
    revision = case['revisions'][-1]
    assert revision['status'] == 'requires_higher_level_inputs'
    assert revision['higher_proof_ids']
    assert not revision['parts'] and revision['candidate_core'] is None
    assert not revision['eligible_for_recursive_input']
    assert_causal(segments(prices))


def test_api_dates_and_independent_snapshots_without_new_signals():
    items = segments(PRICES)
    result = ChanlunResult(frequency='5min', xds=items, klines=bars_for(items))
    first = result.to_dict()
    original = deepcopy(first)
    for case in first['regrouping_versions']['cases']:
        for r in case['revisions']:
            assert r['known_date'] == result._fmt_dt(result.klines[r['known_index']].date)
            for p in r['parts']:
                assert p['end_date'] == result._fmt_dt(result.klines[p['end_index']].date)
    revision = first['regrouping_versions']['cases'][0]['revisions'][0]
    revision['parts'][0]['source_segment_indices'].append(999)
    assert result.to_dict() == original
    assert not first['structure_metadata']['recursive_levels_ready']
    assert first['mmds'] == first['structural_signals'] == []


def test_empty_input():
    result = regrouping_versions([])
    assert result['cases'] == []
    assert result['accepted_segment_count'] == result['rejected_suffix_count'] == 0


def test_higher_priority_waits_for_real_knowledge_and_preserves_unrelated_proofs():
    child = dict(id='child', level=2, source_segment_indices=list(range(9)), known_index=140)
    parent = dict(id='parent', level=3, source_segment_indices=list(range(27)), known_index=230)
    other = dict(id='other', level=2, source_segment_indices=list(range(30, 39)), known_index=290)
    proofs = [child, parent, other]
    assert not _preferred_proofs(proofs, 0, 10, 139)
    assert _preferred_proofs(proofs, 0, 10, 140) == [child]
    assert _preferred_proofs(proofs, 0, 10, 230) == [parent]
    assert _preferred_proofs(proofs, 0, 10, 290) == [parent]
    assert _preferred_proofs(proofs, 0, 38, 290) == [parent, other]
    assert not _preferred_proofs(proofs, 27, 29, 290)
