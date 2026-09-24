"""Confirmed-segment centre lifecycle, timing and provenance."""
from datetime import datetime, timedelta

import pytest

from easy_tdx.chanlun.decomposition import decompose_base_chain
from easy_tdx.chanlun.structure import find_structural_centres
from easy_tdx.chanlun.structure_signals import structure_signals, to_chart_signals
from easy_tdx.chanlun.types import FX, XD, CLKline, Direction, FXType, Kline


def segments(prices):
    points = []
    for i, price in enumerate(prices):
        candles = [CLKline(j, datetime(2026, 1, 1) + timedelta(days=j),
                           price, price, price + 1, price - 1, 0, index=j)
                   for j in range(4 * i, 4 * i + 3)]
        points.append(FX(FXType.DI if i % 2 == 0 else FXType.DING,
                         candles[1], candles, price))
    return [XD(a, b, Direction.UP if b.val > a.val else Direction.DOWN,
               index=i, high=max(a.val, b.val), low=min(a.val, b.val),
               confirmed_index=100 + i * 5)
            for i, (a, b) in enumerate(zip(points, points[1:]))]


def test_forms_only_from_three_confirmed_segments():
    items = segments([8, 12, 10, 14])
    assert not find_structural_centres(items[:2])
    result = find_structural_centres(items)
    assert len(result) == 1
    centre = result[0]
    assert (centre.zd, centre.zg, centre.state) == (10, 12, 'formed')
    assert centre.formed_index == 110
    items[-1].confirmed_index = None
    assert not find_structural_centres(items)


@pytest.mark.parametrize('size', range(14))
def test_base_decomposition_covers_each_accepted_segment_once(size):
    items = segments([14, 10, 12, 8, 20, 16, 22, 18, 25, 14, 21, 15, 26, 23])[:size]
    result = decompose_base_chain(items)
    assert [i for b in result['blocks'] for i in b['segment_indices']] == list(range(size))
    assert result['accepted_segment_count'] == size
    assert result['rejected_suffix_count'] == 0
    assert not result['recursive_levels_ready']
    assert all(not b['recursive_type_complete'] for b in result['blocks'])
    assert all(b['known_index'] <= result['as_of_index'] for b in result['blocks'])


def test_base_decomposition_keeps_return_out_of_previous_centre():
    items = segments([14, 10, 12, 8, 20, 16, 22, 18])
    before = decompose_base_chain(items[:4])['blocks']
    assert before[-1]['role'] == 'pending_departure'
    assert not before[-1]['ownership_frozen']
    at_exit = decompose_base_chain(items[:5])['blocks']
    assert [b['role'] for b in at_exit] == ['centre_members', 'connector', 'unassigned']
    assert at_exit[0]['segment_indices'] == [0, 1, 2]
    assert at_exit[1]['segment_indices'] == [3]
    assert at_exit[1]['known_index'] == items[4].confirmed_index
    assert at_exit[-1]['segment_indices'] == [4]
    later = decompose_base_chain(items)['blocks']
    assert later[:2] == at_exit[:2]  # frozen ownership survives future formation
    assert later[-1]['segment_indices'] == [4, 5, 6]
    assert later[-1]['role'] == 'centre_members'
    assert not later[-1]['ownership_frozen']


def test_failed_departure_is_folded_back_without_losing_a_segment():
    items = segments([8, 12, 10, 14, 9, 11])
    result = decompose_base_chain(items)
    assert len(result['blocks']) == 1
    assert result['blocks'][0]['segment_indices'] == [0, 1, 2, 3, 4]
    assert result['blocks'][0]['role'] == 'centre_members'


def test_decomposition_reports_invalid_suffix_and_respects_bar_cutoff():
    items = segments([14, 10, 12, 8, 20, 16, 22, 18])
    bounded = decompose_base_chain(items, bar_count=111)
    assert bounded['accepted_segment_count'] == 3
    assert bounded['rejected_suffix_count'] == 4
    items[4].confirmed_index = None
    truncated = decompose_base_chain(items)
    assert truncated['accepted_segment_count'] == 4
    assert truncated['rejected_suffix_count'] == 3
    assert truncated['blocks'][-1]['role'] == 'pending_departure'


