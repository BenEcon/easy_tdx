"""Oct 3 confirmed three-family rules; no future confirmation or strategy mixing."""
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from easy_tdx.chanlun.analyser import ChanlunAnalyser, ChanlunResult
from easy_tdx.chanlun.divergence_signals import indicator_events, special_wave_events, wave_events
from easy_tdx.chanlun.macd import calc_macd
from easy_tdx.chanlun.types import Kline
from tests.unit.test_wave_rule_comparison import sample
from tests.unit.test_october_second_divergence import reverse_pen_sample


def snapshot(name, count=600, top=False):
    raw = json.loads((Path(__file__).parents[1]/'fixtures/chanlun'/f'{name}.json').read_text())
    bars = [Kline(i, datetime.fromisoformat(r['datetime']), r['open'], r['close'],
                  r['high'], r['low'], r['amount']) for i, r in enumerate(raw['data'][-count:])]
    macd = calc_macd([b.close for b in bars], 12, 26, 9)
    if top:
        bars = [Kline(b.index, b.date, 100-b.open, 100-b.close, 100-b.low, 100-b.high, b.amount) for b in bars]
        macd = {k: [-v for v in values] for k, values in macd.items()}
    return bars, macd


@pytest.mark.parametrize('top', [False, True])
@pytest.mark.parametrize('family', ['standard', 'nonstandard'])
def test_b_price_boundary_by_family_while_c_may_equal(top, family):
    bars, macd = sample(top)
    key = 'high' if top else 'low'
    setattr(bars[5], key, getattr(bars[2], key))
    setattr(bars[6], key, getattr(bars[2], key))
    assert wave_events(bars, macd, family=family)[-1].status == 'confirmed'
    for delta in (0, 1):
        setattr(bars[3], key, getattr(bars[2], key) + (delta if top else -delta))
        audit = []
        if family == 'nonstandard' and delta == 0:
            assert wave_events(bars, macd, family=family)[-1].status == 'confirmed'
            continue
        assert not wave_events(bars, macd, family=family, diagnostics=audit)
        record = next(r for r in audit if r['c_start'] == 5)
        assert record['family'] == family
        gate = 'b_price_inside_a' if family == 'standard' else 'b_price_not_beyond_a'
        assert any(g['gate'] == gate and not g['passed'] for g in record['checks'])


@pytest.mark.parametrize('top', [False, True])
def test_nonstandard_only_omits_dea_improvement(top):
    bars, macd = sample(top)
    sign = -1 if top else 1
    macd['dea'][5:7] = [-2*sign, -1.9*sign]
    assert not wave_events(bars, macd)
    audits = []
    event, = wave_events(bars, macd, family='nonstandard', diagnostics=audits)
    assert event.status == 'confirmed' and event.confirmed_index == 7
    assert event.bc_type.value == 'macd_wave_nonstandard'
    assert event.evidence['a_dea_extreme'] == pytest.approx(-1.8*sign)
    assert event.evidence['c_dea_extreme'] == pytest.approx(-2*sign)
    gates = {g['gate'] for r in audits for g in r['checks']}
    assert 'dea_extreme_and_zero_axis' not in gates
    assert {'dea_zero_axis_without_improvement', 'dea_whole_bc_zero_axis',
            'dea_centre_pullback'} <= gates


@pytest.mark.parametrize('top', [False, True])
@pytest.mark.parametrize('index,value', [(3, 0), (3, .1), (5, 0), (5, .1), (5, float('nan'))])
def test_nonstandard_retains_dea_zero_axis_and_finite_checks(top, index, value):
    bars, macd = sample(top)
    macd['dea'][index] = -value if top else value
    assert not wave_events(bars, macd, family='nonstandard')


