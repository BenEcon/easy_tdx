"""Early-stopping structural scans validate only the links they consume."""
from copy import deepcopy
from dataclasses import asdict
from importlib import import_module

import pytest

from easy_tdx.chanlun.expansion_regrouping import _component_prefixes
from easy_tdx.chanlun.structure import (
    confirmed_segment_prefix,
    find_structural_centres,
    iter_structural_steps,
)
from tests.unit.test_chanlun_extension_recursion import oscillation
from tests.unit.test_chanlun_structure import segments


def count_anchors(monkeypatch):
    module = import_module('easy_tdx.chanlun.structure')
    original = module.extreme_index
    calls = []

    def counted(point):
        calls.append(point.k.k_index)
        return original(point)

    monkeypatch.setattr(module, 'extreme_index', counted)
    return calls


def test_first_step_does_not_validate_the_whole_unused_suffix(monkeypatch):
    items = oscillation(200)
    calls = count_anchors(monkeypatch)
    steps = iter_structural_steps(items)
    assert not calls
    for number in range(5):
        current, _, _ = next(steps)
        assert current is items[number]
        assert len(calls) == 2 * (number + 1)
    steps.close()
    assert len(calls) == 10


@pytest.mark.parametrize('reason', ['ninth_admission', 'second_centre'])
def test_disqualified_component_does_not_validate_irrelevant_suffix(monkeypatch, reason):
    items = oscillation(200)
    stop = 9
    if reason == 'second_centre':
        items = segments([14, 10, 12, 8, 20, 16, 22, 18] + [25, 18] * 100)
        stop = 7
    expected = _component_prefixes(items[:stop], 0)
    calls = count_anchors(monkeypatch)
    assert _component_prefixes(items, 0) == expected
    assert len(calls) == 2 * stop


@pytest.mark.parametrize('fault', ['unconfirmed', 'id_gap', 'direction', 'price',
                                  'future_raw', 'shared_anchor', 'confirmation_order'])
@pytest.mark.parametrize('sign', [1, -1])
def test_stream_stops_at_same_bad_link_as_batch_without_bridging(fault, sign):
    items = segments([sign * p for p in [0, 10, 2, 8, 2, 8, 2, 8, 2, 8, 2, 8]])
    for item in items:
        item.index += 31
    broken = items[5]
    if fault == 'unconfirmed':
        broken.confirmed_index = None
    elif fault == 'id_gap':
        broken.index += 1
    elif fault == 'direction':
        broken.direction = items[4].direction
    elif fault == 'price':
        broken.high = float('nan')
    elif fault == 'future_raw':
        broken.end = deepcopy(broken.end)
        broken.end.k.k_index = 999
    elif fault == 'shared_anchor':
        broken.start = deepcopy(broken.start)
        broken.start.k.k_index += 1
    else:
        broken.confirmed_index = items[4].confirmed_index - 1
    batch = confirmed_segment_prefix(items)
    assert batch == items[:5]
    assert [s for s, _, _ in iter_structural_steps(items)] == batch
    assert find_structural_centres(items) == find_structural_centres(items[:5])


def test_bad_link_stops_before_reading_later_input():
    items = oscillation(12)
    items[5].confirmed_index = None
    consumed = []

    def source():
        for pos, item in enumerate(items):
            if pos > 5:
                pytest.fail('Must not request any input after the first rejected link')
            consumed.append(pos)
            yield item

    assert [s for s, _, _ in iter_structural_steps(source())] == items[:5]
    assert consumed == list(range(6))


def test_interleaved_scans_have_no_shared_validation_or_lifecycle_state():
    left = oscillation(27)
    right = segments([14, 10, 12, 8, 20, 16, 22, 18])
    original = deepcopy((left, right))
    a, b = iter_structural_steps(left), iter_structural_steps(right)
    for position in range(len(left)):
        for stream, source in ((a, left), (b, right)):
            if position >= len(source):
                continue
            current, centre, _ = next(stream)
            assert current is source[position]
            expected = find_structural_centres(source[:position + 1])
            if centre is not None:
                assert asdict(centre) == asdict(expected[-1])
    assert list(a) == list(b) == []
    assert (left, right) == original


@pytest.mark.parametrize('after', [False, True])
def test_batch_bar_boundary_keeps_existing_eager_list_contract(after):
    items = oscillation(27)
    result = confirmed_segment_prefix(items, items[8].confirmed_index + int(after))
    assert isinstance(result, list)
    assert result == items[:8 + int(after)]
    assert all(a is b for a, b in zip(result, items))


def test_empty_stream_and_fully_consumed_stream_match_batch():
    assert list(iter_structural_steps(iter(()))) == []
    items = oscillation(81)
    assert [s for s, _, _ in iter_structural_steps(iter(items))] == confirmed_segment_prefix(items)
