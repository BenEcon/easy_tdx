"""Cross-centre candidates remain separate from confirmed recursive types."""
from copy import deepcopy
from datetime import datetime, timedelta
from random import Random

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.expansion_regrouping import expansion_regrouping
from easy_tdx.chanlun.types import Kline
from tests.unit.test_chanlun_structure import segments

PRICES = [100, 109, 102, 115, 110, 116, 111, 114, 101, 113, 101, 110,
          99, 104, 102, 117, 116, 120, 113]


def test_partition_keeps_connectors_and_does_not_use_envelope_as_core():
    event = expansion_regrouping(segments(PRICES))['candidates'][0]
    assert event['status'] == 'partition_found_awaiting_type_completion'
    assert event['envelope_overlap'] == [101, 115]
    assert event['candidate_core'] == [101, 113]
    assert event['source_segment_indices'] == list(range(11))
    assert [i for part in event['parts'] for i in part['source_segment_indices']] == list(range(11))
    assert [len(part['source_segment_indices']) for part in event['parts']] == [3, 5, 3]
    assert [part['direction'] for part in event['parts']] == ['up', 'down', 'up']
    assert not event['higher_level_confirmed']
    assert not event['natural_type_complete']
    assert all(not part['natural_type_complete'] for part in event['parts'])


def test_waits_for_both_exits_and_stays_frozen_afterwards():
    items = segments(PRICES)
    final = expansion_regrouping(items)['candidates'][0]
    assert final['known_index'] == items[10].confirmed_index
    for size in range(len(items) + 1):
        events = expansion_regrouping(items[:size])['candidates']
        event = next((e for e in events if e['id'] == final['id']), None)
        if size >= 11:
            assert event == final
        elif event:
            assert event['status'] == 'awaiting_centre_exit'
            assert event['parts'] == []
            assert event['known_index'] is None


def test_no_valid_partition_does_not_manufacture_core():
    prices = [100, 105, 103, 108, 102, 117, 104, 112, 106, 109, 106, 118,
              113, 118, 111, 125, 119, 134, 124]
    events = expansion_regrouping(segments(prices))['candidates']
    event = next(e for e in events if e['id'] == 'expansion:7:11')
    assert event['status'] == 'no_three_range_partition'
    assert event['candidate_core'] is None
    assert not event['parts']


def test_touching_envelopes_are_eligible_but_not_a_positive_width_core():
    items = segments([14, 10, 12, 8, 20, 14, 18, 15, 26, 23])
    event = expansion_regrouping(items)['candidates'][0]
    assert event['envelope_overlap'] == [14, 14]
    assert event['status'] == 'no_three_range_partition'
    assert event['candidate_core'] is None
    assert not event['higher_level_confirmed']


def test_already_upgraded_centres_are_not_used_as_base_types():
    prices = [100, 114, 102, 109, 104, 118, 109, 122, 116, 127, 113, 124,
              112, 119, 116, 125, 124, 127, 113]
    event = expansion_regrouping(segments(prices))['candidates'][0]
    assert event['status'] == 'requires_higher_level_inputs'
    assert event['candidate_core'] is None


@pytest.mark.parametrize('offset', [0, 17])
def test_cutoff_invalid_suffix_nonzero_ids_and_no_mutation(offset):
    items = segments(PRICES)
    for item in items:
        item.index += offset
    before = deepcopy(items)
    early = expansion_regrouping(items, items[10].confirmed_index)['candidates'][0]
    assert early['status'] == 'awaiting_centre_exit'
    at = expansion_regrouping(items, items[10].confirmed_index + 1)['candidates'][0]
    assert at['source_segment_indices'] == list(range(offset, offset + 11))
    assert items == before
    items[9].confirmed_index = None
    result = expansion_regrouping(items)
    assert result['accepted_segment_count'] == 9
    assert result['rejected_suffix_count'] == len(items) - 9
    assert all(not e['parts'] for e in result['candidates'])


def test_mirror_and_separated_centres():
    left = expansion_regrouping(segments(PRICES))['candidates'][0]
    right = expansion_regrouping(segments([-price for price in PRICES]))['candidates'][0]
    assert left['known_index'] == right['known_index']
    assert left['candidate_core'] == [-right['candidate_core'][1], -right['candidate_core'][0]]
    assert [p['source_segment_indices'] for p in left['parts']] == [
        p['source_segment_indices'] for p in right['parts']]
    assert not expansion_regrouping(segments([14, 10, 12, 8, 20, 16, 22, 18, 30, 26]))[
        'candidates']


def test_random_prefixes_preserve_mature_candidates():
    random = Random(1701)
    for _ in range(50):
        prices = [100]
        for i in range(24):
            prices.append(prices[-1] + (1 if i % 2 == 0 else -1) * random.randint(1, 15))
        items = segments(prices)
        final = {e['id']: e for e in expansion_regrouping(items)['candidates']}
        for size in range(len(items) + 1):
            for event in expansion_regrouping(items[:size])['candidates']:
                if event['known_index'] is not None:
                    assert event == final[event['id']]
                    assert event['known_index'] <= items[size - 1].confirmed_index


def test_api_exposes_candidates_without_enabling_recursive_signals():
    items = segments(PRICES)
    bars = [Kline(i, datetime(2026, 1, 1) + timedelta(minutes=i), 100, 100, 125, 90, 1)
            for i in range(items[-1].confirmed_index + 1)]
    result = ChanlunResult(frequency='5min', klines=bars, xds=items).to_dict()
    event = result['expansion_regrouping']['candidates'][0]
    assert event['known_date'] == bars[150].date.strftime('%Y-%m-%d %H:%M')
    assert all(part['known_date'] for part in event['parts'])
    assert not result['structure_metadata']['recursive_levels_ready']
    assert not result['mmds']


def test_candidate_parts_have_alternating_endpoint_directions_and_single_centres():
    from easy_tdx.chanlun.structure import find_structural_centres

    random = Random(1702)
    found = 0
    for _ in range(100):
        prices = [100]
        for i in range(24):
            prices.append(prices[-1] + (1 if i % 2 == 0 else -1) * random.randint(1, 15))
        items = segments(prices)
        for event in expansion_regrouping(items)['candidates']:
            if not event['parts']:
                continue
            found += 1
            a, b, c = event['parts']
            assert a['direction'] == c['direction'] != b['direction']
            for part in (a, b, c):
                source = [items[i] for i in part['source_segment_indices']]
                assert len(source) >= 3
                assert source[0].direction.value == source[-1].direction.value == part['direction']
                assert len(find_structural_centres(source)) == 1
                assert part['known_index'] <= event['known_index']
    assert found > 0
