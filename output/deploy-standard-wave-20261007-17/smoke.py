"""Offline production-image acceptance; no account data or live market writes."""
import json
from datetime import datetime
from pathlib import Path
from easy_tdx.chanlun.types import Kline
from easy_tdx.chanlun.macd import calc_macd
from easy_tdx.chanlun.divergence_signals import wave_events, special_wave_events, link_wave_families
from easy_tdx.chanlun.analyser import ChanlunResult

rows=json.loads(Path(__file__).with_name('case.json').read_text())['bars'][-600:]
bars=[Kline(i,datetime.fromisoformat(r['datetime']),r['open'],r['close'],r['high'],r['low'],r.get('amount',0)) for i,r in enumerate(rows)]
macd=calc_macd([b.close for b in bars],12,26,9)
at=next(i for i,b in enumerate(bars) if str(b.date.date())=='2026-09-16')
audits=[]
events=wave_events(bars,macd,diagnostics=audits)+special_wave_events(bars,macd)
link_wave_families(events,bars)
target=next(e for e in events if e.bc_type.value=='macd_wave' and e.signal_index==at)
assert target.confirmed_index==at+1 and target.evidence['rule_version']==2026100717
assert abs(target.evidence['price']-17.80)<1e-6 and target.evidence['legacy_standard_passed']==0
assert target.related_events
assert not any(e.signal_index==at for e in wave_events(bars,macd,legacy_standard=True))
early=next(e for e in wave_events(bars[:at+1],{k:v[:at+1] for k,v in macd.items()}) if e.signal_index==at)
assert early.status=='candidate' and early.confirmed_index is None
payload=ChanlunResult(klines=bars,bcs=events,wave_diagnostics=audits).to_dict()
assert any(c['mode']=='legacy_standard' for a in payload['wave_diagnostics'] for c in a['comparisons'])
json.dumps(payload,allow_nan=False)
print('PASS production image: Sep16 17.80 candidate; Sep17 confirmation; legacy blocked; related special preserved; JSON valid')
