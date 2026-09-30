"""Reuse geometry inside one analysis, never mutable ownership or old queries."""
import gc
import weakref
from copy import deepcopy
from dataclasses import replace
from importlib import import_module

import pytest

from easy_tdx.chanlun.nested_recursion import _NestedScanCache, nested_candidates
from easy_tdx.chanlun.types import Direction
from tests.unit.test_chanlun_layered_ownership import PRICES
from tests.unit.test_chanlun_nested_ownership import current, records_for, run, triple_fixture
from tests.unit.test_chanlun_signal_levels import fixture


def count_scans(monkeypatch):
    module = import_module('easy_tdx.chanlun.nested_recursion')
    original, calls = module._scan, []

    def scan(*args):
        calls.append(len(args[0]))
        return original(*args)

    monkeypatch.setattr(module, '_scan', scan)
    return calls


def test_equivalent_adapters_hit_cache_but_return_detached_evidence(monkeypatch):
    items, bars, macd = fixture(PRICES, 10, 14)
    inputs = deepcopy((items, bars, macd))
    calls = count_scans(monkeypatch)
    cache = _NestedScanCache(bars, macd)
    first = cache.scan(items)
    second = cache.scan([replace(item) for item in items])
    assert first == second and calls == [len(items)]
    first[0][next(iter(first[0]))][0]['sources'].clear()
    first[1][0]['macd_evidence'].clear()
    assert cache.scan(items) == second
    assert calls == [len(items)]
    assert (items, bars, macd) == inputs


@pytest.mark.parametrize('field', ['index', 'confirmed_index', 'direction', 'low', 'high',
                                  'start', 'end'])
def test_every_adapter_dependency_changes_the_key(monkeypatch, field):
    module = import_module('easy_tdx.chanlun.nested_recursion')
    calls = []
    # This test isolates the key, not the validity of modified geometric inputs.
    monkeypatch.setattr(module, '_scan', lambda *args: (calls.append(1) or {}, []))
    items, bars, macd = fixture(PRICES, 10, 14)
    cache = _NestedScanCache(bars, macd)
    cache.scan(items)
    old = getattr(items[0], field)
    value = (replace(old, val=old.val+1) if field in ('start', 'end')
             else Direction.UP if field == 'direction' else old+1)
    changed = [replace(items[0], **{field: value}), *items[1:]]
    cache.scan(changed)
    cache.scan(changed)
    assert len(calls) == 2


def test_new_series_gets_a_new_cache_even_with_identical_adapter_objects(monkeypatch):
    items, bars, macd = fixture(PRICES, 10, 14)
    calls = count_scans(monkeypatch)
    first = _NestedScanCache(bars, macd).scan(items)
    changed = {key: [0.] * len(values) for key, values in macd.items()}
    second = _NestedScanCache(bars, changed).scan(items)
    assert first[1] and not second[1]
    assert calls == [len(items), len(items)]


def test_owner_ids_transfers_and_decisions_are_recomputed_outside_cache(monkeypatch):
    items, bars, macd = fixture(PRICES, 10, 14)
    calls = count_scans(monkeypatch)
    cache = _NestedScanCache(bars, macd)
    outputs = []
    for parent in ('first', 'second'):
        records = records_for(items)
        for record in records.values():
            record['id'] = f"{parent}:{record['id']}"
        result = nested_candidates(items, bars, macd, records, 1, parent, scan_cache=cache)
        uncached = nested_candidates(items, bars, macd, records_for(items), 1, parent)
        assert result[0] == uncached[0]
        assert result[1][0]['parent_owner_id'] == parent
        assert all(identity.startswith(parent+':') for identity in result[1][0]['source_unit_ids'])
        assert all(record['ownership_transfers'][0]['from_owner_id'] == parent
                   for record in records.values() if record.get('ownership_transfers'))
        outputs.append(result)
    assert len(calls) == 3  # One shared geometry scan plus two independent controls.
    assert outputs[0][0][0]['current_owner_id'] != outputs[1][0][0]['current_owner_id']


@pytest.mark.parametrize('mirror', [False, True])
def test_full_three_level_version_history_is_identical_without_reuse(monkeypatch, mirror):
    module = import_module('easy_tdx.chanlun.nested_recursion')
    items, bars, macd = triple_fixture(mirror)
    cached = run(items, bars, macd)
    with monkeypatch.context() as independent:
        independent.setattr(_NestedScanCache, 'scan',
                            lambda self, chain: module._scan(chain, self.bars, self.macd))
        uncached = run(items, bars, macd)
    assert cached == uncached
    assert len(cached['versions']) == 429
    owner = current(cached)[0]
    assert [(level['level'], len(level['types'])) for level in owner['levels']] == [
        (1, 86), (2, 16), (3, 1)]
    assert all(v['highest_completed_internal_level'] < 3
               for v in cached['versions'] if v['known_index'] < 2280)
    assert owner['levels'][2]['types'][0]['known_index'] == 2280
    # History snapshots must not alias each other after geometry reuse.
    shared_source = owner['levels'][0]['types'][0]['source_segment_indices']
    earlier = next(v for v in cached['versions'][:-1] if v['levels'] and
                   v['levels'][0]['types'][0]['source_segment_indices'] == shared_source)
    historical = deepcopy(earlier)
    owner['levels'][0]['types'][0]['macd_evidence'].clear()
    assert earlier == historical
    assert not cached['natural_type_recursion_ready']


def test_cache_lifetime_ends_with_analysis_and_no_entries_survive(monkeypatch):
    module = import_module('easy_tdx.chanlun.nested_recursion')
    references = []

    class ObservedCache(_NestedScanCache):
        def __init__(self, bars, macd):
            super().__init__(bars, macd)
            references.append(weakref.ref(self))

    monkeypatch.setattr(module, '_NestedScanCache', ObservedCache)
    items, bars, macd = fixture(PRICES, 10, 14)
    run(items, bars, macd)
    gc.collect()
    assert len(references) == 1 and references[0]() is None
