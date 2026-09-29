"""Directed multi-centre candidates widen research, never certify completion."""
from copy import deepcopy
from random import Random

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.expansion_regrouping import (
    _endpoints_consistent,
    _partition,
    _research_partition,
    _trend_component_prefixes,
)
from easy_tdx.chanlun.regrouping_versions import regrouping_versions
from easy_tdx.chanlun.structure import find_structural_centres
from tests.unit.test_chanlun_anchors import bars_for
from tests.unit.test_chanlun_extension_recursion import oscillation
from tests.unit.test_chanlun_regrouping_versions import assert_causal
from tests.unit.test_chanlun_structure import segments

TREND = [0, 10, 2, 8, 3, 20, 15, 22, 17, 30, 25, 32, 27, 34]
PARTITION = [100, 110, 108, 115, 111, 131, 125, 130, 124, 146, 134, 155, 146,
             168, 148, 165, 146, 166, 150, 172, 163, 169, 163, 168, 158, 179]
INTEGRATION = [100, 119, 107, 123, 111, 130, 125, 132, 123, 137, 132, 147, 135,
               156, 145, 148, 145, 147, 128, 139, 124, 127, 112, 132, 114, 132,
               118, 140, 132, 149]


@pytest.mark.parametrize('sign', [1, -1])
@pytest.mark.parametrize('offset', [0, 41])
def test_two_and_three_centres_form_directed_candidates(sign, offset):
    items = segments([sign*p for p in TREND])
    for s in items:
        s.index += offset
    summaries = _trend_component_prefixes(items, 0)
    for stop, count in [(7, 1), (9, 2), (13, 3)]:
        summary = summaries[stop]
        assert len(summary['centre_chain']) == count
        assert summary['component_kind'] == ('trend_candidate' if count > 1
                                             else 'consolidation_candidate')
        for a, b in zip(summary['centre_chain'], summary['centre_chain'][1:]):
            assert b['low'] > a['high'] if sign == 1 else b['high'] < a['low']
        assert all(c['formed_index'] <= summary['known_index'] for c in summary['centre_chain'])
        assert not summary['natural_type_complete']


@pytest.mark.parametrize('sign', [1, -1])
def test_wider_search_finds_consistent_partition_missing_in_old_model(sign):
    items = segments([sign*p for p in PARTITION])
    assert _partition(items) is None
    parts = _research_partition(items)
    assert parts and _endpoints_consistent(parts)
    assert [len(p['source_segment_indices']) for p in parts] == [13, 3, 9]
    assert parts[0]['component_kind'] == 'trend_candidate'
    assert [i for p in parts for i in p['source_segment_indices']] == list(range(25))
    assert all(not p['natural_type_complete'] for p in parts)


@pytest.mark.parametrize('prices', [
    [14, 10, 12, 8, 20, 16, 22, 18],  # Opposite progression to component direction.
    [0, 10, 2, 8, 3, 20, 10, 22, 17, 24],  # Envelopes merely touch.
    [0, 10, 2, 8, 3, 20, 9, 22, 17, 24],  # Envelopes overlap.
])
def test_opposite_touching_or_overlapping_centres_are_not_trend_components(prices):
    result = _trend_component_prefixes(segments(prices), 0)
    assert all(p['component_kind'] != 'trend_candidate' for p in result.values())


def test_later_expansion_or_upgrade_does_not_erase_earlier_valid_prefixes():
    for items in [segments(TREND[:10] + [5, 9, 4]), oscillation(81)]:
        full = _trend_component_prefixes(items, 0)
        for stop in range(1, len(items)+1):
            assert _trend_component_prefixes(items[:stop], 0) == {
                k: v for k, v in full.items() if k <= stop}
    assert list(_trend_component_prefixes(oscillation(81), 0)) == [3, 5, 7]


def test_rolling_eligibility_matches_independent_batch_definition():
    rng = Random(3701)
    samples = [TREND, PARTITION, INTEGRATION]
    for _ in range(12):
        prices = [100]
        for i in range(20):
            prices.append(prices[-1] + (1 if i % 2 == 0 else -1)*rng.randint(1, 20))
        samples.append(prices)
    for prices in samples:
        items = segments(prices)
        for start in range(len(items)):
            found = _trend_component_prefixes(items, start)
            for stop in range(start+1, len(items)+1):
                chunk = items[start:stop]
                first, last = chunk[0], chunk[-1]
                centres = find_structural_centres(chunk)
                up = first.direction.value == 'up'
                valid = (bool(centres) and first.direction == last.direction
                         and (last.end.val > first.start.val if up else
                              last.end.val < first.start.val)
                         and all(len(c.member_segments) < 9 for c in centres)
                         and all(b.dd > a.gg if up else b.gg < a.dd
                                 for a, b in zip(centres, centres[1:])))
                assert (stop in found) == valid
                if valid:
                    assert found[stop]['centre_chain'] == [{
                        'seed_segment_indices': c.seed_segments, 'formed_index': c.formed_index,
                        'zd': c.zd, 'zg': c.zg, 'low': c.dd, 'high': c.gg,
                    } for c in centres]


def test_existing_consistent_single_centre_partition_is_preserved():
    from tests.unit.test_chanlun_expansion_regrouping import PRICES
    items = segments(PRICES)[:15]
    original = _partition(items)
    assert original and _endpoints_consistent(original)
    assert _research_partition(items) == original


def test_actual_cases_and_all_historical_prefixes_are_causal():
    items = segments(INTEGRATION)
    data = regrouping_versions(items)
    assert data['rule'] == 'causal_regrouping_versions_v3'
    assert any(p.get('component_kind') == 'trend_candidate' for c in data['cases']
               for p in c['revisions'][-1]['parts'])
    assert_causal(items)


@pytest.mark.parametrize('fault', ['unconfirmed', 'gap', 'raw_future'])
def test_new_search_never_bridges_rejected_suffix(fault):
    items = segments(INTEGRATION)
    expected = regrouping_versions(items[:20])
    if fault == 'unconfirmed':
        items[20].confirmed_index = None
    elif fault == 'gap':
        items[20].index += 1
    else:
        items[20].end = deepcopy(items[20].end)
        items[20].end.k.k_index = 9999
    assert regrouping_versions(items)['cases'] == expected['cases']


def test_candidate_snapshots_and_serialized_centre_dates_are_independent():
    items = segments(TREND)
    summaries = _trend_component_prefixes(items, 0)
    earlier = deepcopy(summaries[9])
    summaries[13]['centre_chain'][0]['seed_segment_indices'].clear()
    assert summaries[9] == earlier
    items = segments(INTEGRATION)
    result = ChanlunResult(frequency='5min', xds=items, klines=bars_for(items))
    payload = result.to_dict()
    assert not payload['structure_metadata']['recursive_levels_ready']
    chains = [p['centre_chain'] for c in payload['regrouping_versions']['cases']
              for r in c['revisions'] for p in r['parts'] if 'centre_chain' in p]
    assert chains
    for chain in chains:
        for c in chain:
            assert c['formed_date'] == result._fmt_dt(result.klines[c['formed_index']].date)
    saved = deepcopy(payload)
    chains[0][0]['seed_segment_indices'].append(9999)
    assert result.to_dict() == saved
