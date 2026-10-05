"""HTTPS asset and real replay acceptance, without logging into an account."""
import hashlib
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from http.client import RemoteDisconnected

root = Path(__file__).resolve().parent
base = 'https://tdx.bowenv.com'
def request(path, body=None):
    req = Request(base+path, data=None if body is None else json.dumps(body).encode(),
                  headers={'User-Agent':'TDX-Deployment-Verification','Cache-Control':'no-cache',
                           'Content-Type':'application/json'})
    for attempt in range(3):
        try:
            with urlopen(req, timeout=50) as response:
                return response.read()
        except HTTPError as error:
            if error.code not in (502,503,504) or attempt == 2:
                raise
        except (URLError, RemoteDisconnected, TimeoutError):
            if attempt == 2:
                raise
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
from urllib.parse import urlencode

def check_instrument(params):
    value = json.loads(request('/api/v1/bars/research?'+urlencode(params)))
    rows, meta = value['data'], value['metadata']
    assert rows and meta['actual_adjust'] == meta['requested_adjust'] == 'NONE'
    assert meta['instrument']['kind'] == params['kind'] and meta['instrument']['code'] == params['code']
    assert all('is_closed' in row and 'period_end' in row for row in rows)
    for row in rows:
        assert row['low'] <= min(row['open'],row['close']) <= max(row['open'],row['close']) <= row['high']
        row['datetime'] = row.get('datetime',row.get('date'))
    identity = f"{params['kind']}:{meta['instrument']['market']}:{params['code']}"
    result = json.loads(request('/api/v1/chanlun/replay?ownership_history=summary',
        {'code':identity,'category':params['category'],'bars':rows,'visible_count':len(rows)}))
    assert result['code'] == identity and result['kline_count'] == len(rows)
    print('PASS live instrument + analysis',identity,params['category'],len(rows),flush=True)
    return value

for market,code in [('SH','000001'),('SZ','399001'),('SZ','399006')]:
    check_instrument(dict(kind='index',market=market,code=code,category='DAY',count=200))
check_instrument(dict(kind='index',market='SH',code='000001',category='MIN_30',count=200))
for board_type in ('HY','GN'):
    listing = json.loads(request('/api/v1/board-mac/list?'+urlencode({'board_type':board_type,'count':20})))['data']
    assert listing
    check_instrument(dict(kind='board',board_type=board_type,code=str(listing[0]['code']),category='DAY',count=200))
try:
    request('/api/v1/bars/research?kind=index&market=SH&code=000001&category=MIN_120')
except HTTPError as e:
    assert e.code == 422
else:
    raise AssertionError('Unsupported index period must not be substituted')
print('PASS unsupported period explicitly rejected',flush=True)
for code,period,category,date in [('603936','min60','MIN_60','2026-09-22 11:30'),
                                ('603259','min30','MIN_30','2026-09-29 11:30')]:
    bars = json.loads((root/f'{code}-{period}-qfq-20261003.json').read_text())['data'][-600:]
    result = json.loads(request('/api/v1/chanlun/replay?ownership_history=summary',
                       {'code':'SH'+code,'category':category,'bars':bars,'visible_count':len(bars)}))
    if code == '603936':
        e = next(e for e in result['bcs'] if e['type']=='macd_wave_special' and e['curr_date']==date)
        assert e['status']=='confirmed' and e['confirmed_date']=='2026-09-28 15:00'
        assert e['evidence']['rule_version']==2026100414
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
        assert e['evidence']['rule_version']==2026100414
    print('PASS public replay',code,category,flush=True)

for code,at,confirmed in [
    ('603936','2026-09-15 09:45','2026-09-15 13:45'),
    ('002821','2026-09-14 10:00','2026-09-14 13:15'),
    ('002821','2026-09-18 09:45','2026-09-18 11:00'),
]:
    bars = json.loads((root/f'{code}-min15-qfq-20261004.json').read_text())['data'][-600:]
    result = json.loads(request('/api/v1/chanlun/replay?ownership_history=summary',
        {'code':('SH' if code=='603936' else 'SZ')+code,'category':'MIN_15','bars':bars,'visible_count':len(bars)}))
    for family in ('macd_wave_special','macd'):
        e = next(e for e in result['bcs'] if e['type']==family and e['curr_date']==at)
        assert e['status']=='confirmed' and e['confirmed_date']==confirmed
        assert e['evidence']['rule_version']==2026100414
        assert e['evidence']['reverse_pen_local']==1
        assert e['intervals']['reverse_pen_confirmed']==confirmed
    print('PASS public local proof',code,at,confirmed,flush=True)
