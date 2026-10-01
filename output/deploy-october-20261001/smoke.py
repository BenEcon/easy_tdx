"""Offline verification in the actual release image, without production data."""
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pandas as pd

from easy_tdx.chanlun.analyser import ChanlunAnalyser
from easy_tdx.chanlun.divergence_signals import indicator_events, segment_evidence, wave_events
from easy_tdx.chanlun.types import Kline
from easy_tdx.indicator import compute_indicators
from easy_tdx.web.bar_snapshot import annotate_snapshot
from easy_tdx.web.routers.chanlun_observations import StudyRequest, observations
from easy_tdx.web.routers.bars import security_bars
from easy_tdx.mac.enums import Period

def bars(prices):
    return [Kline(i, datetime(2026, 9, 28) + timedelta(minutes=5*i), p+.5, p+.5,
                  p+1, p, 100) for i, p in enumerate(prices)]

ks = bars([23, 20, 23, 21, 23, 20.5, 23])
macd = {'dif': [-3, -3, -2, -1, -1, -.7, -1],
        'dea': [-2.8, -2.8, -1.8, -.8, -.8, -.6, -.8], 'hist': [-.1]*7}
event, = indicator_events(ks, macd)
assert (event.signal_index, event.reference_index, event.confirmed_index) == (5, 3, 6)
mirror = [Kline(b.index, b.date, 100-b.open, 100-b.close, 100-b.low, 100-b.high, 100) for b in ks]
top, = indicator_events(mirror, {k: [-x for x in v] for k, v in macd.items()})
assert top.direction == 'up' and top.reference_index == 3

ks = bars([25, 24, 20, 22, 23, 19, 19.5, 21])
macd = {'dif': [.1, .1, -2, -1, -.5, -1.5, -1.4, -1.3],
        'dea': [.1, -1.8, -1.7, -1.2, -.9, -1.3, -1.2, -1.1],
        'hist': [.2, -2, -1, .3, .2, -.5, -.2, .1]}
assert segment_evidence(ks, macd, (1, 2), (5, 6), 'down') is not None
assert segment_evidence(ks, macd, (1, 2), (5, 6), 'down', whole_leg_axis=True) is None
assert not wave_events(ks, macd)

data = json.loads(Path('/release/market-fixture.json').read_text())
frame = pd.DataFrame(data['bars'])
result = ChanlunAnalyser(code='600699', frequency='day').process_klines(frame)
payload = result.to_dict(ownership_history='summary')
assert (payload['bi_count'], payload['xd_count'], payload['zs_count']) == (52, 6, 10)
assert len(payload['pen_consolidations']) == 4
assert any(e['type'] == 'macd' and e['curr_date'] == '2026-07-09' and e['prev_date'] == '2026-07-03' for e in payload['bcs'])
assert not any(e['type'] == 'macd_wave' and e['curr_date'] == '2026-07-14' for e in payload['bcs'])
computed = compute_indicators(frame, ['MACD'])
for key in ('dif', 'dea', 'hist'):
    assert list(computed[f'MACD_{key.upper()}']) == result.macd[key]

rows = [{'datetime': datetime(2026, 9, 30, 9, 30) + timedelta(minutes=5*i),
         'open': 10, 'close': 10.1, 'high': 11, 'low': 9, 'vol': 100, 'amount': 1000} for i in range(12)]
study = observations(StudyRequest(as_of=datetime(2026, 9, 30, 10), series=[
    {'code': '300450', 'category': 'MIN_5', 'bars': rows},
    {'code': '300450', 'category': 'DAY', 'bars': [rows[0]]},
]))
assert study['rows'][0]['bar_count'] == 6 and 'error' in study['rows'][1]
assert study['eligible_for_trading'] is False
snapshot = annotate_snapshot(rows, 'MIN_5', source='TDX_STANDARD', requested_adjust='QFQ',
                             actual_adjust='NONE', now=datetime(2026, 9, 30, 9, 33))
assert snapshot['metadata']['actual_adjust'] == 'NONE'
assert snapshot['data'][0]['is_closed'] is False

async def check_120():
    mac = AsyncMock()
    mac.get_stock_kline.return_value = pd.DataFrame(rows)
    response = await security_bars(market='SZ', code='300450', category='MIN_120', start=0,
                                  count=12, bar_time='start', adjust='QFQ', mac_client=mac, client=AsyncMock())
    assert mac.get_stock_kline.call_args.args[2] == Period.MINS
    assert mac.get_stock_kline.call_args.args[5] == 24
    assert response['data'][0]['period_end'] == '2026-09-30 11:30:00'

asyncio.run(check_120())
print('PASS: nearest pivots, mirrored divergence, whole-wave axis scope, frozen market, consolidation, MACD precision, cutoff, provenance, 120-minute mapping')
