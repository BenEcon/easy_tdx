"""Only clone production SQLite; compare all original rows, never print user data."""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.strategy_store import StrategyStore

root = Path("/migration")
def quote(value):
    return '"' + value.replace('"', '""') + '"'
def digest(connection, table, columns):
    rows = connection.execute("SELECT " + ",".join(map(quote, columns)) + " FROM " + quote(table)).fetchall()
    encoded = sorted(json.dumps(row, default=str, ensure_ascii=False) for row in rows)
    return {"count": len(rows), "hash": hashlib.sha256(json.dumps(encoded).encode()).hexdigest()}

if sys.argv[1] == "clone":
    manifest = {}
    for name in ("accounts.db", "strategies.db"):
        with sqlite3.connect(f"file:/production/.easy_tdx/{name}?mode=ro", uri=True) as source, sqlite3.connect(root / name) as target:
            source.backup(target)
            assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            manifest[name] = {}
            for (table,) in target.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                columns = [row[1] for row in target.execute("PRAGMA table_info(" + quote(table) + ")")]
                manifest[name][table] = {"columns": columns, **digest(target, table, columns)}
    (root / "manifest.json").write_text(json.dumps(manifest))

AccountStore(root / "accounts.db")
StrategyStore(root / "strategies.db")
manifest = json.loads((root / "manifest.json").read_text())
for name, tables in manifest.items():
    with sqlite3.connect(root / name) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        for table, expected in tables.items():
            actual = digest(connection, table, expected["columns"])
            assert actual == {key: expected[key] for key in ("count", "hash")}, (name, table)
    print("PASS preserved all original records:", name)
print("PASS", sys.argv[1], "schema compatibility")