def test_decomposition_random_prefixes_preserve_frozen_ownership():
    from random import Random

    random = Random(20260924)
    for _ in range(40):
        prices = [100.0]
        for index in range(24):
            prices.append(prices[-1] + (1 if index % 2 == 0 else -1)
                          * random.uniform(1, 20))
        items = segments(prices)
        final = decompose_base_chain(items)['blocks']
        for size in range(1, len(items) + 1):
            now = decompose_base_chain(items[:size])['blocks']
            assert [i for b in now for i in b['segment_indices']] == list(range(size))
            for block in now:
                if block['ownership_frozen']:
                    assert block in final


def test_decomposition_empty_and_nonzero_ids():
    assert decompose_base_chain([])['blocks'] == []
    items = segments([8, 12, 10, 14])
    for item in items:
        item.index += 7
    block = decompose_base_chain(items)['blocks'][0]
    assert block['segment_indices'] == [7, 8, 9]
    assert block['role'] == 'centre_members'


def test_departure_is_not_yet_exit():
    centre = find_structural_centres(segments([8, 12, 10, 14, 9]))[0]
    assert centre.state == 'departed'
    assert centre.departure_direction == 'down'
    assert centre.exited_index is None


def test_failed_return_extends_fixed_core():
    centre = find_structural_centres(segments([8, 12, 10, 14, 9, 11]))[0]
    assert centre.state == 'extended'
    assert centre.departure_segment is None
    assert (centre.zd, centre.zg) == (10, 12)
    assert centre.member_segments == [0, 1, 2, 3, 4]


@pytest.mark.parametrize('return_high', [9.5, 10])
def test_down_exit_only_after_first_return_completes(return_high):
    items = segments([8, 12, 10, 14, 7, return_high])
    centre = find_structural_centres(items)[0]
    assert centre.state == 'exited'
    assert centre.return_segment == 4
    assert centre.departure_segment == 3
    assert centre.exited_index == items[4].confirmed_index
    assert centre.member_segments == [0, 1, 2]


def test_up_exit_and_seed_reuse():
    items = segments([14, 10, 12, 8, 16, 13, 18, 15])
    centres = find_structural_centres(items)
    assert len(centres) == 2
    assert centres[0].state == 'exited'
    assert centres[0].departure_direction == 'up'
    assert centres[1].seed_segments == [4, 5, 6]
    # Core separation alone is NOT enough to call a trend: envelopes overlap.
    assert centres[1].relation_at_formation == 'expansion_candidate'


def test_separated_envelopes_are_distinguished_from_expansion():
    centres = find_structural_centres(segments([14, 10, 12, 8, 20, 16, 22, 18]))
    assert len(centres) == 2
    assert centres[1].relation_at_formation == 'separated_up'


@pytest.mark.parametrize('mirror', [1, -1])
def test_relation_updates_when_extension_touches_previous_envelope(mirror):
    items = segments([mirror * p for p in
                      [14, 10, 12, 8, 20, 16, 22, 18, 25, 14, 21, 15, 26, 23]])
    centre = find_structural_centres(items)[1]
    direction = 'separated_up' if mirror == 1 else 'separated_down'
    assert centre.relation_at_formation == direction
    assert centre.relation_current == 'expansion_candidate'
    changes = centre.relation_history
    assert changes[0]['relation'] == direction
    changed = next(e for e in changes if e['relation'] == 'expansion_candidate')
    # Departure is not included until the failed return is confirmed.
    assert changed['known_index'] == items[9].confirmed_index
    assert changed['envelope_overlap'] == [14 * mirror, 14 * mirror]
    assert changes[-1]['both_exited'] is True
    assert changes[-1]['known_index'] == items[12].confirmed_index
    assert changes[-1]['higher_level_confirmed'] is False
    for n in range(7, len(items) + 1):
        prefix = find_structural_centres(items[:n])[1]
        assert prefix.relation_history == [e for e in changes
                                           if e['known_index'] <= items[n - 1].confirmed_index]


