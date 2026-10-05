"""HTTPS asset and real replay acceptance, without logging into an account."""
import hashlib
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

root = Path(__file__).resolve().parent
base = 'https://tdx.bowenv.com'
def request(path, body=None):
    req = Request(base+path, data=None if body is None else json.dumps(body).encode(),
                  headers={'User-Agent':'TDX-Deployment-Verification','Cache-Control':'no-cache',
                           'Content-Type':'application/json'})
    with urlopen(req, timeout=50) as response:
        return response.read()
def normalize(value):
    text = re.sub(r'<script\b[^>]*src="https://static\.cloudflareinsights\.com/beacon\.min\.js/[^>]*></script>', '', value.decode())
    return re.sub(r'>\s+<','><',text).strip()
for path in ('/','/login','/chanlun'):
    assert normalize(request(path)) == normalize((root/'dist/index.html').read_bytes())
    print('PASS public HTML',path,flush=True)
for p in (root/'dist/assets').iterdir():
    if p.name.startswith(('index-','ChanlunView-')):
        assert hashlib.sha256(request('/assets/'+p.name)).digest() == hashlib.sha256(p.read_bytes()).digest()
        print('PASS public asset',p.name,flush=True)
status = json.loads(request('/api/v1/auth/status'))
assert not status.get('authenticated',False) and not status.get('setup_required',True)
try:
    request('/api/v1/auth/me')
except HTTPError as e:
    assert e.code == 401
else:
    raise AssertionError('Account endpoint must require login')
print('PASS existing account setup and login requirement',flush=True)
for code,period,category,date in [('603936','min60','MIN_60','2026-09-22 11:30'),
                                ('603259','min30','MIN_30','2026-09-29 11:30')]:
    bars = json.loads((root/f'{code}-{period}-qfq-20261003.json').read_text())['data'][-600:]
    result = json.loads(request('/api/v1/chanlun/replay?ownership_history=summary',
                       {'code':'SH'+code,'category':category,'bars':bars,'visible_count':len(bars)}))
    if code == '603936':
        e = next(e for e in result['bcs'] if e['type']=='macd_wave_special' and e['curr_date']==date)
        assert e['status']=='confirmed' and e['confirmed_date']=='2026-09-28 15:00'
        assert e['evidence']['rule_version']==20261004
        assert e['intervals']['a_dif_extreme_index']=='2026-09-15 11:30'
        assert e['intervals']['a_dea_extreme_index']=='2026-09-16 11:30'
        assert abs(e['evidence']['previous_dif']-1.282777764)<1e-6
        assert abs(e['evidence']['previous_dea']-1.128720187)<1e-6
        assert not any(e['type']=='macd' and e['curr_date']==date for e in result['bcs'])
    else:
        e = next(e for e in result['bcs'] if e['type']=='macd_wave_nonstandard' and e['curr_date']==date)
        assert e['status']=='confirmed' and e['confirmed_date']=='2026-09-30 10:00'
        assert not any(e['type']=='macd_wave' and e['curr_date']==date and e['status']=='confirmed' for e in result['bcs'])
        assert abs(e['evidence']['a_area']-24.922384899472686)<1e-6
        assert e['evidence']['rule_version']==20261004
    print('PASS public replay',code,category,flush=True)
