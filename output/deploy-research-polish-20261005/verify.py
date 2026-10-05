"""Read-only acceptance for the second frontend research polish release."""
import hashlib
import json
import re
import sqlite3
import subprocess
import tarfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

root = Path(__file__).resolve().parent
previous = Path('/home/opc/apps/easy_tdx-release-20261005-research-style')
backend = Path('/home/opc/apps/easy_tdx-release-20261005-instruments-v2/src/easy_tdx')
def config(folder):
    data = json.loads(subprocess.check_output(['docker', 'compose', '-p', 'easy_tdx', '-f', str(folder/'compose.yaml'), '-f', str(folder/'release-image.yaml'), 'config', '--format', 'json']))
    for service in data['services'].values():
        service.pop('image', None)
        service.pop('build', None)
    return data
assert config(root) == config(previous)
print('PASS unchanged configuration, ports, security and volume', flush=True)
files = sorted(backend.rglob('*.py'))
assert files
relative = [str(p.relative_to(backend)) for p in files]
hashes = json.loads(subprocess.check_output(['docker', 'exec', 'easy-tdx', 'python', '-c', 'import sys,json,hashlib,pathlib; r=pathlib.Path("/usr/local/lib/python3.12/site-packages/easy_tdx"); print(json.dumps({p:hashlib.sha256((r/p).read_bytes()).hexdigest() for p in sys.argv[1:]}))', *relative]))
assert all(hashes[name] == hashlib.sha256(p.read_bytes()).hexdigest() for p, name in zip(files, relative))
print(f'PASS {len(files)} backend modules unchanged', flush=True)
backup = Path('/home/opc/backups/tdx-20261005-research-polish/data.tar.gz')
checked = set()
with tarfile.open(backup) as archive:
    for member in archive.getmembers():
        if not member.isfile() or Path(member.name).name not in ('accounts.db', 'strategies.db'):
            continue
        relative = Path(member.name)
        assert not relative.is_absolute() and '..' not in relative.parts
        live = Path('/var/lib/docker/volumes/easy_tdx_data/_data')/relative
        with sqlite3.connect(live.as_uri()+'?mode=ro', uri=True) as db:
            assert db.execute('PRAGMA quick_check').fetchall() == [('ok',)]
        assert hashlib.sha256(archive.extractfile(member).read()).digest() == hashlib.sha256(live.read_bytes()).digest()
        checked.add(live.name)
assert checked == {'accounts.db', 'strategies.db'}
print('PASS account and strategy databases intact and unchanged from backup', flush=True)

def request(path):
    for attempt in range(3):
        try:
            with urlopen(Request('https://tdx.bowenv.com'+path, headers={'Cache-Control':'no-cache','User-Agent':'TDX-Deployment-Verification'}), timeout=30) as response:
                return response.read()
        except HTTPError as error:
            if error.code not in (502,503,504) or attempt == 2:
                raise
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
def normalize(data):
    text = re.sub(r'<script\b[^>]*src="https://static\.cloudflareinsights\.com/beacon\.min\.js/[^>]*></script>', '', data.decode())
    return re.sub(r'>\s+<', '><', text).strip()
for path in ('/', '/login', '/chanlun'):
    assert normalize(request(path)) == normalize((root/'dist/index.html').read_bytes())
    print('PASS public HTML', path, flush=True)
for path in sorted((root/'dist/assets').iterdir()):
    if path.name.startswith(('index-', 'ChanlunView-', 'KlineChart-', 'echarts-setup-')):
        assert hashlib.sha256(request('/assets/'+path.name)).digest() == hashlib.sha256(path.read_bytes()).digest()
        print('PASS public asset', path.name, flush=True)
status = json.loads(request('/api/v1/auth/status'))
assert not status.get('authenticated', False) and not status.get('setup_required', True)
try:
    request('/api/v1/auth/me')
except HTTPError as error:
    assert error.code == 401
else:
    raise AssertionError('Authentication required')
print('PASS health and login protection', flush=True)
