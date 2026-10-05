"""Read-only diagnostics for user questions; does not change production rules."""
import json
from pathlib import Path
from datetime import datetime
from easy_tdx.chanlun.types import Kline
from easy_tdx.chanlun.macd import calc_macd
from easy_tdx.chanlun.divergence_signals import special_wave_events, indicator_events, wave_events

ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent/'doc-review-oct03-1/quotes'
def load(code, period):
    p = ROOT/f'{code}-{period}.json'
    if not p.exists(): p = OLD/p.name
    raw = json.loads(p.read_text())
    rows = raw['data'][-600:]
    bars = [Kline(i,datetime.fromisoformat(r['datetime']),r['open'],r['close'],r['high'],r['low'],r['amount']) for i,r in enumerate(rows)]
    return bars, calc_macd([b.close for b in bars],12,26,9), raw.get('metadata')

def audit(code,period,targets=(),all_waves=False):
    bars,m,meta=load(code,period)
    dt=lambda i: bars[i].date.strftime('%Y-%m-%d %H:%M') if i is not None else None
    print('\nCASE',code,period,'range',dt(0),dt(len(bars)-1),'meta',meta)
    special=special_wave_events(bars,m)
    dual=indicator_events(bars,m)
    for date,direction in targets:
        at=next(i for i in range(len(bars)) if dt(i)==date)
        print('TARGET',date,direction, 'low/high', bars[at].low,bars[at].high,'MACD',{k:v[at] for k,v in m.items()})
        for detector,name in ((special_wave_events,'SPECIAL'),(indicator_events,'DUAL')):
            reports=[]
            prefix=detector(bars[:at+1],{k:v[:at+1] for k,v in m.items()},diagnostics=reports)
            for e in prefix:
                if e.signal_index==at:
                    print(name,'PREFIX',e.status,'ref',dt(e.reference_index),'evidence',e.evidence)
            for r in reports:
                if r.get('known_index')==at and r['direction']==direction:
                    print(name,'REPORT',json.dumps(r,ensure_ascii=False))
        for name,events in (('SPECIAL',special),('DUAL',dual)):
            for e in events:
                if abs(e.signal_index-at)<=1:
                    print(name,'FINAL',dt(e.signal_index),e.status,'confirmed',dt(e.confirmed_index),'invalidated',dt(e.invalidated_index),e.failure_reason, 'evidence',e.evidence)
        # Exact run context at event date, independent of the final report's overwrites.
        runs=[]
        for i,h in enumerate(m['hist'][:at+1]):
            colour=1 if h>0 else -1 if h<0 else runs[-1][0] if runs else 0
            if not colour: continue
            if not runs or colour!=runs[-1][0]: runs.append([colour,i,i])
            else: runs[-1][2]=i
        for colour,s,t in runs[-2:]:
            print('AB',colour,dt(s),dt(t),'low',min(b.low for b in bars[s:t+1]),'high',max(b.high for b in bars[s:t+1]),
                  'dif_min/max',min(m['dif'][s:t+1]),max(m['dif'][s:t+1]),'dea_min/max',min(m['dea'][s:t+1]),max(m['dea'][s:t+1]))
    if all_waves:
        reports=[]
        events=wave_events(bars,m,family='nonstandard',diagnostics=reports)
        for r in reports:
            if dt(r['c_start'])<'2026-07-25' or 'a_start' not in r: continue
            print('WAVE',r['direction'],r['status'],{k:dt(r.get(k)) for k in ['a_start','a_end','b_start','b_end','c_start','c_end']})
            for g in r['checks']:
                if not g['passed'] or g['gate'] in ('equal_or_new_price_extreme','shrinking_same_colour_area','dif_extreme_and_zero_axis','b_price_inside_a'):
                    print('CHECK',g)
            failures=[g['gate'] for g in r['checks'] if not g['passed']]
            print('PRICE_ONLY_RELAXATION_PASSES',all(g['passed'] for g in r['checks'] if g['gate']!='equal_or_new_price_extreme'),'failures',failures)

if __name__=='__main__':
    audit('399006','MIN_5',[(f'2026-09-28 {t}','down') for t in ['11:00','11:20','13:40']])
    audit('603936','MIN_15',[('2026-09-15 09:45','up')])
    audit('002821','MIN_15',[('2026-09-14 10:00','down'),('2026-09-18 09:45','up')])
    audit('002821','MIN_30',[('2026-09-18 10:00','up')])
    audit('603936','MIN_60',all_waves=True)
    audit('002821','MIN_60',all_waves=True)
