"""Local restart cannot downgrade the tail of a proven extending centre."""
from copy import deepcopy
from importlib import import_module

import pytest

from easy_tdx.chanlun.engineering_trends import engineering_trend_hierarchy
from easy_tdx.chanlun.extension_recursion import extension_hierarchy, promoted_member_times
from tests.unit.test_chanlun_signal_levels import fixture
from tests.unit.test_chanlun_structure import segments

EXTENDED = [40, 30, 38, 32, 38, 32, 38, 32, 38, 32, 38, 32, 38, 32,
            37, 20, 26, 22, 25, 18, 28]


@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('offset', [0, 37])
def test_real_macd_cannot_complete_trend_from_later_promoted_members(mirror, offset):
    items, bars, macd = fixture(EXTENDED, 14, 18, mirror)
    for item in items:
        item.index += offset
    proof = extension_hierarchy(items)['proofs'][0]
    assert proof['source_segment_indices'] == list(range(offset, offset+9))
    # The old local restart used 10..18, entirely after the nine proof members.
    assert proof['source_segment_indices'][-1] < offset+10
    result = engineering_trend_hierarchy(items, bars, macd)
    assert not result['levels']
    assert not result['structure_layers']


def test_later_members_wait_for_admission_and_earlier_members_wait_for_promotion():
    items = segments([0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 4, 12, 4])
    times = promoted_member_times(items)
    assert times[0] == times[8] == 145  # Ninth member admitted on failed return.
    assert items[0].confirmed_index == 100
    assert items[10].confirmed_index == 150
    assert times[10] == 155  # Later pending departure also waits for its return.
    assert 10 not in promoted_member_times(items[:11])
    assert 10 not in promoted_member_times(items, bar_count=155)
    assert promoted_member_times(items, bar_count=156)[10] == 155
    for count in range(100, 162):
        assert promoted_member_times(items, bar_count=count) == {
            index: known for index, known in times.items() if known < count}


def test_external_departure_and_successful_return_are_not_promoted_members():
    items = segments([0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 4, 14, 10])
    times = promoted_member_times(items)
    assert set(times) == set(range(10))
    assert 10 not in times and 11 not in times


def test_same_time_batch_and_invalid_suffix_are_not_partial_evidence():
    items = segments([0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 4, 12, 4])
    for item in items:
        item.confirmed_index = 190
    assert not promoted_member_times(items, bar_count=190)
    assert set(promoted_member_times(items, bar_count=191).values()) == {190}
    items[9].confirmed_index = None  # Waiting ninth member cannot be admitted.
    assert not promoted_member_times(items)


def test_member_count_without_geometric_upgrade_proof_does_not_create_guard(monkeypatch):
    module = import_module('easy_tdx.chanlun.extension_recursion')
    items = segments(EXTENDED)
    monkeypatch.setattr(module, 'centre_extension_proof', lambda *_: None)
    assert not module.promoted_member_times(items)


def test_guard_results_do_not_mutate_source_or_share_state():
    items = segments(EXTENDED)
    before = deepcopy(items)
    first = promoted_member_times(items)
    assert 13 in first  # Beyond the first nine proof sources.
    first.clear()
    assert promoted_member_times(items)
    assert items == before


@pytest.mark.parametrize('mirror', [False, True])
def test_rejected_trend_stays_absent_at_every_history_prefix(mirror):
    items, bars, macd = fixture(EXTENDED, 14, 18, mirror)
    for count in range(130, 201):
        result = engineering_trend_hierarchy(items, bars[:count], macd)
        assert not result['levels']
        assert result['rule'] == 'approved_macd_reverse_v2'
        assert result['promotion_scope'] == 'all_admitted_members_at_candidate_confirmation'


def test_unpromoted_independent_trend_after_exit_can_still_complete():
    # A later independent down trend starts with the departure, not the promoted
    # members. Promotion is not a blanket ban on the entire remaining history.
    prices = EXTENDED[:-6] + [20, 26, 22, 25, 10, 16, 12, 15, 8, 18]
    items, bars, macd = fixture(prices, 18, 22)
    # The fixture provides 200 bars: extend its harmless flat tail through all
    # segment confirmations while preserving the original indicator evidence.
    from dataclasses import replace
    from datetime import timedelta
    bars += [replace(bars[-1], index=i, date=bars[-1].date + timedelta(days=i-199))
             for i in range(200, 230)]
    macd = {key: values + [values[-1]] * 30 for key, values in macd.items()}
    result = engineering_trend_hierarchy(items, bars, macd)
    trend = result['levels'][0]['types'][0]
    assert trend['source_segment_indices'] == list(range(14, 23))
    assert trend['known_index'] == items[23].confirmed_index
