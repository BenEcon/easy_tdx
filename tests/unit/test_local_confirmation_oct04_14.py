"""Approved October 4-14 boundaries, local proof and causal history acceptance."""
from copy import deepcopy

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.bi import find_bis, _can_form_bi
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.kline_merge import merge_klines
from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.anchors import extreme_index
from easy_tdx.chanlun.divergence_signals import (
    indicator_events, special_wave_events, wave_events, _link_replacements,
)
from easy_tdx.chanlun.types import BC, BCType
from tests.unit.test_october_second_divergence import sample, reverse_pen_sample
from tests.unit.test_wave_families import snapshot


@pytest.mark.parametrize('top', [False, True])
@pytest.mark.parametrize('relative', [-1, 0, 1])
def test_nonstandard_c_can_be_on_either_side_and_b_equal(top, relative):
    bars, macd = sample(top)
    key, sign = ('high', -1) if top else ('low', 1)
    a = getattr(bars[2], key)
    setattr(bars[3], key, a)
    setattr(bars[5], key, a + relative * sign)
    setattr(bars[6], key, a + (relative + .5) * sign)
    event, = wave_events(bars, macd, family='nonstandard')
    assert event.status == 'confirmed' and event.confirmed_index == 7
    assert event.evidence['c_price_reaches_a'] == int(relative <= 0)
    assert not wave_events(bars, macd)  # Standard B remains strict.
    for n in range(1, len(bars) + 1):
        current = wave_events(bars[:n], {k:v[:n] for k,v in macd.items()}, family='nonstandard')
        assert all(e.detected_index < n and (e.confirmed_index is None or e.confirmed_index < n) for e in current)
        if n > 5:
            assert current[0].status == ('confirmed' if n == 8 else 'candidate')


@pytest.mark.parametrize('top', [False, True])
@pytest.mark.parametrize('gate', ['area', 'dif', 'dea_axis', 'dif_axis', 'b_price'])
def test_relaxed_c_keeps_all_other_gates_and_failure_evidence(top, gate):
    bars, macd = sample(top)
    key, sign = ('high', -1) if top else ('low', 1)
    setattr(bars[5], key, getattr(bars[2], key) + sign)
    setattr(bars[6], key, getattr(bars[2], key) + 1.5 * sign)
    if gate == 'area': macd['hist'][6] = -4 * sign
    elif gate == 'dif': macd['dif'][6] = -3 * sign
    elif gate == 'dea_axis': macd['dea'][6] = 0
    elif gate == 'dif_axis': macd['dif'][6] = 0
    else: setattr(bars[3], key, getattr(bars[2], key) - sign)
    audit = []
    events = wave_events(bars, macd, family='nonstandard', diagnostics=audit)
    assert not any(e.status == 'confirmed' for e in events)
    assert any(not c['passed'] for r in audit if r['c_start'] == 5 for c in r['checks'])
    if gate != 'b_price':
        assert events[0].status == 'superseded'
        assert events[0].invalidated_index == 6 and events[0].failure_reason


CASES = [
    ('603936-min15-qfq-20261004', '2026-09-15 09:45:00', '2026-09-15 13:45:00'),
    ('002821-min15-qfq-20261004', '2026-09-14 10:00:00', '2026-09-14 13:15:00'),
    ('002821-min15-qfq-20261004', '2026-09-18 09:45:00', '2026-09-18 11:00:00'),
]


@pytest.mark.parametrize('name,at,confirmation', CASES)
@pytest.mark.parametrize('detector', [special_wave_events, indicator_events])
def test_real_local_proof_confirms_without_global_selection_and_freezes(name, at, confirmation, detector):
    bars, macd = snapshot(name)
    index = next(i for i,b in enumerate(bars) if str(b.date) == at)
    full = detector(bars, macd)
    event = next(e for e in full if e.signal_index == index)
    assert str(bars[event.confirmed_index].date) == confirmation
    assert event.evidence['reverse_pen_local'] == 1
    fxs = find_fractals(merge_klines(bars[:event.confirmed_index+1]))
    start = next(f for f in fxs if extreme_index(f) == index)
    end = next(f for f in fxs if extreme_index(f) == event.evidence['reverse_pen_end'])
    assert _can_form_bi(start, end, ChanlunConfig())
    assert not any(extreme_index(b.start) == index for b in find_bis(fxs))
    # Every prefix from discovery through the end, not just the final chart.
    for n in range(index+1, len(bars)+1):
        current = next(e for e in detector(bars[:n], {k:v[:n] for k,v in macd.items()}) if e.signal_index == index)
        if n <= event.confirmed_index:
            assert current.status == 'candidate' and current.confirmed_index is None
        else:
            assert current == event
    encoded = ChanlunResult(klines=bars, bcs=[event], frequency='15min').to_dict()['bcs'][0]
    assert encoded['detected_index'] == event.detected_index
    assert encoded['intervals']['reverse_pen_confirmed'] == confirmation[:16]