@pytest.mark.parametrize('top', [False, True])
def test_nonstandard_retains_dea_pullback(top):
    bars, macd = sample(top)
    sign = -1 if top else 1
    macd['dea'][1:7] = [v*sign for v in [-1.8, -1.8, -1.9, -2, -2.1, -2.2]]
    audits = []
    assert not wave_events(bars, macd, family='nonstandard', diagnostics=audits)
    assert any(g['gate'] == 'dea_centre_pullback' and not g['passed']
               for r in audits for g in r['checks'])


@pytest.mark.parametrize('top', [False, True])
@pytest.mark.parametrize('condition', ['area', 'dif', 'axis'])
def test_nonstandard_still_rejects_area_dif_and_axis_failures(top, condition):
    bars, macd = sample(top)
    sign = -1 if top else 1
    if condition == 'area':
        macd['hist'][5] = -5*sign
    elif condition == 'dif':
        macd['dif'][5] = -3*sign
    else:
        macd['dif'][3] = 0
    assert not wave_events(bars, macd, family='nonstandard')


@pytest.mark.parametrize('top', [False, True])
def test_special_reverse_pen_confirmation_and_prefix_invariance(top):
    bars, macd = reverse_pen_sample(top)
    macd['hist'][0] = -.2 if top else .2
    macd['hist'][9] = -.2 if top else .2
    full = special_wave_events(bars, macd)
    for count in range(10, 20):
        events = special_wave_events(bars[:count], {k:v[:count] for k,v in macd.items()})
        event = next(e for e in events if e.signal_index == 9)
        assert event.bc_type.value == 'macd_wave_special'
        assert event.reference_index == 1
        assert event.confirmed_index == (14 if count >= 15 else None)
        assert event.status == ('confirmed' if count >= 15 else 'candidate')
        assert 'c_area' not in event.evidence and 'c_start' not in event.evidence
        assert [e for e in events if e.status == 'confirmed'] == [e for e in full if e.confirmed_index is not None and e.confirmed_index < count]
    payload = ChanlunResult(klines=bars, bcs=full).to_dict()['bcs'][0]
    assert payload['type'] == 'macd_wave_special'
    assert payload['intervals']['a_start'] and payload['intervals']['b_start']
    assert 'c_start' not in payload['intervals']
    changed = deepcopy(macd)
    changed['dif'][13] = changed['dif'][1]
    audits = []
    failed = next(e for e in special_wave_events(bars, changed, diagnostics=audits) if e.signal_index == 9)
    assert failed.status == 'superseded' and failed.invalidated_index == 13
    report = next(r for r in audits if r['b_start'] == 9)
    assert report['known_index'] == 13 and report['status'] == 'blocked'
    assert any(not g['passed'] for g in report['checks'])


def test_special_repeated_equal_b_extreme_does_not_duplicate_candidates():
    bars, macd = reverse_pen_sample()
    macd['hist'][0] = .2
    macd['hist'][9] = macd['hist'][10] = .2
    bars[10].low = bars[9].low
    events = special_wave_events(bars[:11], {k:v[:11] for k,v in macd.items()})
    assert [e.signal_index for e in events] == [9]


def special_distinct_extrema_sample(top=False):
    bars, macd = reverse_pen_sample(top)
    sign = -1 if top else 1
    macd['hist'][0] = macd['hist'][9] = .2*sign
    macd['dif'][1], macd['dif'][3] = -1*sign, -4*sign
    macd['dea'][1], macd['dea'][5] = -.8*sign, -3.5*sign
    return bars, macd


