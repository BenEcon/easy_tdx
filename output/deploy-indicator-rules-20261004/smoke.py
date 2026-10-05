"""Offline production-image checks with frozen cases; no user data access."""
import json
from pathlib import Path
import pandas as pd
from easy_tdx.chanlun.analyser import ChanlunAnalyser
from easy_tdx.chanlun.divergence_signals import INDICATOR_RULE_VERSION

assert INDICATOR_RULE_VERSION == 20261004
root = Path(__file__).resolve().parent
for code, period, frequency, date in [
    ('603936', 'min60', '60min', '2026-09-22 11:30'),
    ('603259', 'min30', '30min', '2026-09-29 11:30'),
    ('399006', 'min5', '5min', '2026-09-29 11:15'),
]:
    raw = json.loads((root/f'{code}-{period}-qfq-20261003.json').read_text())['data'][-600:]
    result = ChanlunAnalyser(code=('SZ' if code=='399006' else 'SH')+code,
                            frequency=frequency).process_klines(pd.DataFrame(raw)).to_dict()
    assert {'standard', 'nonstandard', 'special', 'double'} <= {r['family'] for r in result['wave_diagnostics']}
    if code == '603936':
        e = next(e for e in result['bcs'] if e['type']=='macd_wave_special' and e['curr_date']==date)
        assert e['status']=='confirmed' and e['confirmed_date']=='2026-09-28 15:00'
        assert e['evidence']['rule_version']==20261004
        assert e['intervals']['a_dif_extreme_index']=='2026-09-15 11:30'
        assert e['intervals']['a_dea_extreme_index']=='2026-09-16 11:30'
        assert not any(e['type']=='macd' and e['curr_date']==date for e in result['bcs'])
    elif code == '603259':
        e = next(e for e in result['bcs'] if e['type']=='macd_wave_nonstandard' and e['curr_date']==date)
        assert e['status']=='confirmed' and e['confirmed_date']=='2026-09-30 10:00'
        assert abs(e['evidence']['a_area']-24.922384899472686)<1e-6
        assert not any(e['type']=='macd_wave' and e['curr_date']==date and e['status']=='confirmed' for e in result['bcs'])
    else:
        assert not any(e['type'] in ('macd_wave', 'macd_wave_nonstandard') and e['curr_date']==date for e in result['bcs'])
    print('PASS frozen case', code, frequency, flush=True)