@pytest.mark.parametrize('name,at,invalid', [
    ('399006-min5-qfq-20261003', '2026-09-28 11:20:00', '2026-09-28 13:25:00'),
    ('002821-min30-qfq-20261004', '2026-09-18 10:00:00', '2026-09-21 11:00:00'),
])
def test_local_does_not_waive_gap_or_use_lower_timeframe(name, at, invalid):
    bars, macd = snapshot(name)
    event = next(e for e in special_wave_events(bars, macd) if str(bars[e.signal_index].date) == at)
    assert event.status == 'superseded' and event.confirmed_index is None
    assert str(bars[event.invalidated_index].date) == invalid


@pytest.mark.parametrize('top', [False, True])
def test_local_rejects_open_bars_or_broken_conditions_before_proof(top):
    bars, macd = reverse_pen_sample(top)
    bars[14].is_closed = False
    event, = indicator_events(bars, macd)
    assert event.status == 'candidate'
    bars[14].is_closed = True
    macd['dif'][14] = macd['dif'][1]
    event, = indicator_events(bars, macd)
    assert event.status == 'superseded' and event.invalidated_index == 14


def test_replacement_requires_a_real_candidate_same_time_and_family():
    old = BC(bc_type=BCType.MACD, bc=True, direction='down', signal_index=5,
             status='superseded', invalidated_index=9, failure_reason='价格极值被后续新极值替代')
    _link_replacements([old])
    assert 'replacement_signal_index' not in old.evidence
    new = BC(bc_type=BCType.MACD, bc=True, direction='down', signal_index=9, detected_index=9)
    for changes in ({'detected_index':10}, {'direction':'up'}, {'bc_type':BCType.MACD_WAVE_SPECIAL}):
        other = deepcopy(new)
        for k,v in changes.items(): setattr(other,k,v)
        _link_replacements([old,other])
        assert 'replacement_signal_index' not in old.evidence
    _link_replacements([old,new])
    assert old.evidence['replacement_signal_index'] == 9


@pytest.mark.parametrize('name,c_start,confirmation,blocked_gate', [
    ('603936-min60-qfq-20261003','2026-07-29 11:30:00','2026-07-31 11:30:00',None),
    ('603936-min60-qfq-20261003','2026-08-27 11:30:00',None,'dif_whole_bc_zero_axis'),
    ('002821-min60-qfq-20261004','2026-08-03 15:00:00','2026-08-04 10:30:00',None),
    ('002821-min60-qfq-20261004','2026-08-20 11:30:00','2026-08-21 10:30:00',None),
    ('002821-min60-qfq-20261004','2026-08-28 11:30:00','2026-09-02 10:30:00',None),
    ('002821-min60-qfq-20261004','2026-09-21 10:30:00',None,'dif_extreme_and_zero_axis'),
])
def test_document_six_nonstandard_pairs(name, c_start, confirmation, blocked_gate):
    bars, macd = snapshot(name)
    start = next(i for i,b in enumerate(bars) if str(b.date) == c_start)
    audit = []
    events = wave_events(bars,macd,family='nonstandard',diagnostics=audit)
    matching = [e for e in events if e.evidence.get('c_start') == start and e.status == 'confirmed']
    if confirmation:
        assert len(matching) == 1
        assert str(bars[matching[0].confirmed_index].date) == confirmation
        assert matching[0].evidence['c_price_reaches_a'] == 0
    else:
        assert not matching
        report = next(r for r in audit if r['c_start'] == start)
        assert any(c['gate']==blocked_gate and not c['passed'] for c in report['checks'])
