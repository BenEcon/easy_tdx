"""Oct 2-2: research comparisons, exact rejection witnesses, unchanged defaults."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.divergence_signals import segment_evidence, wave_events
from easy_tdx.chanlun.macd import calc_macd
from easy_tdx.chanlun.types import Kline


def sample(top=False):
    bars = [Kline(i, datetime(2026, 1, 1)+timedelta(minutes=30*i), p+.5, p+.5, p+1, p, 100)
            for i, p in enumerate([25, 24, 20, 22, 23, 19, 19.5, 21, 22])]
    macd = {'dif': [.1, -2, -2, -1, -.5, -1.5, -1.4, -1.3, -1.2],
            'dea': [.1, -1.8, -1.7, -1.2, -.9, -1.3, -1.2, -1.1, -1.0],
            'hist': [.2, -2, -1, .3, .2, -.5, -.2, .1, .2]}
    if top:
        bars = [Kline(b.index,b.date,100-b.open,100-b.close,100-b.low,100-b.high,100) for b in bars]
        macd = {k: [-v for v in values] for k, values in macd.items()}
    return bars, macd


@pytest.mark.parametrize('top', [False, True])
@pytest.mark.parametrize('line', ['dif', 'dea'])
def test_both_whole_segment_extrema_required_not_only_price_day(top, line):
    bars, macd = sample(top)
    # The price extreme is at 5; the later C indicator extreme at 6 is worse.
    macd[line][6] = 3 if top else -3
    events = wave_events(bars, macd)
    failed, = events
    assert failed.signal_index == 5 and failed.invalidated_index == 6
    assert failed.status == 'superseded' and failed.confirmed_index is None
    assert line.upper() in failed.failure_reason
    gate = next(g for g in failed.failure_audit['checks'] if g['gate'] == f'{line}_extreme_and_zero_axis')
    assert not gate['passed'] and gate['values']['c_extreme_index'] == 6
    assert failed.evidence[f'c_{line}_extreme'] != gate['values']['c_extreme']
    assert failed.failure_audit['known_index'] == 6  # frozen, not overwritten at C close


@pytest.mark.parametrize('top', [False, True])
def test_equal_price_is_standard_but_not_future_confirmation(top):
    bars, macd = sample(top)
    key = 'high' if top else 'low'
    setattr(bars[5], key, getattr(bars[2], key))
    setattr(bars[6], key, getattr(bars[2], key))
    for count in (6, 7, 8, 9):
        reports = []
        events = wave_events(bars[:count], {k:v[:count] for k,v in macd.items()}, diagnostics=reports)
        assert events[-1].status == ('confirmed' if count >= 8 else 'candidate')
        assert events[-1].confirmed_index == (7 if count >= 8 else None)
        report = next(r for r in reports if r['c_start'] == 5)
        assert report['status'] == ('confirmed' if count >= 8 else 'candidate')
        comparisons = {c['mode']:c for c in report['comparisons']}
        assert not comparisons['full_a']['passed']
        assert comparisons['equal_price']['passed'] and comparisons['full_a_equal_price']['passed']
        assert all(c['research_only'] for c in comparisons.values())
        assert comparisons['equal_price']['closed'] == (count >= 8)
        assert comparisons['equal_price']['known_index'] == min(count-1, 7)


@pytest.mark.parametrize('top', [False, True])
def test_full_a_recalculates_all_statistics_and_never_exempts_b_c(top):
    bars, macd = sample(top)
    macd['dif'][1] = -.1 if top else .1
    audit=[]
    wave_events(bars, macd, diagnostics=audit)
    report = next(r for r in audit if r['c_start']==5)
    full = report['comparisons'][0]
    assert full['passed'] and full['a_start']==1 and report['a_start']==2
    area=next(g['values'] for g in full['checks'] if g['gate']=='shrinking_same_colour_area')
    assert area['a_area']==3
    # Including original A's more extreme price must make this comparison fail.
    setattr(bars[1], 'high' if top else 'low', 90 if top else 10)
    audit=[]
    assert wave_events(bars, macd, diagnostics=audit)[0].status=='confirmed'
    assert not next(r for r in audit if r['c_start']==5)['comparisons'][0]['passed']
    macd['dea'][3]=0
    audit=[]
    assert not wave_events(bars, macd, diagnostics=audit)
    for comparison in next(r for r in audit if r['c_start']==5)['comparisons']:
        assert not comparison['passed']
    full=next(r for r in audit if r['c_start']==5)['comparisons'][0]
    assert any(g['gate']=='dea_whole_bc_zero_axis' and not g['passed'] for g in full['checks'])


def test_failure_snapshot_and_comparisons_are_independent_exports():
    bars, macd=sample()
    macd['hist'][6]=-4
    audit=[]
    event, = wave_events(bars, macd, diagnostics=audit)
    result=ChanlunResult(klines=bars, bcs=[event], wave_diagnostics=audit, frequency='30min')
    payload=result.to_dict()
    failed=payload['bcs'][0]['failure_audit']
    assert failed['dates']['known_index']=='2026-01-01 03:00'
    area=next(g for g in failed['checks'] if g['gate']=='shrinking_same_colour_area')
    assert area['values']['c_area']==4.5 and not area['passed']
    failed['checks'].clear()
    payload['wave_diagnostics'][-2]['comparisons'].clear()
    assert event.failure_audit['checks']
    assert all(len(r['comparisons'])==4 for r in audit)


def test_same_price_anchor_is_not_described_as_new_low():
    bars, macd=sample()
    bars[6].low=bars[5].low
    event, = wave_events(bars, macd)
    assert event.status=='confirmed' and event.signal_index == 5


@pytest.mark.parametrize('count',[600,800])
@pytest.mark.parametrize('top',[False,True])
def test_document_four_cases_and_mirrors(count,top):
    raw=json.loads((Path(__file__).parents[1]/'fixtures/chanlun/601698-min30-qfq-20261002.json').read_text())
    assert raw['metadata']['actual_adjust']=='QFQ' and raw['metadata']['category']=='MIN_30'
    bars=[Kline(i,datetime.fromisoformat(r['datetime']),r['open'],r['close'],r['high'],r['low'],r['amount'])
          for i,r in enumerate(raw['data'][-count:])]
    macd=calc_macd([b.close for b in bars],12,26,9)
    if top:
        bars=[Kline(b.index,b.date,100-b.open,100-b.close,100-b.low,100-b.high,100) for b in bars]
        macd={k:[-v for v in values] for k,values in macd.items()}
    date=lambda i:bars[i].date.strftime('%Y-%m-%d %H:%M')
    reports=[]
    events=wave_events(bars,macd,diagnostics=reports)
    expected={
        '2026-09-04 15:00': (False,False,False),
        '2026-09-10 10:30': (False,False,False),
        '2026-09-17 11:30': (False,True,True),
        '2026-09-22 10:00': (False,False,False),
    }
    for start, allowed in expected.items():
        report=next(r for r in reports if date(r['c_start'])==start)
        assert report['status']==('confirmed' if start == '2026-09-17 11:30' else 'blocked')
        assert tuple(c['passed'] for c in report['comparisons'][:3])==allowed
        assert report['comparisons'][3]['passed'] == (start == '2026-09-22 10:00')
    event=next(e for e in events if date(e.signal_index)=='2026-09-22 11:00')
    assert event.status=='superseded' and date(event.invalidated_index)=='2026-09-22 11:30'
    failed=[g for g in event.failure_audit['checks'] if not g['passed']]
    assert [g['gate'] for g in failed]==['dea_extreme_and_zero_axis']
    assert abs(failed[0]['values']['a_extreme'])==pytest.approx(.06015324550774)
    assert abs(failed[0]['values']['c_extreme'])==pytest.approx(.06269914239408)
    before=event.invalidated_index
    prior=next(e for e in wave_events(bars[:before],{k:v[:before] for k,v in macd.items()})
               if date(e.signal_index)=='2026-09-22 11:00')
    assert prior.status=='candidate' and not prior.failure_audit


def test_research_equality_does_not_change_structural_defaults():
    bars,macd=sample()
    bars[5].low=bars[6].low=bars[2].low
    assert segment_evidence(bars,macd,(1,2),(5,6),'down') is None
    assert segment_evidence(bars,macd,(1,2),(5,6),'down',allow_equal_price=True) is not None


@pytest.mark.parametrize('top',[False,True])
def test_price_day_lines_can_be_worse_if_whole_segment_extrema_improve(top):
    bars,macd=sample(top)
    sign=-1 if top else 1
    # A price low/high is index 2, while A DIF extreme is 1; DEA differs too.
    macd['dif'][1],macd['dif'][2]=-3*sign,-1*sign
    macd['dea'][1],macd['dea'][2]=-2.8*sign,-.9*sign
    event,=wave_events(bars,macd)
    assert event.signal_index==5 and event.reference_index==2
    assert event.status=='confirmed'
    # On price days alone the C values are worse, yet segment extrema improve.
    assert sign*macd['dif'][5]<sign*macd['dif'][2]
    assert sign*macd['dea'][5]<sign*macd['dea'][2]
    assert event.evidence['a_dif_extreme']==-3*sign
    assert event.evidence['c_dif_extreme']==-1.5*sign
