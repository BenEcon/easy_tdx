"""Late ownership cannot erase a disjoint, already completed internal type."""
from copy import deepcopy
from importlib import import_module
from random import Random

import pytest

from easy_tdx.chanlun.engineering_trends import (
    _select_owned_candidates,
    engineering_movement_hierarchy,
)
from easy_tdx.chanlun.layered_ownership import layered_movement_ownership
from easy_tdx.chanlun.ownership_history import summarize_ownership_history
from tests.unit.test_chanlun_engineering_movements import mixed_fixture


def delayed_left_claims(monkeypatch, items, offset):
    module = import_module('easy_tdx.chanlun.layered_ownership')
    original = module._claim_events
    # Isolate admission timing; local geometry, MACD and reverse confirmation
    # remain real. The older right domain later admits the earlier left span.
    events = {
        295: [{'key': 'right', 'kind': 'promotion',
               'sources': list(range(offset + 5, offset + 39))}],
        310: [{'key': 'left-expansion', 'kind': 'expansion',
               'sources': list(range(offset, offset + 6))}],
    }

    def claims(chain):
        if chain and chain[0] is items[0]:
            return deepcopy({k: v for k, v in events.items() if k <= chain[-1].confirmed_index})
        return original(chain)

    monkeypatch.setattr(module, '_claim_events', claims)


@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('offset', [0, 37])
def test_late_left_admission_preserves_disjoint_types_without_backdating_parent(
        monkeypatch, mirror, offset):
    items, bars, macd, _ = mixed_fixture(mirror)
    for item in items:
        item.index += offset
    inputs = deepcopy((items, bars, macd))
    flat = engineering_movement_hierarchy(items, bars, macd)
    delayed_left_claims(monkeypatch, items, offset)

    def run(count, **kwargs):
        return layered_movement_ownership(items, bars[:count], macd, flat, **kwargs)

    before = run(310, nested=True)
    result = run(311, nested=True)
    owner = result['versions'][-1]
    records = owner['levels'][0]['types']
    expected = [(0, 4), (5, 13), (14, 18), (19, 27), (28, 32)]
    assert [(r['source_segment_indices'][0] - offset,
             r['source_segment_indices'][-1] - offset) for r in records] == expected
    left = records[0]
    assert left['original_known_index'] == 125
    assert left['known_index'] == left['ownership_known_index'] == 310
    assert all(r['known_index'] == 295 for r in records[1:])
    assert not any(r['source_segment_indices'][0] == offset
                   for r in before['versions'][-1]['levels'][0]['types'])
    assert result['versions'][:-1] == before['versions']
    assert owner['highest_completed_internal_level'] == 1
    # A late left record followed by earlier right records is not a valid
    # time-ordered higher chain, even though both can remain as evidence.
    assert [len(c['input_ids']) for c in owner['structure_layers'][0]['chains']] == [1, 4]
    assert len(owner['frontier_ids']) == 5
    covered = [i for r in records for i in r['source_segment_indices']]
    assert len(covered) == len(set(covered)) == 33
    assert owner['unresolved_segment_indices'] == list(range(offset + 33, offset + 39))
    assert not result['natural_type_recursion_ready']
    assert all(not r['eligible_for_external_recursion'] for r in records)
    assert run(311, nested=True, ownership_history='summary') == summarize_ownership_history(result)
    # Preserve the older first-generation explanation for comparison.
    old = run(311)['versions'][-1]['levels'][0]['types']
    assert old[0]['source_segment_indices'][0] == offset + 5
    assert (items, bars, macd) == inputs


def priority(candidate):
    return (candidate['known_index'], candidate['start_unit_index'], candidate['end_unit_index'])


def candidates_from(specs):
    return [{'id': str(i), 'known_index': known, 'start_unit_index': start, 'end_unit_index': end}
            for i, (known, start, end) in enumerate(specs)]


@pytest.mark.parametrize('specs,expected', [
    ([], []),
    ([(20, 0, 4), (10, 5, 9)], ['0', '1']),  # Late left, adjacent sources.
    ([(10, 5, 9), (20, 0, 4), (15, 10, 14)], ['1', '0', '2']),
    ([(10, 5, 9), (20, 0, 5), (20, 9, 14)], ['0']),  # Shared source is overlap.
    ([(10, 5, 9), (20, 0, 14)], ['0']),  # Enclosing later span loses.
    ([(10, 0, 14), (20, 5, 9)], ['0']),  # Enclosed later span loses.
    ([(10, 5, 9), (10, 0, 6)], ['1']),  # Same time: earliest start wins.
    ([(10, 0, 9), (10, 0, 4)], ['1']),  # Same start: shortest end wins.
    ([(10, 0, 4), (10, 0, 4)], ['0']),  # Exact ties retain stable input priority.
])
def test_actual_overlap_and_existing_priority_are_respected(specs, expected):
    candidates = candidates_from(specs)
    before = deepcopy(candidates)
    assert [c['id'] for c in _select_owned_candidates(candidates)] == expected
    assert candidates == before


def test_interval_selection_matches_independent_source_set_oracle():
    rng = Random(51)
    for _ in range(200):
        specs = {(rng.randrange(100, 200), start, start + rng.randrange(1, 12))
                 for start in (rng.randrange(0, 120) for _ in range(60))}
        candidates = candidates_from(sorted(specs))
        used, expected = set(), []
        for candidate in sorted(candidates, key=priority):
            sources = set(range(candidate['start_unit_index'], candidate['end_unit_index'] + 1))
            if not sources.intersection(used):
                used.update(sources)
                expected.append(candidate)
        expected.sort(key=lambda c: c['start_unit_index'])
        rng.shuffle(candidates)
        before = deepcopy(candidates)
        assert _select_owned_candidates(candidates) == expected
        assert candidates == before
        # Every rejection has an actual overlap with a higher-priority winner.
        for rejected in (c for c in candidates if c not in expected):
            assert any(priority(winner) < priority(rejected)
                       and max(winner['start_unit_index'], rejected['start_unit_index'])
                       <= min(winner['end_unit_index'], rejected['end_unit_index'])
                       for winner in expected)


def test_spatially_monotonic_availability_keeps_previous_selection():
    rng = Random(510)
    for _ in range(100):
        candidates = candidates_from([(100 + start, start, start + rng.randrange(1, 12))
                                      for start in range(50)])
        rng.shuffle(candidates)
        last_end, previous = -1, []
        for candidate in sorted(candidates, key=priority):
            if candidate['start_unit_index'] > last_end:
                previous.append(candidate)
                last_end = candidate['end_unit_index']
        assert _select_owned_candidates(candidates) == previous


def test_api_dates_preserve_original_completion_and_delayed_availability(monkeypatch):
    from easy_tdx.chanlun.analyser import ChanlunResult

    items, bars, macd, _ = mixed_fixture()
    delayed_left_claims(monkeypatch, items, 0)
    result = ChanlunResult(xds=items, klines=bars, macd=macd)
    payload = result.to_dict(ownership_history='summary')
    recursive = payload['recursive_movement_ownership']
    left = recursive['versions'][0]['levels'][0]['types'][0]
    assert left['source_segment_indices'] == list(range(5))
    assert left['original_known_date'] == result._fmt_dt(bars[125].date)
    assert left['known_date'] == left['ownership_known_date'] == result._fmt_dt(bars[310].date)
    assert not payload['structure_metadata']['recursive_levels_ready']
    assert not payload['mmds'] and not payload['bcs']
