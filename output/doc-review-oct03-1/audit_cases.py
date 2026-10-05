"""Read-only frozen case audit for the Oct 3 document."""
import json
from pathlib import Path
from datetime import datetime
from easy_tdx.chanlun.types import Kline
from easy_tdx.chanlun.macd import calc_macd
from easy_tdx.chanlun.divergence_signals import wave_events, indicator_events

cases=[('399006','MIN_5','2026-09-29 11:15'),('603936','MIN_60','2026-09-22 11:30'),
       ('002821','MIN_30','2026-09-30 10:00'),('300054','MIN_30','2026-09-30 13:30'),
       ('603936','MIN_15','2026-09-29 09:45'),('603127','MIN_15','2026-09-30 09:45'),
       ('603259','MIN_30','2026-09-29 11:30')]
for code,category,target in cases:
    raw=json.loads((Path(__file__).parent/'quotes'/f'{code}-{category}.json').read_text())
    rows=raw['data'][-600:]
    bars=[Kline(i,datetime.fromisoformat(r.get('datetime',r.get('date'))),r['open'],r['close'],r['high'],r['low'],r.get('amount',0)) for i,r in enumerate(rows)]
    macd=calc_macd([b.close for b in bars],12,26,9)
    dt=lambda i:bars[i].date.strftime('%Y-%m-%d %H:%M') if i is not None else None
    at=next(i for i in range(len(bars)) if dt(i)==target)
    audit=[];waves=wave_events(bars,macd,diagnostics=audit)
    record=next((r for r in audit if r['c_start']<=at<=r['c_end']),None)
    print('\nCASE',code,category,target,'metadata',raw.get('metadata'))
    print('PRICE',bars[at].low,bars[at].high,'MACD',{k:v[at] for k,v in macd.items()})
    for event in waves+indicator_events(bars,macd):
        if abs(event.signal_index-at)<=2:
            print('EVENT',event.bc_type.value,dt(event.signal_index),event.status,'ref',dt(event.reference_index),'confirmed',dt(event.confirmed_index),'failed',event.failure_reason)
    if record:
        print('WAVE',record['direction'],record['status'],{k:dt(record.get(k)) for k in ['original_a_start','a_start','a_end','b_start','b_end','c_start','c_end']})
        for g in record['checks']:
            if not g['passed'] or g['gate'] in ['strict_price_extreme','shrinking_same_colour_area','dif_extreme_and_zero_axis','dea_extreme_and_zero_axis']:
                print('CHECK',g)
        if record.get('a_start') is not None:
            key='low' if record['direction']=='down' else 'high';fn=min if key=='low' else max
            print('ABC PRICE',[(s,fn(getattr(b,key) for b in bars[record[s+'_start']:record[s+'_end']+1])) for s in 'abc'])
