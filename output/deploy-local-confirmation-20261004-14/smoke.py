"""Frozen release acceptance; no network or production data required."""
import json
from pathlib import Path
import pandas as pd
from easy_tdx.chanlun.analyser import ChanlunAnalyser
from easy_tdx.chanlun.divergence_signals import INDICATOR_RULE_VERSION

assert INDICATOR_RULE_VERSION == 2026100414
root = Path(__file__).resolve().parent
CASES = [
    ('603936-min15-qfq-20261004', 'SH603936', '15min', '2026-09-15 09:45', '2026-09-15 13:45'),
    ('002821-min15-qfq-20261004', 'SZ002821', '15min', '2026-09-14 10:00', '2026-09-14 13:15'),
    ('002821-min15-qfq-20261004', 'SZ002821', '15min', '2026-09-18 09:45', '2026-09-18 11:00'),
    ('002821-min30-qfq-20261004', 'SZ002821', '30min', '2026-09-18 10:00', None),
    ('399006-min5-qfq-20261003', 'SZ399006', '5min', '2026-09-28 11:20', None),
]
for fixture, code, freq, at, confirmed in CASES:
    rows = json.loads((root/(fixture+'.json')).read_text())['data'][-600:]
    result = ChanlunAnalyser(code=code, frequency=freq).process_klines(pd.DataFrame(rows)).to_dict()
    families = ('macd_wave_special', 'macd') if confirmed else ('macd_wave_special',)
    for family in families:
        event = next(e for e in result['bcs'] if e['type']==family and e['curr_date']==at)
        assert event['evidence']['rule_version'] == 2026100414
        if confirmed:
            assert event['status']=='confirmed' and event['confirmed_date']==confirmed, event
            assert event['evidence']['reverse_pen_local']==1
            assert event['intervals']['reverse_pen_confirmed']==confirmed
        else:
            assert event['status']=='superseded' and not event.get('confirmed_date'), event
    print('PASS local proof', code, freq, at, confirmed, flush=True)
rows = json.loads((root/'603936-min60-qfq-20261003.json').read_text())['data'][-600:]
result = ChanlunAnalyser(code='SH603936', frequency='60min').process_klines(pd.DataFrame(rows)).to_dict()
event = next(e for e in result['bcs'] if e['type']=='macd_wave_nonstandard' and e.get('confirmed_date')=='2026-07-31 11:30')
assert event['evidence']['c_price_reaches_a']==0
print('PASS nonstandard C price unrestricted, confirmation retained', flush=True)
