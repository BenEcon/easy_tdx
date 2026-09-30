"""Approved engineering closure is causal, recursive and explicitly trend-only."""
from copy import deepcopy
from datetime import datetime, timedelta
from importlib import import_module
from random import Random

import pytest

from easy_tdx.chanlun.engineering_trends import engineering_trend_hierarchy
from easy_tdx.chanlun.types import Kline
from tests.unit.test_chanlun_signal_levels import fixture
from tests.unit.test_chanlun_structure import signal_fixture

PRICES = [40, 30, 38, 32, 37, 20, 26, 22, 25, 18, 28]


@pytest.mark.parametrize('mirror', [False, True])
def test_real_macd_closure_requires_opposite_confirmation(mirror):
    items, bars, macd = fixture(PRICES, 4, 8, mirror)
    assert not engineering_trend_hierarchy(items[:9], bars, macd)['levels']
    result = engineering_trend_hierarchy(items, bars, macd)
    trend = result['levels'][0]['types'][0]
    assert trend['source_segment_indices'] == list(range(9))
    assert trend['known_index'] == items[9].confirmed_index
    assert trend['end_index'] < trend['divergence_known_index'] < trend['known_index']
    assert trend['opposite_id'] == 'segment:9'
    assert trend['direction'] == ('up' if mirror else 'down')
    assert trend['engineering_complete'] and trend['eligible_for_trend_recursion']
    assert not trend['theory_equivalence_claim']
    assert not result['natural_type_recursion_ready']
    assert result['levels'][0]['unresolved_input_ids'] == ['segment:9']
    for count in range(len(bars) + 1):
        now = engineering_trend_hierarchy(items, bars[:count], macd)
        assert [t for lev in now['levels'] for t in lev['types']] == (
            [trend] if count > trend['known_index'] else [])


@pytest.mark.parametrize('fault', [
    'area', 'dual_line', 'missing_macd', 'invalid_reverse', 'unconfirmed'])
def test_no_false_completion_when_a_gate_fails(fault):
    items, bars, macd = fixture(PRICES, 4, 8)
    if fault == 'area':
        macd['hist'] = [-1.] * len(bars)
    elif fault == 'dual_line':
        macd['dea'] = [-1.] * len(bars)
    elif fault == 'missing_macd':
        macd = {}
    elif fault == 'invalid_reverse':
        items[-1].index += 2
    else:
        items[-1].confirmed_index = None
    assert not engineering_trend_hierarchy(items, bars, macd)['levels']


def nested_prices(depth):
    """Substitute each directed unit by a bounded nine-unit two-centre trend."""
    pattern = PRICES[:-1]
    values = pattern
    for _ in range(depth - 1):
        expanded = []
        for a, b in zip(values, values[1:]):
            expanded.extend(a + (b-a) * (p-pattern[0]) / (pattern[-1]-pattern[0])
                            for p in pattern[:-1])
        values = expanded + [values[-1]]
    # One complete opposite trend, plus its reversal, confirms the top tail.
    # Strong enough first return to exit the last lower centre instead of
    # extending it across the proposed child boundary (which correctly blocks).
    a, b = values[-1], values[-1] + 70
    opposite = [a + (b-a) * (p-pattern[0]) / (pattern[-1]-pattern[0]) for p in pattern]
    return values + opposite[1:] + [b-1]


