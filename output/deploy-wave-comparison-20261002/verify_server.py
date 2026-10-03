"""Read-only release, config and database checks; never print account data."""
import hashlib
import json
import sqlite3
import subprocess
import tarfile
from pathlib import Path

release = Path('/home/opc/apps/easy_tdx-release-20261002-wave-comparison')
previous = Path('/home/opc/apps/easy_tdx-release-20261002-wave-axis')
backup = Path('/home/opc/backups/tdx-20261002-wave-comparison/data.tar.gz')
volume = Path('/var/lib/docker/volumes/easy_tdx_data/_data')

def config(root):
    value = json.loads(subprocess.check_output(['docker', 'compose', '-p', 'easy_tdx',
        '-f', str(root/'compose.yaml'), '-f', str(root/'release-image.yaml'), 'config', '--format', 'json']))
    for service in value['services'].values():
        service.pop('image', None)
        service.pop('build', None)
    return value

assert config(release) == config(previous)
print('PASS unchanged runtime configuration, security limits and data volume')
files = sorted((release/'src/easy_tdx').rglob('*.py'))
remote = json.loads(subprocess.check_output(['docker', 'exec', 'easy-tdx', 'python', '-c',
    'import sys,json,hashlib,pathlib; root=pathlib.Path("/usr/local/lib/python3.12/site-packages/easy_tdx"); print(json.dumps({p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in sys.argv[1:]}))',
    *[str(p.relative_to(release/'src/easy_tdx')) for p in files]]))
assert all(remote[str(p.relative_to(release/'src/easy_tdx'))] == hashlib.sha256(p.read_bytes()).hexdigest() for p in files)
print(f'PASS {len(files)} deployed Python modules match release bytes')

checked = []
with tarfile.open(backup) as archive:
    for member in archive.getmembers():
        if not member.isfile() or Path(member.name).name not in ('accounts.db', 'strategies.db'):
            continue
        relative = Path(member.name)
        assert not relative.is_absolute() and '..' not in relative.parts
        live = volume/relative
        with sqlite3.connect(live.as_uri()+'?mode=ro', uri=True) as connection:
            assert connection.execute('PRAGMA quick_check').fetchall() == [('ok',)]
        identical = hashlib.sha256(archive.extractfile(member).read()).digest() == hashlib.sha256(live.read_bytes()).digest()
        checked.append(live.name)
        print(f'PASS {live.name}: integrity ok; identical to pre-release backup={identical}')
assert set(checked) == {'accounts.db', 'strategies.db'}
assert backup.stat().st_mode & 0o777 == 0o600
print('PASS recoverable data backup exists with mode 600')
