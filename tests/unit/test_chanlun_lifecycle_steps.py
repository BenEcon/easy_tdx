"""Causal single-pass lifecycle steps and immutable signal evidence."""
from copy import deepcopy
from dataclasses import asdict
from random import Random

import pytest

from easy_tdx.chanlun.structure import (
    confirmed_segment_prefix,
    find_structural_centres,
    iter_structural_steps,
)
from easy_tdx.chanlun.structure_signals import structure_signals
from tests.unit.test_chanlun_structure import segments, signal_fixture


@pytest.mark.parametrize('sign', [1, -1])
@pytest.mark.parametrize('offset', [0, 17])
def test_each_step_matches_only_the_observable_prefix(sign, offset):
    random = Random(2302)
    for _ in range(25):
        prices = [100]
        for i in range(24):
            prices.append(prices[-1] + (1 if i % 2 == 0 else -1) * random.randint(1, 20))
        items = segments([sign * p for p in prices])
        for item in items:
            item.index += offset
        original = deepcopy(items)
        collected = []
        for count, (current, active, prior) in enumerate(iter_structural_steps(items), 1):
            assert current is items[count - 1]
            if active is not None and (not collected or collected[-1] is not active):
                collected.append(active)
            expected = find_structural_centres(items[:count])
            # Compare immediately: iterator centre references deliberately remain live.
            assert [asdict(c) for c in collected] == [asdict(c) for c in expected]
            assert (active is None
                    or active.transitions[-1]['known_index'] <= current.confirmed_index)
            assert prior is None or prior.state == 'exited'
        assert len(items) == count
        assert items == original


def test_seed_gaps_exit_and_return_reuse_are_visible_at_correct_steps():
    # First three ranges only touch at 10, so the rolling seed must advance.
    items = segments([10, 12, 8, 10, 7, 9])
    snapshots = [(s.index, asdict(c) if c else None, asdict(p) if p else None)
                 for s, c, p in iter_structural_steps(items)]
    assert snapshots[0][1] is None and snapshots[1][1] is None
    assert snapshots[2][1] is None
    assert snapshots[3][1]['state'] == 'formed'
    assert snapshots[3][1]['seed_segments'] == [1, 2, 3]
    assert snapshots[4][1]['state'] == 'extended'
    # Separate fixture: successful return becomes the next seed, never the departure.
    items = segments([14, 10, 12, 8, 20, 16, 22, 18])
    snapshots = [(s.index, asdict(c) if c else None, asdict(p) if p else None)
                 for s, c, p in iter_structural_steps(items)]
    assert snapshots[3][1]['state'] == 'departed'
    assert snapshots[4][1]['state'] == 'exited'
    assert snapshots[5][1] is None
    assert snapshots[5][2]['state'] == 'exited'
    assert snapshots[6][1]['seed_segments'] == [4, 5, 6]
    assert snapshots[6][1]['index'] == 1


def test_failed_departure_can_immediately_become_opposite_departure():
    items = segments([8, 12, 10, 14, 7, 15, 11])
    snapshots = [asdict(c) if c else None for _, c, _ in iter_structural_steps(items)]
    failed = snapshots[4]
    assert failed['state'] == 'departed'
    assert failed['departure_direction'] == 'up'
    assert failed['departure_segment'] == 4
    assert failed['member_segments'] == [0, 1, 2, 3]
    assert failed['member_admissions'][-1]['reason'] == 'failed_departure_return'
    assert failed['member_admissions'][-1]['admitted_index'] == items[4].confirmed_index
    assert snapshots[5]['state'] == 'extended'
    assert snapshots[5]['member_segments'] == list(range(6))


@pytest.mark.parametrize('invalid', ['missing', 'disconnected', 'confirmation_order'])
def test_iterator_stops_at_invalid_link_without_skipping_it(invalid):
    items = segments([14, 10, 12, 8, 20, 16, 22, 18])
    if invalid == 'missing':
        items[4].confirmed_index = None
    elif invalid == 'disconnected':
        items[4].start = items[3].start
    else:
        items[4].confirmed_index = items[3].confirmed_index - 1
    steps = list(iter_structural_steps(items))
    assert [s.index for s, _, _ in steps] == [0, 1, 2, 3]
    assert steps[-1][1].state == 'departed'
    assert steps[-1][1].exited_index is None


def test_signal_evidence_and_first_return_do_not_drift_after_continuation():
    items, bars, macd = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18, 28, 26,
                                      30, 24, 31, 23, 32])
    final = structure_signals(items, bars, macd)
    assert {'1buy', '2buy', '3buy'} <= {s.signal_type for s in final}
    first = next(s for s in final if s.signal_type == '1buy')
    seconds = [s for s in final if s.signal_type == '2buy'
               and s.evidence['first_segment'] == first.segment_index]
    assert len(seconds) == 1
    assert seconds[0].segment_index == first.segment_index + 2
    for count in range(len(items) + 1):
        cutoff = items[count - 1].confirmed_index if count else -1
        prefix = structure_signals(items[:count], bars, macd)
        assert prefix == [s for s in final if s.confirmed_index <= cutoff]
    before = first.confirmed_index
    assert not any(s.signal_type == '1buy' for s in structure_signals(items, bars[:before], macd))
    assert first in structure_signals(items, bars[:before + 1], macd)


def test_empty_and_bar_limited_steps():
    assert list(iter_structural_steps([])) == []
    items = segments([8, 12, 10, 14])
    before = confirmed_segment_prefix(items, items[2].confirmed_index)
    assert all(c is None for _, c, _ in iter_structural_steps(before))
    at = confirmed_segment_prefix(items, items[2].confirmed_index + 1)
    assert list(iter_structural_steps(at))[-1][1].state == 'formed'


def test_signal_scan_does_not_rebuild_already_processed_lifecycle(monkeypatch):
    import easy_tdx.chanlun.structure as structure

    items, bars, macd = signal_fixture([0, 10] + [2, 8] * 7 + [2])
    transitions = []
    original = structure._transition

    def record(centre, state, segment):
        transitions.append(segment.index)
        original(centre, state, segment)

    monkeypatch.setattr(structure, '_transition', record)
    structure_signals(items, bars, macd)
    assert transitions == list(range(2, len(items)))