def test_actual_two_level_recursion_and_child_provenance(monkeypatch):
    # Synthetic structure test: real MACD area/dual-line acceptance is covered above.
    module = import_module('easy_tdx.chanlun.engineering_trends')
    monkeypatch.setattr(module, 'segment_evidence', lambda *args: {'area_ratio': .5})
    prices = nested_prices(2)
    items, _, macd = signal_fixture(prices)
    bars = [Kline(i, datetime(2026, 1, 1) + timedelta(days=i),
                  prices[min(i//4, len(prices)-1)], prices[min(i//4, len(prices)-1)],
                  prices[min(i//4, len(prices)-1)], prices[min(i//4, len(prices)-1)], 0)
            for i in range(101 + 5*len(items))]
    result = engineering_trend_hierarchy(items, bars, macd)
    assert result['highest_completed_trend_level'] == 2
    first, second = result['levels']
    top = second['types'][0]
    assert top['source_segment_indices'] == list(range(81))
    assert len(top['child_ids']) == 9
    lookup = {t['id']: t for t in first['types']}
    assert [i for child in top['child_ids']
            for i in lookup[child]['source_segment_indices']] == list(range(81))
    assert top['known_index'] == lookup[top['opposite_id']]['known_index']
    assert top['known_index'] > top['divergence_known_index']
    assert second['input_count'] < first['input_count']
    # Prefix results preserve all published records, including nested evidence.
    full = [t for level in result['levels'] for t in level['types']]
    for known in sorted({t['known_index'] for t in full}):
        for count in (known, known+1):
            prefix = engineering_trend_hierarchy(items, bars[:count], macd)
            assert [t for level in prefix['levels'] for t in level['types']] == [
                t for t in full if t['known_index'] < count]


def test_chain_split_cannot_bridge_unresolved_sources():
    module = import_module('easy_tdx.chanlun.engineering_trends')
    items, _, _ = signal_fixture(PRICES)
    records = {i: {'source_segment_indices': [i]} for i in range(len(items))}
    assert [len(c) for c in module._chains([items[0], items[3], items[4]], records)] == [1, 2]


def test_payload_isolation_and_nonzero_source_ids():
    items, bars, macd = fixture(PRICES, 4, 8)
    for item in items:
        item.index += 37
    before = deepcopy(items)
    first = engineering_trend_hierarchy(items, bars, macd)
    assert first['levels'][0]['types'][0]['source_segment_indices'] == list(range(37, 46))
    first['levels'][0]['types'][0]['centres'][0]['source_unit_indices'].clear()
    second = engineering_trend_hierarchy(items, bars, macd)
    assert second['levels'][0]['types'][0]['centres'][0]['source_unit_indices']
    assert items == before


def test_serialized_dates_scope_and_trading_outputs_stay_separate():
    from easy_tdx.chanlun.analyser import ChanlunResult

    items, bars, macd = fixture(PRICES, 4, 8)
    result = ChanlunResult(xds=items, klines=bars, macd=macd)
    payload = result.to_dict()
    trend = payload['engineering_trend_hierarchy']['levels'][0]['types'][0]
    assert trend['known_date'] == result._fmt_dt(bars[145].date)
    assert trend['end_date'] == result._fmt_dt(bars[37].date)
    assert payload['structure_metadata']['engineering_trend_recursion_ready']
    assert not payload['structure_metadata']['recursive_levels_ready']
    assert not payload['mmds'] and not payload['bcs']
    trend['child_ids'].clear()
    assert result.to_dict()['engineering_trend_hierarchy']['levels'][0]['types'][0]['child_ids']


def test_equal_time_confirmation_is_atomic():
    items, bars, macd = fixture(PRICES, 4, 8)
    for item in items:
        item.confirmed_index = 180
    assert not engineering_trend_hierarchy(items, bars[:180], macd)['levels']
    trend = engineering_trend_hierarchy(items, bars[:181], macd)['levels'][0]['types'][0]
    assert trend['known_index'] == trend['divergence_known_index'] == 180


def test_later_upgrade_preserves_early_trend_but_same_batch_blocks_it(monkeypatch):
    module = import_module('easy_tdx.chanlun.engineering_trends')
    monkeypatch.setattr(module, 'segment_evidence', lambda *args: {'area_ratio': .5})
    # Start with a trend, then linger around its final centre until it upgrades.
    prices = PRICES[:-1] + [24, 19, 24, 19, 24, 19, 24, 19]
    items, bars, macd = signal_fixture(prices)
    earlier = engineering_trend_hierarchy(items[:10], bars, macd)
    assert earlier['levels']
    later = engineering_trend_hierarchy(items, bars, macd)
    assert later['levels'][0]['types'][0] == earlier['levels'][0]['types'][0]
    for item in items:
        item.confirmed_index = 190
    same_batch = engineering_trend_hierarchy(items, bars, macd)
    assert not same_batch['levels']


def test_two_levels_with_real_area_and_dual_line_checks():
    prices = nested_prices(2)
    items, _, _ = signal_fixture(prices)
    count = 101 + 5*len(items)
    bars = [Kline(i, datetime(2026, 1, 1) + timedelta(days=i),
                  prices[min(i//4, len(prices)-1)], prices[min(i//4, len(prices)-1)],
                  prices[min(i//4, len(prices)-1)], prices[min(i//4, len(prices)-1)], 0)
            for i in range(count)]
    # Controlled indicator series, not MACD calculated from a real security.
    # Both sides fade over time; each recursive leg compares its full raw span.
    values = [(1 if items[min(max(0, (i-1)//4), len(items)-1)].direction.value == 'up'
               else -1) * 10 * .995**i for i in range(count)]
    macd = {'dif': values, 'dea': [v*.8 for v in values], 'hist': [v*.4 for v in values]}
    result = engineering_trend_hierarchy(items, bars, macd)
    assert result['highest_completed_trend_level'] == 2
    assert all(0 < trend['macd_evidence']['area_ratio'] < 1
               for level in result['levels'] for trend in level['types'])


def test_random_prefixes_do_not_rewrite_published_trends(monkeypatch):
    module = import_module('easy_tdx.chanlun.engineering_trends')
    monkeypatch.setattr(module, 'segment_evidence', lambda *args: {'area_ratio': .5})
    random = Random(20260929)
    for _ in range(20):
        prices = [100.]
        for i in range(19):
            prices.append(prices[-1] + (-1 if i % 2 == 0 else 1) * random.uniform(2, 20))
        items, bars, macd = signal_fixture(prices)
        full = engineering_trend_hierarchy(items, bars, macd)
        types = [t for level in full['levels'] for t in level['types']]
        for count in range(100, 197, 5):
            now = engineering_trend_hierarchy(items, bars[:count], macd)
            assert [t for level in now['levels'] for t in level['types']] == [
                t for t in types if t['known_index'] < count]