def test_relation_evidence_does_not_alias_future_members():
    centre = find_structural_centres(
        segments([14, 10, 12, 8, 20, 16, 22, 18, 25, 14, 21]))[1]
    assert centre.relation_history[0]['member_segments'] == [4, 5, 6]
    assert 8 in centre.relation_history[-1]['member_segments']
    assert not centre.relation_history[-1]['both_exited']


def test_history_transitions_do_not_arrive_before_confirmation():
    items = segments([8, 12, 10, 14, 9, 11, 7, 9, 6, 8])
    full = find_structural_centres(items)
    for n in range(1, len(items) + 1):
        now = items[n - 1].confirmed_index
        prefix = find_structural_centres(items[:n])
        expected = [c for c in full if c.formed_index <= now]
        assert len(prefix) == len(expected)
        for a, b in zip(prefix, expected):
            assert a.transitions == [t for t in b.transitions if t['known_index'] <= now]
            assert (a.zd, a.zg, a.seed_segments) == (b.zd, b.zg, b.seed_segments)


def test_disconnected_or_unknown_segment_is_not_bridged():
    items = segments([8, 12, 10, 14])
    items[1].start = items[0].start
    assert not find_structural_centres(items)


def test_confirmation_order_must_be_monotonic():
    items = segments([8, 12, 10, 14])
    items[2].confirmed_index = 99
    assert not find_structural_centres(items)


def signal_fixture(prices):
    bars = [Kline(i, datetime(2026, 1, 1) + timedelta(days=i),
                  prices[min(i // 4, len(prices)-1)], prices[min(i // 4, len(prices)-1)],
                  prices[min(i // 4, len(prices)-1)] + 1,
                  prices[min(i // 4, len(prices)-1)], 0) for i in range(200)]
    macd = {'dif': [-.5] * 200, 'dea': [-.4] * 200, 'hist': [.1] * 200}
    for i in range(13, 18):
        macd['dif'][i], macd['dea'][i], macd['hist'][i] = -3, -2.5, -2
    for i in range(29, 34):
        macd['dif'][i], macd['dea'][i], macd['hist'][i] = -1.5, -1.2, -.5
    return segments(prices), bars, macd


def test_base_first_buy_requires_two_separated_centres_and_macd():
    items, bars, macd = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18])
    events = structure_signals(items, bars, macd)
    first = [e for e in events if e.signal_type == '1buy']
    assert len(first) == 1
    assert first[0].segment_index == 7
    assert first[0].confirmed_index == items[7].confirmed_index
    assert first[0].evidence['envelopes_separated']
    macd['hist'][30] = -100
    assert not any(e.signal_type == '1buy' for e in structure_signals(items, bars, macd))


def test_second_and_third_buy_can_coexist():
    items, bars, macd = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18, 28, 26])
    events = structure_signals(items, bars, macd)
    at_return = [e for e in events if e.segment_index == 9]
    assert {e.signal_type for e in at_return} == {'2buy', '3buy'}
    second = next(e for e in at_return if e.signal_type == '2buy')
    assert second.evidence['first_segment'] == 7
    assert second.evidence['strength'] == 'held_first_extreme'


def test_weak_second_buy_is_explicit_not_silently_excluded():
    items, bars, macd = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18, 24, 17])
    events = structure_signals(items, bars, macd)
    second = [e for e in events if e.signal_type == '2buy']
    assert len(second) == 1
    assert second[0].evidence['strength'] == 'weak_new_extreme'


def test_no_second_buy_without_first_buy():
    items, bars, macd = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18, 24, 19])
    macd['hist'] = [0] * 200
    events = structure_signals(items, bars, macd)
    assert not any(e.signal_type in ('1buy', '2buy') for e in events)


