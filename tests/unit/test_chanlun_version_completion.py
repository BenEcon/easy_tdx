"""Completion evidence is bound to a version's actual partition and time."""
from copy import deepcopy

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.expansion_regrouping import expansion_regrouping
from easy_tdx.chanlun.regrouping_versions import regrouping_versions
from tests.unit.test_chanlun_anchors import bars_for
from tests.unit.test_chanlun_regrouping_starts import PRICES
from tests.unit.test_chanlun_regrouping_versions import assert_causal
from tests.unit.test_chanlun_structure import segments


def case(items, count=None, offset=0):
    return next(c for c in regrouping_versions(items, count)['cases']
                if c['candidate_id'] == f'expansion:{6+offset}:{15+offset}')


@pytest.mark.parametrize('sign', [1, -1])
@pytest.mark.parametrize('offset', [0, 31])
def test_audit_tracks_rebased_parts_not_original_formation(sign, offset):
    items = segments([sign*p for p in PRICES])
    for s in items:
        s.index += offset
    c = case(items, offset=offset)
    r = c['revisions'][-1]
    audit = c['completion_audit']
    assert audit['interpretation_id'] == r['id']
    assert audit['as_of_index'] == c['as_of_index']
    assert [p['source_segment_indices'] for p in audit['parts']] == [
        p['source_segment_indices'] for p in r['parts']]
    assert [p['opposite_segment_index'] for p in audit['parts']] == [
        14+offset, 19+offset, 24+offset]
    assert [p['opposite_evidence']['source_part_index'] for p in audit['parts']] == [1, 2, None]
    assert 'retained_prefix_unresolved' in audit['blocking_reasons']
    assert all(p['start_is_extreme'] and p['end_is_extreme'] for p in audit['parts'])
    assert not audit['natural_type_complete'] and not audit['eligible_for_recursive_input']
    assert not any(x['candidate_id'] == c['candidate_id']
                   for x in expansion_regrouping(items)['completion_audits'])


def test_new_opposite_evidence_updates_snapshot_without_rewriting_revision():
    items = segments(PRICES)
    before, at = case(items, 220), case(items, 221)
    assert before['current_revision_id'] == at['current_revision_id']
    assert before['revisions'] == at['revisions']
    assert before['completion_audit']['parts'][-1]['opposite_segment_index'] is None
    assert at['completion_audit']['parts'][-1]['opposite_segment_index'] == 24
    history = at['revisions'][-1]['completion_audit']
    assert history['as_of_index'] == 215
    assert history['parts'][-1]['opposite_segment_index'] is None
    assert at['completion_audit']['as_of_index'] == 220


def test_every_historical_boundary_is_causal_with_new_audits():
    assert_causal(segments(PRICES))


@pytest.mark.parametrize('fault', ['unconfirmed', 'gap', 'future_anchor'])
def test_rejected_tail_cannot_supply_confirmation(fault):
    items = segments(PRICES)
    expected = case(items[:24])
    if fault == 'unconfirmed':
        items[24].confirmed_index = None
    elif fault == 'gap':
        items[24].index += 1
    else:
        items[24].end = deepcopy(items[24].end)
        items[24].end.k.k_index = 9999
    assert case(items) == expected


def test_higher_proof_priority_never_audits_stale_flat_parts():
    prices = [100, 114, 102, 109, 104, 118, 109, 122, 116, 127,
              113, 124, 112, 119, 116, 125, 124, 127, 113]
    cases = regrouping_versions(segments(prices))['cases']
    audits = [c['completion_audit'] for c in cases if c['revisions'][-1]['higher_proof_ids']]
    assert audits
    for audit in audits:
        assert not audit['parts']
        assert 'higher_proof_requires_regrouping' in audit['blocking_reasons']
        assert 'no_current_partition' in audit['blocking_reasons']


def test_snapshot_isolation_and_api_dates():
    items = segments(PRICES)
    result = ChanlunResult(frequency='5min', xds=items, klines=bars_for(items))
    payload = result.to_dict()
    saved = deepcopy(payload)
    for c in payload['regrouping_versions']['cases']:
        for a in [c['completion_audit'], *(r['completion_audit'] for r in c['revisions'])]:
            assert a['as_of_date'] == result._fmt_dt(result.klines[a['as_of_index']].date)
            for p in a['parts']:
                evidence = p['opposite_evidence']
                if evidence:
                    for key in ('start', 'end', 'known'):
                        assert evidence[f'{key}_date'] == result._fmt_dt(
                            result.klines[evidence[f'{key}_index']].date)
    payload['regrouping_versions']['cases'][1]['completion_audit']['parts'][0][
        'source_segment_indices'].append(999)
    assert result.to_dict() == saved
    assert payload['regrouping_versions']['cases'][1]['revisions'] == (
        saved['regrouping_versions']['cases'][1]['revisions'])


def test_no_cases_or_empty_parts_are_not_vacuously_complete():
    assert not regrouping_versions([])['cases']
    a = case(segments(PRICES), 196)['completion_audit']
    assert not a['parts']
    assert a['blocking_reasons'] == ['no_current_partition', 'same_level_completion_unproven']
    assert not a['eligible_for_recursive_input']
