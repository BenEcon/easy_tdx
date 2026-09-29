"""Raw extreme identity agrees across geometry, indicators and API output."""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.anchors import extreme_date, extreme_index
from easy_tdx.chanlun.decomposition import decompose_base_chain
from easy_tdx.chanlun.divergence_signals import extreme_index as signal_extreme_index
from easy_tdx.chanlun.expansion_regrouping import expansion_regrouping
from easy_tdx.chanlun.extension_recursion import _endpoint_index, extension_hierarchy
from easy_tdx.chanlun.structure import find_structural_centres
from easy_tdx.chanlun.structure_signals import structure_signals, to_chart_signals
from easy_tdx.chanlun.types import FXType, Kline
from tests.unit.test_chanlun_expansion_regrouping import LATER_VALID_PRICES
from tests.unit.test_chanlun_extension_recursion import oscillation
from tests.unit.test_chanlun_structure import segments, signal_fixture


def bars_for(items):
    return [Kline(i, datetime(2026, 1, 1) + timedelta(minutes=i), 10, 10, 150, -150, 1)
            for i in range(items[-1].confirmed_index + 1)]


def attach_extreme(point, bars, delta=5e-7):
    """Earlier actual extreme, followed by a nearby but distinct price."""
    last = point.k.k_index
    for index, difference in ((last - 1, 0), (last, delta)):
        bottom = point.fx_type == FXType.DI
        low = point.val + difference if bottom else point.val - 1
        high = point.val + 1 if bottom else point.val - difference
        bars[index] = Kline(index, bars[index].date, (low + high) / 2,
                           (low + high) / 2, high, low, 1)
    point.k.klines = bars[last - 1:last + 1]
    point.k.date = bars[last].date
    return last - 1


@pytest.mark.parametrize('kind', [FXType.DI, FXType.DING])
@pytest.mark.parametrize('delta,use_last', [(5e-7, False), (1e-10, True), (0, True)])
def test_directional_tolerance_and_last_equal_extreme_are_shared(kind, delta, use_last):
    items = segments([8, 12, 10, 14])
    point = items[0].start
    point.fx_type = kind
    bars = bars_for(items)
    first = attach_extreme(point, bars, delta)
    original = deepcopy(point)
    expected = point.k.k_index if use_last else first
    assert extreme_index(point) == signal_extreme_index(point) == _endpoint_index(point) == expected
    assert extreme_date(point) == ChanlunResult._fx_dt(point) == bars[expected].date
    assert point == original


@pytest.mark.parametrize('kind', [FXType.DI, FXType.DING])
@pytest.mark.parametrize('missing', [True, False])
def test_source_missing_or_unmatched_uses_merged_fallback(kind, missing):
    items = segments([8, 12, 10, 14])
    point = items[0].start
    point.fx_type = kind
    bars = bars_for(items)
    attach_extreme(point, bars)
    if missing:
        point.k.klines = []
    else:
        for bar in point.k.klines:
            bar.low, bar.high = point.val - 1, point.val + 1
    assert extreme_index(point) == point.k.k_index
    assert extreme_date(point) == point.k.date


def test_decomposition_extension_and_api_dates_share_both_endpoints():
    items = oscillation(9)
    bars = bars_for(items)
    start = attach_extreme(items[0].start, bars)
    end = attach_extreme(items[-1].end, bars)
    original = deepcopy(items)
    result = ChanlunResult(frequency='5min', klines=bars, xds=items,
                          structural_centres=find_structural_centres(items)).to_dict()
    block = result['base_decomposition']['blocks'][0]
    proof = result['extension_hierarchy']['proofs'][0]
    assert block['start_index'] == proof['start_index'] == start
    assert block['end_index'] == proof['end_index'] == end
    assert block['known_index'] == proof['known_index'] == items[-1].confirmed_index
    for key, index in (('start', start), ('end', end)):
        expected = bars[index].date.strftime('%Y-%m-%d %H:%M')
        assert block[f'{key}_date'] == proof[f'{key}_date'] == expected
        assert result['structural_centres'][0][f'{key}_date'] == expected
    assert items == original
    assert not result['structure_metadata']['recursive_levels_ready']


