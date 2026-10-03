"""Compare public HTTPS output with the built release without logging in."""
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

root = Path(__file__).resolve().parent / 'dist'
base = 'https://tdx.bowenv.com'

def get(path):
    req = Request(base + path, headers={'Cache-Control': 'no-cache', 'User-Agent': 'TDX-Deployment-Verification'})
    with urlopen(req, timeout=30) as response:
        return response.read()

html = root.joinpath('index.html').read_bytes()
def normalized_html(value):
    text = value.decode('utf-8')
    # Cloudflare may inject its existing analytics beacon depending on UA.
    # Only remove that known edge addition; application scripts remain compared.
    text = re.sub(r'<script\b[^>]*src="https://static\.cloudflareinsights\.com/beacon\.min\.js/[^>]*></script>', '', text)
    return re.sub(r'>\s+<', '><', text).strip()

for path in ('/', '/login', '/chanlun'):
    assert normalized_html(get(path)) == normalized_html(html), f'HTML mismatch: {path}'
    print('PASS HTML', path)

files = [p for p in (root/'assets').iterdir()
         if p.name.startswith(('index-', 'ChanlunView-', 'echarts-setup-', 'TechnicalIndicatorPicker-'))]
def verify(path):
    actual = get('/assets/' + path.name)
    assert hashlib.sha256(actual).digest() == hashlib.sha256(path.read_bytes()).digest(), path.name
    return 'PASS ASSET ' + path.name
with ThreadPoolExecutor(max_workers=4) as executor:
    for result in executor.map(verify, files):
        print(result)

auth = json.loads(get('/api/v1/auth/status'))
assert not auth.get('authenticated', False)
assert not auth.get('setup_required', True)
print('PASS existing account setup preserved; anonymous session not authenticated')
try:
    get('/api/v1/auth/me')
except HTTPError as exc:
    assert exc.code == 401, exc.code
    print('PASS account endpoint requires login (401)')
else:
    raise AssertionError('Account endpoint unexpectedly accessible without login')

body = {'as_of': '2026-09-30 10:00:00', 'series': [{'code': '300450', 'category': 'MIN_5', 'bars': [
    {'datetime': f'2026-09-30 09:{minute:02d}:00', 'open': 10, 'high': 11, 'low': 9,
     'close': 10.1, 'vol': 100, 'amount': 1000} for minute in (30, 35, 40, 45, 50, 55)
]}]}
req = Request(base+'/api/v1/chanlun/observations', data=json.dumps(body).encode(),
              headers={'Content-Type': 'application/json', 'User-Agent': 'TDX-Deployment-Verification'}, method='POST')
try:
    with urlopen(req, timeout=30) as response:
        result = json.load(response)
except HTTPError as exc:
    print('Public POST rejected:', exc.code, exc.headers.get('Server'), exc.read(300).decode(errors='replace'))
    raise
assert result['rows'][0]['bar_count'] == 6 and result['eligible_for_trading'] is False
print('PASS public multi-period route, cutoff and non-trading scope')

fixture = json.loads((root.parent/'lead-fixture.json').read_text())
bars = [{**r, 'datetime': r['date']} for r in fixture['data'][-600:]]
req = Request(base+'/api/v1/chanlun/replay?ownership_history=summary',
              data=json.dumps({'code': 'SZ300450', 'category': 'DAY', 'bars': bars, 'visible_count': len(bars)}).encode(),
              headers={'Content-Type': 'application/json', 'User-Agent': 'TDX-Deployment-Verification'}, method='POST')
with urlopen(req, timeout=60) as response:
    result = json.load(response)
for signal, confirmed in [('2025-12-16', '2025-12-22'), ('2026-09-11', '2026-09-16')]:
    assert any(e['type'] == 'macd_wave' and e['curr_date'] == signal and e['confirmed_date'] == confirmed
               for e in result['bcs']), signal
assert any(r['status'] == 'blocked' and r['rejections'] for r in result['wave_diagnostics'])
print('PASS public replay: both 300450 wave confirmations and explicit rejection diagnostics')
