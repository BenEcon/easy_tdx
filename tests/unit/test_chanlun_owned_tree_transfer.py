"""Removing a redundant tree copy must retain all ownership isolation boundaries."""
from copy import deepcopy
from importlib import import_module

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.engineering_trends import engineering_movement_hierarchy
from easy_tdx.chanlun.layered_ownership import layered_movement_ownership
from tests.unit.test_chanlun_nested_ownership import nested_fixture, triple_fixture


def mutable_nodes(value):
    """Identity audit, not equality: detect hidden sharing even before mutation."""
    found = set()

    def visit(item):
        if not isinstance(item, (dict, list, tuple)) or id(item) in found:
            return
        if isinstance(item, (dict, list)):
            found.add(id(item))
        for child in item.values() if isinstance(item, dict) else item:
            visit(child)

    visit(value)
    return found


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize('mirror', [False, True])
def test_transferred_revisions_are_disjoint_from_seeds_cache_and_each_other(
        monkeypatch, nested, mirror):
    module = import_module('easy_tdx.chanlun.layered_ownership')
    original = module._hierarchy
    items, bars, macd = nested_fixture(mirror, 37)
    flat = engineering_movement_hierarchy(items, bars, macd)
    inputs = deepcopy((items, bars, macd, flat))
    trees, occupied = [], set()

    def observe(*args, **kwargs):
        tree = original(*args, **kwargs)
        nodes = mutable_nodes(tree)
        assert not nodes.intersection(mutable_nodes(kwargs['internal_seed']))
        cache = kwargs.get('scan_cache')
        if cache is not None:
            assert not nodes.intersection(mutable_nodes(cache.entries))
        assert not nodes.intersection(occupied)
        occupied.update(nodes)
        # Retain the actual trees: recycling Python IDs must not make this
        # independence check fail for unrelated, already-released objects.
        trees.append(tree)
        return tree

    monkeypatch.setattr(module, '_hierarchy', observe)
    output = layered_movement_ownership(items, bars, macd, flat, nested=nested)
    assert len(trees) == len(output['versions']) == 78
    assert not mutable_nodes(output).intersection(occupied)
    assert (items, bars, macd, flat) == inputs
    saved = deepcopy(output)
    for tree in trees:
        tree['levels'].clear()
        tree['structure_layers'].clear()
    assert output == saved  # Final public output boundary remains a deep copy.
    prior = deepcopy(output['versions'][:-1])
    latest = output['versions'][-1]
    latest['levels'][0]['types'][0]['macd_evidence'].clear()
    latest['member_admissions'].clear()
    assert output['versions'][:-1] == prior


@pytest.mark.parametrize('history', ['full', 'summary'])
@pytest.mark.parametrize('mirror', [False, True])
def test_all_three_level_revisions_equal_the_original_extra_copy_path(
        monkeypatch, history, mirror):
    module = import_module('easy_tdx.chanlun.layered_ownership')
    original = module._hierarchy
    items, bars, macd = triple_fixture(mirror)
    flat = engineering_movement_hierarchy(items, bars, macd)
    transferred = layered_movement_ownership(
        items, bars, macd, flat, nested=True, ownership_history=history)
    monkeypatch.setattr(module, '_hierarchy', lambda *a, **kw: deepcopy(original(*a, **kw)))
    copied = layered_movement_ownership(
        items, bars, macd, flat, nested=True, ownership_history=history)
    assert transferred == copied
    history_items = (transferred['versions'] if history == 'full'
                     else transferred['history_summaries'])
    assert len(history_items) == 429
    assert transferred['versions'][-1]['highest_completed_internal_level'] == 3
    assert not transferred['natural_type_recursion_ready']


@pytest.mark.parametrize('history', ['full', 'summary'])
@pytest.mark.parametrize('mirror', [False, True])
def test_dated_api_prefixes_are_identical_to_original_copy_boundary(
        monkeypatch, history, mirror):
    module = import_module('easy_tdx.chanlun.layered_ownership')
    original = module._hierarchy
    items, bars, macd = nested_fixture(mirror, 37)
    snapshots = []
    for count in (400, 525, 526, len(bars)):
        result = ChanlunResult(xds=items, klines=bars[:count], macd=macd)
        direct = result.to_dict(ownership_history=history)
        with monkeypatch.context() as control:
            control.setattr(module, '_hierarchy', lambda *a, **kw: deepcopy(original(*a, **kw)))
            assert direct == result.to_dict(ownership_history=history)
        assert direct == result.to_dict(ownership_history=history)
        snapshots.append(direct)
    saved = deepcopy(snapshots[:-1])
    snapshots[-1]['recursive_movement_ownership']['versions'][-1]['levels'].clear()
    assert snapshots[:-1] == saved