def test_second_buy_cannot_cross_a_regressing_confirmation_chain():
    items, bars, macd = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18, 28, 26])
    expected = structure_signals(items[:8], bars, macd)
    assert any(event.signal_type == '1buy' for event in expected)
    items[8].confirmed_index = 90  # earlier than the preceding segment's confirmation
    assert structure_signals(items, bars, macd) == expected


@pytest.mark.parametrize('length', [100, 120, 135, 136, 145, 146])
def test_signals_never_use_confirmations_beyond_available_bars(length):
    items, bars, macd = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18, 28, 26])
    expected = structure_signals([s for s in items if s.confirmed_index < length],
                                 bars[:length], macd)
    assert structure_signals(items, bars[:length], macd) == expected


@pytest.mark.parametrize('fault', ['duplicate', 'missing', 'nan', 'inverted', 'direction'])
def test_invalid_segment_suffix_preserves_only_prior_valid_signals(fault):
    items, bars, macd = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18, 28, 26])
    expected = structure_signals(items[:8], bars, macd)
    centres = find_structural_centres(items[:8])
    if fault == 'duplicate':
        items[8].index = items[7].index
    elif fault == 'missing':
        items[8].index += 2
    elif fault == 'nan':
        items[8].low = float('nan')
    elif fault == 'inverted':
        items[8].low = items[8].high + 1
    else:
        items[8].direction = Direction.DOWN
    assert structure_signals(items, bars, macd) == expected
    assert find_structural_centres(items) == centres


@pytest.mark.parametrize('fault', ['short_hist', 'missing_dea', 'nan_dif', 'infinite_hist'])
def test_incomplete_macd_cannot_be_treated_as_weaker_complete_area(fault):
    items, bars, macd = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18, 28, 26])
    if fault == 'short_hist':
        macd['hist'] = macd['hist'][:31]
    elif fault == 'missing_dea':
        del macd['dea']
    elif fault == 'nan_dif':
        macd['dif'][30] = float('nan')
    else:
        macd['hist'][30] = float('inf')
    events = structure_signals(items, bars, macd)
    assert not any(e.signal_type in ('1buy', '2buy') for e in events)


@pytest.mark.parametrize('known', [None, -1, True, 1.5, 10])
def test_invalid_confirmation_time_stops_the_structure_chain(known):
    from easy_tdx.chanlun.structure import confirmed_segment_prefix

    items = segments([8, 12, 10, 14])
    items[2].confirmed_index = known
    assert confirmed_segment_prefix(items) == items[:2]
    assert not find_structural_centres(items)


def test_signals_replay_by_confirmation_not_pivot_date():
    items, bars, macd = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18, 28, 26])
    full = structure_signals(items, bars, macd)
    assert len(full) >= 3
    for n in range(1, len(items)+1):
        now = items[n-1].confirmed_index
        observed = structure_signals(items[:n], bars[:now+1],
                                     {key: value[:now+1] for key, value in macd.items()})
        assert observed == [e for e in full if e.confirmed_index <= now]


def test_sell_signals_mirror_buy_signals():
    prices = [30, 40, 32, 38, 20, 26, 22, 25, 18, 28, 26]
    items, bars, macd = signal_fixture(prices)
    buys = structure_signals(items, bars, macd)
    reverse_items = segments([100-p for p in prices])
    reverse_bars = [Kline(b.index, b.date, 100-b.open, 100-b.close,
                         100-b.low, 100-b.high, b.amount) for b in bars]
    reverse_macd = {key: [-v for v in values] for key, values in macd.items()}
    sells = structure_signals(reverse_items, reverse_bars, reverse_macd)
    mirror = {'1buy': '1sell', '2buy': '2sell', '3buy': '3sell',
              '1sell': '1buy', '2sell': '2buy', '3sell': '3buy'}
    assert {(mirror[e.signal_type], e.segment_index, e.confirmed_index) for e in buys} == {
        (e.signal_type, e.segment_index, e.confirmed_index) for e in sells}


