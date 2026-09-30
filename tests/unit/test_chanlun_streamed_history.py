"""Summary delivery must not first retain every full historical revision."""
import weakref
from copy import deepcopy
from importlib import import_module

import pytest

from easy_tdx.chanlun.engineering_trends import engineering_movement_hierarchy
from easy_tdx.chanlun.layered_ownership import layered_movement_ownership
from easy_tdx.chanlun.ownership_history import summarize_ownership_history
from tests.unit.test_chanlun_engineering_movements import CONSOLIDATION
from tests.unit.test_chanlun_nested_ownership import current, nested_fixture, triple_fixture
from tests.unit.test_chanlun_owner_witness import install_base_claims
from tests.unit.test_chanlun_signal_levels import fixture


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize('mirror', [False, True])
def test_streamed_delivery_matches_full_projection_at_each_prefix(nested, mirror):
    items, bars, macd = nested_fixture(mirror)
    inputs = deepcopy((items, bars, macd))
    for count in (140, 400, 525, 526, len(bars)):
        visible = bars[:count]
        flat = engineering_movement_hierarchy(items, visible, macd)
        full = layered_movement_ownership(items, visible, macd, flat, nested=nested)
        summary = layered_movement_ownership(
            items, visible, macd, flat, nested=nested, ownership_history='summary')
        assert summary == summarize_ownership_history(full)
        assert all(v['known_index'] < count for v in summary['history_summaries'])
        assert all('_signature' not in v for v in summary['versions'])
        if summary['versions']:
            expected = deepcopy(summary['history_summaries'])
            summary['versions'][0]['source_segment_indices'].clear()
            assert summary['history_summaries'] == expected
    assert (items, bars, macd) == inputs


@pytest.mark.parametrize('nested', [False, True])
def test_completed_detail_trees_are_released_instead_of_accumulating(monkeypatch, nested):
    module = import_module('easy_tdx.chanlun.layered_ownership')
    original = module._hierarchy
    items, bars, macd = nested_fixture()
    flat = engineering_movement_hierarchy(items, bars, macd)
    counts = {}

    class TrackedLevels(list):
        pass

    for mode in ('full', 'summary'):
        references, living_counts = [], []

        def observe(*args, **kwargs):
            result = original(*args, **kwargs)
            result['levels'] = TrackedLevels(result['levels'])
            references.append(weakref.ref(result['levels']))
            living_counts.append(sum(ref() is not None for ref in references))
            return result

        with monkeypatch.context() as watching:
            watching.setattr(module, '_hierarchy', observe)
            result = layered_movement_ownership(
                items, bars, macd, flat, nested=nested, ownership_history=mode)
        counts[mode] = max(living_counts)
        history = result['versions'] if mode == 'full' else result['history_summaries']
        assert len(history) == len(references) == 78
        assert all(ref() is None for ref in references)  # Output is detached too.
    assert counts['full'] == 78
    assert counts['summary'] <= 3


@pytest.mark.parametrize('mirror', [False, True])
def test_streaming_keeps_witness_migration_and_merge_history(monkeypatch, mirror):
    items, bars, macd = fixture(CONSOLIDATION + [22, 27, 21], 0, 4, mirror)
    install_base_claims(monkeypatch, items)
    snapshots = []
    for count in (126, 136, 141):
        flat = engineering_movement_hierarchy(items, bars[:count], macd)
        full = layered_movement_ownership(items, bars[:count], macd, flat, nested=True)
        compact = layered_movement_ownership(items, bars[:count], macd, flat,
                                             nested=True, ownership_history='summary')
        assert compact == summarize_ownership_history(full)
        snapshots.append(compact)
    assert len(snapshots[1]['versions']) == 2
    assert snapshots[1]['versions'][0]['blocked_ownership_candidates']
    merged = snapshots[2]['versions'][0]
    assert len(merged['previous_owner_ids']) == 2
    assert merged['levels'][0]['types'][0]['known_index'] == 140
    assert snapshots[2]['history_summaries'][:len(snapshots[1]['history_summaries'])] == (
        snapshots[1]['history_summaries'])


@pytest.mark.parametrize('nested', [False, True])
def test_updated_left_owner_keeps_current_details_in_historical_creation_order(monkeypatch, nested):
    items, bars, macd = fixture(CONSOLIDATION + [22, 27, 21], 0, 4)
    install_base_claims(monkeypatch, items)
    module = import_module('easy_tdx.chanlun.layered_ownership')
    original = module._claim_events

    def claims(chain):
        events = original(chain)
        if chain and chain[0] is items[0] and 140 in events:
            # Add an overlapping claim in the left owner, without merging the
            # unchanged right owner. Spatial and creation order now differ.
            events[140] = [{'key': 'left-update', 'kind': 'expansion', 'sources': [1, 2, 3]}]
        return events

    monkeypatch.setattr(module, '_claim_events', claims)
    flat = engineering_movement_hierarchy(items, bars, macd)
    full = layered_movement_ownership(items, bars, macd, flat, nested=nested)
    summary = layered_movement_ownership(
        items, bars, macd, flat, nested=nested, ownership_history='summary')
    assert [v['known_index'] for v in summarize_ownership_history(full)['versions']] == [135, 140]
    assert summary == summarize_ownership_history(full)
    assert summary['current_owner_ids'] == [v['id'] for v in reversed(summary['versions'])]


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize('invalid_tail', [False, True])
def test_empty_or_no_owner_stream_has_explicit_identical_metadata(nested, invalid_tail):
    items, bars, macd = fixture(CONSOLIDATION, 0, 4)
    if invalid_tail:
        items[-1].confirmed_index = None
    else:
        items = []
    flat = engineering_movement_hierarchy(items, bars, macd)
    full = layered_movement_ownership(items, bars, macd, flat, nested=nested)
    summary = layered_movement_ownership(
        items, bars, macd, flat, nested=nested, ownership_history='summary')
    assert summary == summarize_ownership_history(full)
    assert summary['versions'] == summary['history_summaries'] == []


def test_unknown_stream_mode_does_not_silently_drop_history():
    with pytest.raises(ValueError, match='ownership_history'):
        layered_movement_ownership([], [], {}, {}, ownership_history='truncate')


def test_all_429_addresses_and_current_m3_equal_full_export_projection():
    items, bars, macd = triple_fixture()
    flat = engineering_movement_hierarchy(items, bars, macd)
    full = layered_movement_ownership(items, bars, macd, flat, nested=True)
    summary = layered_movement_ownership(
        items, bars, macd, flat, nested=True, ownership_history='summary')
    assert summary == summarize_ownership_history(full)
    assert len(summary['history_summaries']) == 429
    owner = current(summary)[0]
    assert owner['highest_completed_internal_level'] == 3
    assert owner['levels'][2]['types'][0]['known_index'] == 2280
    assert not summary['natural_type_recursion_ready']