@pytest.mark.parametrize('top', [False, True])
def test_special_a_indicator_extrema_are_independent_of_price_and_each_other(top):
    bars, macd = special_distinct_extrema_sample(top)
    sign = -1 if top else 1
    original = indicator_events(bars, macd)
    assert not any(e.signal_index == 9 for e in original)
    audits = []
    event = next(e for e in special_wave_events(bars, macd, diagnostics=audits) if e.signal_index == 9)
    assert event.reference_index == 1  # A price, not either indicator extreme.
    assert event.evidence['previous_dif'] == -4*sign
    assert event.evidence['previous_dea'] == -3.5*sign
    assert event.evidence['a_dif_extreme_index'] == 3
    assert event.evidence['a_dea_extreme_index'] == 5
    assert event.evidence['dif'] == macd['dif'][9]
    assert event.evidence['dea'] == macd['dea'][9]
    assert event.status == 'confirmed' and event.confirmed_index == 14
    assert indicator_events(bars, macd) == original
    for n in (10, 14, 18, 19):
        early = next(e for e in special_wave_events(bars[:n], {k:v[:n] for k,v in macd.items()})
                     if e.signal_index == 9)
        assert early.evidence['previous_dif'] == event.evidence['previous_dif']
        assert early.evidence['previous_dea'] == event.evidence['previous_dea']
        assert early.confirmed_index == (14 if n >= 15 else None)
    payload = ChanlunResult(klines=bars, bcs=[event], wave_diagnostics=audits).to_dict()
    assert payload['bcs'][0]['intervals']['a_dif_extreme_index'] == '2026-01-04'
    assert payload['bcs'][0]['intervals']['a_dea_extreme_index'] == '2026-01-06'
    report = next(r for r in payload['wave_diagnostics'] if r['b_start'] == 9)
    check = next(g for g in report['checks'] if g['gate'] == 'special_dea_a_segment_extreme')
    assert check['dates']['previous_index'] == '2026-01-06'


@pytest.mark.parametrize('top', [False, True])
@pytest.mark.parametrize('line', ['dif', 'dea'])
@pytest.mark.parametrize('condition', ['touch', 'cross', 'equal', 'worse', 'a_wrong_side'])
def test_special_keeps_b_point_axis_and_strict_improvement(top, line, condition):
    bars, macd = special_distinct_extrema_sample(top)
    sign = -1 if top else 1
    reference = -4 if line == 'dif' else -3.5
    if condition == 'a_wrong_side':
        macd[line][1:9] = [.1*sign]*8
    else:
        macd[line][9] = sign*{'touch': 0, 'cross': .1, 'equal': reference, 'worse': reference-1}[condition]
    # A later, better B indicator value must not substitute for the price-day value.
    macd[line][10] = -.1*sign
    audits = []
    assert not any(e.signal_index == 9 for e in special_wave_events(bars, macd, diagnostics=audits))
    report = next(r for r in audits if r['b_start'] == 9)
    assert any(g['gate'] == f'special_{line}_a_segment_extreme' and not g['passed'] for g in report['checks'])


@pytest.mark.parametrize('top', [False, True])
def test_special_lifecycle_reuses_a_segment_extreme_not_a_price_day(top):
    bars, macd = special_distinct_extrema_sample(top)
    sign = -1 if top else 1
    macd['dif'][13] = -3.8*sign  # Worse than A price-day (-1), still above A trough (-4).
    event = next(e for e in special_wave_events(bars, macd) if e.signal_index == 9)
    assert event.status == 'confirmed'
    macd['dif'][13] = -4*sign
    event = next(e for e in special_wave_events(bars, macd) if e.signal_index == 9)
    assert event.status == 'superseded' and event.invalidated_index == 13