def test_overlapping_envelopes_give_consolidation_not_first_buy():
    items, bars, macd = signal_fixture([23, 40, 32, 38, 20, 26, 22, 25, 18])
    events = structure_signals(items, bars, macd)
    assert any(e.signal_type == 'consolidation_bottom_divergence' for e in events)
    assert not any(e.signal_type == '1buy' for e in events)
    mmds, divergences = to_chart_signals(events, items)
    assert not any(m.mmd_type.value == '1buy' for m in mmds)
    assert len(divergences) == 1
    assert divergences[0].bc_type.value == 'pz'


def test_chart_adapter_keeps_source_and_confirmation():
    items, bars, macd = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18, 28, 26])
    events = structure_signals(items, bars, macd)
    mmds, divergences = to_chart_signals(events, items)
    assert len(mmds) == len(events)
    assert all(m.source == 'confirmed_segment_base_v1' for m in mmds)
    assert [m.confirmed_index for m in mmds] == [e.confirmed_index for e in events]
    assert divergences[0].bc_type.value == 'qs'


def test_centre_transition_dates_match_known_indices():
    from easy_tdx.chanlun.analyser import ChanlunResult

    items, bars, _ = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18, 28, 26])
    centres = find_structural_centres(items)
    result = ChanlunResult(code='fixture', frequency='daily', klines=bars,
                           xds=items, structural_centres=centres)
    payload = result.to_dict()
    decomposition = payload['base_decomposition']
    assert decomposition['accepted_segment_count'] == len(items)
    for block in decomposition['blocks']:
        assert block['known_date'] == bars[block['known_index']].date.strftime('%Y-%m-%d')
    for centre, serialized in zip(centres, payload['structural_centres']):
        assert len(serialized['transitions']) == len(centre.transitions)
        for transition in serialized['transitions']:
            assert transition['known_date'] == bars[transition['known_index']].date.strftime(
                '%Y-%m-%d')
        assert serialized['transitions'][0]['known_date'] == serialized['formed_date']
        assert len(serialized['relation_history']) == len(centre.relation_history)
        for event in serialized['relation_history']:
            assert event['known_date'] == bars[event['known_index']].date.strftime('%Y-%m-%d')
            assert event['higher_level_confirmed'] is False


def test_confirmation_indices_are_serialized_for_exact_replay():
    from easy_tdx.chanlun.analyser import ChanlunResult

    items, bars, macd = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18, 28, 26])
    events = structure_signals(items, bars, macd)
    mmds, divergences = to_chart_signals(events, items)
    result = ChanlunResult(code='fixture', frequency='daily', klines=bars,
                           xds=items, mmds=mmds, bcs=divergences)
    payload = result.to_dict()
    assert payload['mmds'] and payload['bcs']
    for event, record in zip(divergences, payload['bcs']):
        assert record['signal_index'] == event.signal_index
        assert record['reference_index'] == event.reference_index
        assert record['curr_date'] == bars[event.signal_index].date.strftime('%Y-%m-%d')
        assert record['prev_date'] == bars[event.reference_index].date.strftime('%Y-%m-%d')
    for key in ('xds', 'mmds', 'bcs'):
        for record in payload[key]:
            index = record['confirmed_index']
            assert 0 <= index < len(bars)
            assert record['confirmed_date'] == bars[index].date.strftime('%Y-%m-%d')


def test_dual_line_indices_survive_identical_formatted_dates():
    from easy_tdx.chanlun.analyser import ChanlunResult
    from easy_tdx.chanlun.types import BC, BCType

    bars = [Kline(i, datetime(2026, 1, 1, 9, 30, i * 10), 10, 10, 11, 9, 0)
            for i in range(4)]
    event = BC(BCType.MACD, bc=True, reference_index=0, signal_index=2,
               detected_index=3, confirmed_index=3)
    record = ChanlunResult(frequency='1min', klines=bars, bcs=[event]).to_dict()['bcs'][0]
    assert record['curr_date'] == record['prev_date']  # formatted minute is ambiguous
    assert (record['reference_index'], record['signal_index'], record['confirmed_index']) == (0, 2, 3)
