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
from easy_tdx.chanlun.macd import calc_macd
from easy_tdx.indicator import compute_indicators
from easy_tdx.web.bar_snapshot import annotate_snapshot
from easy_tdx.web.routers.chanlun_observations import StudyRequest, observations
from easy_tdx.web.routers.bars import security_bars
from easy_tdx.mac.enums import Period

def bars(prices):
    return [Kline(i, datetime(2026, 9, 28) + timedelta(minutes=5*i), p+.5, p+.5,
                  p+1, p, 100) for i, p in enumerate(prices)]

ks = [Kline(i, datetime(2026, 1, 1) + timedelta(days=i), p+.4, p+.6, p+1, p, 100)
      for i, p in enumerate([12, 10, 11, 12, 13, 14, 13, 12, 11, 9, 10, 11, 12, 13, 12, 11, 10, 9.5, 10])]
macd = {'dif': [-3]*9 + [-1.5]*10, 'dea': [-2.5]*9 + [-1.2]*10,
        'hist': [-1]*9 + [-.6, -.4, -.2] + [.1]*7}
for n in range(10, 20):
    event, = indicator_events(ks[:n], {k: v[:n] for k, v in macd.items()})
    assert (event.signal_index, event.reference_index) == (9, 1)
    assert event.preliminary_index == (11 if n >= 12 else None)
    assert event.confirmed_index == (18 if n == 19 else None)
mirror = [Kline(b.index, b.date, 100-b.open, 100-b.close, 100-b.low, 100-b.high, 100) for b in ks]
top, = indicator_events(mirror, {k: [-x for x in v] for k, v in macd.items()})
assert top.direction == 'up' and top.confirmed_index == 18
broken = {k: v[:] for k, v in macd.items()}
broken['dif'][16] = broken['dif'][1]
invalid, = indicator_events(ks, broken)
assert invalid.invalidated_index == 16 and invalid.confirmed_index is None

ks = bars([25, 24, 20, 22, 23, 19, 19.5, 21])
macd = {'dif': [.1, .1, -2, -1, -.5, -1.5, -1.4, -1.3],
        'dea': [.1, -1.8, -1.7, -1.2, -.9, -1.3, -1.2, -1.1],
        'hist': [.2, -2, -1, .3, .2, -.5, -.2, .1]}
assert segment_evidence(ks, macd, (1, 2), (5, 6), 'down') is not None
assert segment_evidence(ks, macd, (1, 2), (5, 6), 'down', whole_leg_axis=True) is None
trimmed, = wave_events(ks, macd)
assert trimmed.confirmed_index == 7
assert trimmed.evidence['a_start'] == 2 and trimmed.evidence['original_a_start'] == 1
macd['dif'][1] = -2
early, = wave_events(ks[:6], {k: v[:6] for k, v in macd.items()})
assert early.signal_index == 5 and early.confirmed_index is None
final, = wave_events(ks, macd)
assert final.signal_index == 5 and final.confirmed_index == 7
macd['dea'][3] = 0
assert not wave_events(ks, macd)
assert segment_evidence(ks, macd, (1, 2), (5, 6), 'down') is not None

data = json.loads(Path('/release/market-fixture.json').read_text())
frame = pd.DataFrame(data['bars'])
result = ChanlunAnalyser(code='600699', frequency='day').process_klines(frame)
payload = result.to_dict(ownership_history='summary')
assert (payload['bi_count'], payload['xd_count'], payload['zs_count']) == (52, 6, 10)
assert len(payload['pen_consolidations']) == 4
assert any(e['type'] == 'macd' and e['curr_date'] == '2026-07-09' and e['prev_date'] == '2026-07-03' for e in payload['bcs'])
assert any(e['type'] == 'macd_wave' and e['curr_date'] == '2026-07-14' and e['confirmed_date'] == '2026-07-15' for e in payload['bcs'])
assert payload['wave_diagnostics']
computed = compute_indicators(frame, ['MACD'])
for key in ('dif', 'dea', 'hist'):
    assert list(computed[f'MACD_{key.upper()}']) == result.macd[key]

lead = json.loads(Path('/release/lead-fixture.json').read_text())
for count in (600, 800):
    rows = lead['data'][-count:]
    ks = [Kline(i, datetime.fromisoformat(r['date']), r['open'], r['close'], r['high'], r['low'], r['amount']) for i, r in enumerate(rows)]
    macd = calc_macd([b.close for b in ks], 12, 26, 9)
    date = lambda i: ks[i].date.strftime('%Y-%m-%d') if i is not None else None
    audit = []
    events = wave_events(ks, macd, diagnostics=audit)
    for signal, confirmed, start, area in [('2025-12-16', '2025-12-22', '2025-11-14', 12.6582789928),
                                          ('2026-09-11', '2026-09-16', '2026-06-26', 12.4928900854)]:
        event = next(e for e in events if e.direction == 'down' and date(e.signal_index) == signal)
        assert event.status == 'confirmed' and date(event.confirmed_index) == confirmed
        assert date(event.evidence['a_start']) == start and abs(event.evidence['a_area']-area) < 1e-8
        n = event.confirmed_index
        prefix = next(e for e in wave_events(ks[:n], {k: v[:n] for k, v in macd.items()})
                      if e.direction == 'down' and date(e.signal_index) == signal)
        assert prefix.confirmed_index is None and prefix.status == 'candidate'
    assert any(r['status'] == 'blocked' and r['rejections'] for r in audit)
print('PASS independent A/C, effective A statistics, both real cases in 600/800 bars, causal confirmation and blocked diagnostics')

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
print('PASS: reverse-pen finality, preliminary invalidation, C-end finality, whole-ABC axis, independent structural scope, frozen market, MACD precision, cutoff, provenance, 120-minute mapping')
