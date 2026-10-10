"""Production acceptance uses frozen fixtures, no live user or trading data."""
import json
import runpy
from datetime import datetime
from pathlib import Path
from easy_tdx.web.routers.chanlun_observations import StudyRequest, observations
from easy_tdx.web.routers.chanlun_replay import ReplayRequest, replay_snapshot

root=Path(__file__).parent
runpy.run_path(str(root/'prior-smoke.py'))
daily=json.loads((root/'case.json').read_text())['bars'][-160:]
request=StudyRequest(as_of=datetime(2026,10,8,15),series=[dict(code='case',category='DAY',bars=daily)],ma_periods=[5,10,20,30,60,120,250])
result=observations(request)
row=result['rows'][0]
assert result['rule_version']=='multi-period-observation-20261009'
assert row['window']['count']==20 and len(row['ma_research']['lines'])==7
assert row['direction_observation']['auxiliary']==[]
assert result['eligible_for_trading'] is False
json.dumps(result,allow_nan=False)
minute=json.loads((root/'minute.json').read_text())['data'][-80:]
cutoff=datetime.fromisoformat(minute[-1]['datetime'])
request=StudyRequest(as_of=cutoff,series=[dict(code='603936',category='MIN_60',bar_time='end',bars=minute)])
row=observations(request)['rows'][0]
assert row['bar_count']==80 and row['last_closed_at']==cutoff.isoformat(sep=' ')
before=replay_snapshot(ReplayRequest(code='603936',category='MIN_60',bars=minute,visible_count=80),ownership_history='summary')
observations(request)
after=replay_snapshot(ReplayRequest(code='603936',category='MIN_60',bars=minute,visible_count=80),ownership_history='summary')
for key in ('bis','bcs','mmds','xds'):
    assert before[key]==after[key],key
print('PASS: multi-period v2, strict structures isolated, actual close labels, seven MA parameters, snapshot JSON')
