"""Compare only aggregate account-table changes; never emit values or identities."""
import sqlite3
import tarfile
import subprocess
import json
import hashlib
from pathlib import Path

with tarfile.open('/home/opc/backups/tdx-20261002-wave-axis/data.tar.gz') as archive:
    member = next(m for m in archive.getmembers() if m.isfile() and Path(m.name).name == 'accounts.db')
    # Stream the snapshot to SQLite 3.12 in an isolated container; no bind mounts,
    # temporary files, raw credentials or account values are emitted.
    code = '''import sys,sqlite3,json,hashlib
db=sqlite3.connect(':memory:'); db.deserialize(sys.stdin.buffer.read())
h=lambda v:hashlib.sha256(json.dumps(v,ensure_ascii=False).encode()).hexdigest()
print(json.dumps({t:{'columns':[r[1] for r in db.execute('PRAGMA table_info('+t+')')],
 'rows':{h(r[0]):[h(v) for v in r] for r in db.execute('SELECT * FROM '+t)}} for t in ('users','sessions')}))'''
    snapshot = json.loads(subprocess.check_output(['docker','run','--rm','-i','--network','none',
        '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--entrypoint','python',
        'easy-tdx:wave-axis-20261002','-c',code], input=archive.extractfile(member).read()))
    live = sqlite3.connect((Path('/var/lib/docker/volumes/easy_tdx_data/_data')/member.name).as_uri()+'?mode=ro', uri=True)
    digest = lambda v: hashlib.sha256(json.dumps(v,ensure_ascii=False).encode()).hexdigest()
    for table in ('users', 'sessions'):
        columns = snapshot[table]['columns']
        before = snapshot[table]['rows']
        after = {digest(r[0]): [digest(v) for v in r] for r in live.execute(f'SELECT * FROM {table}')}
        changed = sorted({columns[i] for key in before.keys() & after.keys()
                          for i, (a, b) in enumerate(zip(before[key], after[key])) if a != b})
        print(table, 'added=', len(after.keys()-before.keys()), 'removed=', len(before.keys()-after.keys()),
              'changed_columns=', changed)
        if table == 'users':
            assert before.keys() == after.keys()
            assert not set(changed) & {'username', 'password_hash', 'password_salt', 'role', 'active', 'created_at'}
    print('PASS account identities, credentials and roles preserved')