def test_cross_centre_parts_use_the_same_raw_anchors():
    items = segments(LATER_VALID_PRICES)
    bars = bars_for(items)
    before = expansion_regrouping(items)
    for item in items:
        attach_extreme(item.start, bars)
    attach_extreme(items[-1].end, bars)
    after = expansion_regrouping(items)
    for old, event in zip(before['candidates'], after['candidates'], strict=True):
        assert event['known_index'] == old['known_index']
        assert event['partition_selection'] == old['partition_selection']
        for part in event['parts']:
            first, last = part['source_segment_indices'][0], part['source_segment_indices'][-1]
            assert part['start_index'] == items[first].start.k.k_index - 1
            assert part['end_index'] == items[last].end.k.k_index - 1


@pytest.mark.parametrize('offset', [1, 17, 100])
@pytest.mark.parametrize('prices', [[8, 12, 10, 14], [14, 10, 12, 8, 20],
                                  [14, 10, 12, 8, 20, 16, 22, 18]])
def test_api_resolves_centre_sources_by_id_not_list_position(offset, prices):
    items = segments(prices)
    bars = bars_for(items)
    baseline = ChanlunResult(klines=bars, xds=items,
                            structural_centres=find_structural_centres(items)).to_dict()
    for item in items:
        item.index += offset
    original = deepcopy(items)
    result = ChanlunResult(klines=bars, xds=items,
                          structural_centres=find_structural_centres(items)).to_dict()
    for a, b in zip(baseline['structural_centres'], result['structural_centres'], strict=True):
        assert [s + offset for s in a['seed_segments']] == b['seed_segments']
        for key in ('start_date', 'end_date', 'formed_date', 'exited_date', 'state'):
            assert a[key] == b[key]
    assert items == original


def test_signal_marker_chart_date_and_confirmation_remain_separate():
    items, bars, macd = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18, 28, 26])
    target = items[9]
    index = attach_extreme(target.end, bars)
    events = structure_signals(items, bars, macd)
    event = next(s for s in events if s.signal_type == '3buy')
    assert event.signal_index == index
    assert event.confirmed_index == target.confirmed_index > index
    mmds, bcs = to_chart_signals(events, items)
    result = ChanlunResult(klines=bars, xds=items, mmds=mmds, bcs=bcs,
                          structural_signals=events).to_dict()
    marker = next(m for m in result['mmds'] if m['type'] == '3buy')
    signal = next(s for s in result['structural_signals'] if s['signal_type'] == '3buy')
    assert marker['date'] == signal['date'] == bars[index].date.strftime('%Y-%m-%d')
    assert marker['confirmed_date'] == bars[target.confirmed_index].date.strftime('%Y-%m-%d')
    assert not structure_signals(items, bars[:target.confirmed_index], macd) == events
    assert events == structure_signals(items, bars[:target.confirmed_index + 1], macd)


def test_direct_decomposition_and_proof_do_not_rewrite_confirmation_on_anchor_change():
    items = oscillation(9)
    bars = bars_for(items)
    attach_extreme(items[0].start, bars)
    before = items[-1].confirmed_index
    assert extension_hierarchy(items, before)['proofs'] == []
    at = extension_hierarchy(items, before + 1)['proofs'][0]
    assert at['known_index'] == before
    assert decompose_base_chain(items, before + 1)['blocks'][0]['start_index'] == at['start_index']


def test_macd_comparison_uses_raw_extremes_not_nearby_merged_tail(monkeypatch):
    import easy_tdx.chanlun.structure_signals as signals

    items, bars, macd = signal_fixture([30, 40, 32, 38, 20, 26, 22, 25, 18])
    for point in (items[3].start, items[3].end, items[7].start, items[7].end):
        attach_extreme(point, bars)
    compared = []
    original = signals.segment_evidence

    def record(raw_bars, indicators, a, c, direction):
        compared.append((a, c, direction))
        return original(raw_bars, indicators, a, c, direction)

    monkeypatch.setattr(signals, 'segment_evidence', record)
    signals.structure_signals(items, bars, macd)
    assert ((12, 16), (28, 32), 'down') in compared
    assert ((13, 17), (29, 33), 'down') not in compared
