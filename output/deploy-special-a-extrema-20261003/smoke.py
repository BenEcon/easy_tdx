"""Offline image acceptance; no production data or network required."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from easy_tdx.chanlun.analyser import ChanlunAnalyser, ChanlunResult
from easy_tdx.chanlun.divergence_signals import indicator_events, special_wave_events, wave_events
from easy_tdx.chanlun.macd import calc_macd
from easy_tdx.chanlun.types import Kline

root = Path(__file__).resolve().parent
for mirrored in (False, True):
    sign = -1 if mirrored else 1
    bars = [Kline(i, datetime(2026, 1, 1)+timedelta(days=i), p+.4, p+.6, p+1, p, 100)
            for i, p in enumerate([12,10,11,12,13,14,13,12,11,9,10,11,12,13,12,11,10,9.5,10])]
    macd = {'dif': [-3]*9+[-1.5]*10, 'dea': [-2.5]*9+[-1.2]*10,
            'hist': [.2]+[-1]*8+[.2,-.4,-.2]+[.1]*7}
    macd['dif'][1], macd['dif'][3] = -1, -4
    macd['dea'][1], macd['dea'][5] = -.8, -3.5
    if mirrored:
        bars = [Kline(b.index,b.date,100-b.open,100-b.close,100-b.low,100-b.high,b.amount) for b in bars]
        macd = {k: [-v for v in values] for k,values in macd.items()}
    assert not any(e.signal_index == 9 for e in indicator_events(bars, macd))
    for n in (10,18,19):
        event = next(e for e in special_wave_events(bars[:n], {k:v[:n] for k,v in macd.items()}) if e.signal_index == 9)
        assert event.evidence['previous_dif'] == -4*sign
        assert event.evidence['previous_dea'] == -3.5*sign
        assert event.evidence['a_dif_extreme_index'] == 3
        assert event.evidence['a_dea_extreme_index'] == 5
        assert event.confirmed_index == (18 if n == 19 else None)
    for line in ('dif','dea'):
        broken = {k:v[:] for k,v in macd.items()}
        broken[line][9] = 0
        assert not any(e.signal_index == 9 for e in special_wave_events(bars, broken))
print('PASS independent A indicator extrema, mirrored rules, axis and reverse-pen timing')

for code, period, frequency, date in [('603936','min60','60min','2026-09-22 11:30'),
                                     ('603259','min30','30min','2026-09-29 11:30')]:
    raw = json.loads((root/f'{code}-{period}-qfq-20261003.json').read_text())['data'][-600:]
    frame = pd.DataFrame(raw)
    result = ChanlunAnalyser(code='SH'+code, frequency=frequency).process_klines(frame).to_dict()
    assert {'standard','nonstandard','special'} <= {r['family'] for r in result['wave_diagnostics']}
    if code == '603936':
        e = next(e for e in result['bcs'] if e['type']=='macd_wave_special' and e['curr_date']==date)
        assert e['status']=='candidate' and e['confirmed_index'] is None
        assert e['intervals']['a_dif_extreme_index']=='2026-09-15 11:30'
        assert e['intervals']['a_dea_extreme_index']=='2026-09-16 11:30'
        assert abs(e['evidence']['previous_dif']-1.282777764)<1e-6
        assert abs(e['evidence']['previous_dea']-1.128720187)<1e-6
    else:
        e = next(e for e in result['bcs'] if e['type']=='macd_wave_nonstandard' and e['curr_date']==date)
        assert e['status']=='confirmed' and e['confirmed_date']=='2026-09-30 10:00'
        assert abs(e['evidence']['a_area']-7.623578941)<1e-6
        assert not any(e['type']=='macd_wave' and e['curr_date']==date and e['status']=='confirmed' for e in result['bcs'])
    print('PASS real case',code,frequency)