@pytest.mark.parametrize('count', [600, 800])
@pytest.mark.parametrize('mirror', [False, True])
def test_603936_special_uses_a_not_nearest_local_point(count, mirror):
    bars, macd = snapshot('603936-min60-qfq-20261003', count, mirror)
    at = next(i for i,b in enumerate(bars) if str(b.date) == '2026-09-22 11:30:00')
    assert not any(e.signal_index == at for e in indicator_events(bars, macd))
    special = next(e for e in special_wave_events(bars, macd) if e.signal_index == at)
    assert str(bars[special.reference_index].date) == '2026-09-15 10:30:00'
    assert special.status == 'confirmed'
    assert str(bars[special.confirmed_index].date) == '2026-09-28 15:00:00'
    assert special.evidence['price'] == pytest.approx(100-23.76 if mirror else 23.76)
    assert special.evidence['previous_price'] == pytest.approx(100-23.28 if mirror else 23.28)
    assert str(bars[special.evidence['a_dif_extreme_index']].date) == '2026-09-15 11:30:00'
    assert str(bars[special.evidence['a_dea_extreme_index']].date) == '2026-09-16 11:30:00'
    assert special.evidence['previous_dif'] == pytest.approx((-1 if mirror else 1)*1.282777764, abs=1e-6)
    assert special.evidence['previous_dea'] == pytest.approx((-1 if mirror else 1)*1.128720187, abs=1e-6)
    assert special.direction == ('down' if mirror else 'up')
    early = next(e for e in special_wave_events(bars[:at+1], {k:v[:at+1] for k,v in macd.items()}) if e.signal_index == at)
    assert all(special.evidence[k] == v for k, v in early.evidence.items()
               if not k.startswith('reverse_pen_'))
    assert early.status == 'candidate' and early.confirmed_index is None
    assert early.preliminary_index is None  # later preliminary evidence is not backdated


@pytest.mark.parametrize('count', [600, 800])
@pytest.mark.parametrize('mirror', [False, True])
def test_603259_only_nonstandard_confirms_at_colour_change(count, mirror):
    bars, macd = snapshot('603259-min30-qfq-20261003', count, mirror)
    at = next(i for i,b in enumerate(bars) if str(b.date) == '2026-09-29 11:30:00')
    assert not any(e.signal_index == at and e.status == 'confirmed' for e in wave_events(bars, macd))
    event = next(e for e in wave_events(bars, macd, family='nonstandard') if e.signal_index == at)
    assert event.status == 'confirmed'
    assert str(bars[event.confirmed_index].date) == '2026-09-30 10:00:00'
    assert event.evidence['c_area'] < event.evidence['a_area']
    assert event.evidence['a_area'] == pytest.approx(24.922384899472686, abs=1e-6)
    assert event.direction == ('up' if mirror else 'down')
    for count in (at+1, event.confirmed_index, event.confirmed_index+1):
        early = next(e for e in wave_events(bars[:count], {k:v[:count] for k,v in macd.items()}, family='nonstandard') if e.signal_index == at)
        assert (early.status == 'confirmed') == (count > event.confirmed_index)


def test_399006_b_break_blocks_standard_and_nonstandard():
    bars, macd = snapshot('399006-min5-qfq-20261003')
    at = next(i for i,b in enumerate(bars) if str(b.date) == '2026-09-29 11:15:00')
    for family in ('standard', 'nonstandard'):
        audits = []
        assert not any(e.signal_index == at for e in wave_events(bars, macd, family=family, diagnostics=audits))
        report = next(r for r in audits if r['c_start'] <= at <= r['c_end'])
        gate = 'b_price_inside_a' if family == 'standard' else 'b_price_not_beyond_a'
        assert any(g['gate'] == gate and not g['passed'] for g in report['checks'])


def test_analyser_exports_all_families_without_new_structural_signals():
    import pandas as pd
    bars, _ = snapshot('603936-min60-qfq-20261003')
    frame = pd.DataFrame([{'datetime': b.date, 'open': b.open, 'close': b.close,
                           'high': b.high, 'low': b.low, 'vol': b.amount} for b in bars])
    result = ChanlunAnalyser(frequency='60min').process_klines(frame)
    payload = result.to_dict()
    assert {'standard', 'nonstandard', 'special'} <= {r['family'] for r in payload['wave_diagnostics']}
    assert any(b['type'] == 'macd_wave_special' and b['curr_date'] == '2026-09-22 11:30' for b in payload['bcs'])
    assert all(m.source == 'confirmed_segment_base_v1' for m in result.mmds)
