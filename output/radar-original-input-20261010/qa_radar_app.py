"""Isolated actual-cookie radar QA, frozen real input, no production/network feed."""
import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import HTTPException
import pandas as pd

_directory = tempfile.TemporaryDirectory(prefix="radar-original-qa-")
os.environ["EASY_TDX_CONFIG_DIR"] = _directory.name
os.environ["EASY_TDX_TASK_BACKEND"] = "memory"
os.environ.pop("EASY_TDX_ADMIN_PASSWORD", None)
os.environ.pop("EASY_TDX_SECURE_COOKIES", None)

from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.app import _create_app
from easy_tdx.web import signal_scan, market_range, task_runner
from easy_tdx.web.strategy_store import SavedStrategy, get_store
from easy_tdx.web.task_dispatch import _scan_data
from tests.unit.test_scan_evidence import frozen

value, expected = frozen()
bars, targets = _scan_data(value)
account = get_account_store().create_user("radar-qa", "Local-radar-QA-2026!", role="admin", initial=True)
get_store().add(SavedStrategy(id="", name="原扫描均线核验", kind="single", strategy="ma_cross", strategy_label="双均线", params={"fast":7,"slow":31}, context={"symbol":"SZ:300450","category":"DAY","adjust":"QFQ"}, owner_id=account.id))
counts = {"scan_fetch": 0, "live_fetch": 0}

async def fetch_scan(*args, **kwargs):
    counts["scan_fetch"] += 1
    return bars

async def live_forbidden(*args, **kwargs):
    counts["live_fetch"] += 1
    raise HTTPException(503, "QA 禁止重取实时行情，复核必须使用原任务输入")

signal_scan.fetch_scan_bars = fetch_scan
market_range.load_equity_frame = live_forbidden
app = _create_app(host="127.0.0.1", enable_mac=False)
class NamesOnly:
    async def get_security_quotes(self, stocks):
        return pd.DataFrame([{"code": code, "name": "先导智能" if code == "300450" else code} for _, code in stocks])

app.state.tdx_client = NamesOnly()
app.state.mac_client = None
app.state.ex_client = None

@app.get("/qa/status")
def status():
    return {**counts, "bars": len(value.frames[0]), "fingerprint": value.frames[0].attrs["snapshot_metadata"]["data_fingerprint"]}

@app.post("/qa/evict")
def evict():
    runner=task_runner.get_runner()
    with runner._lock:
        for key in list(runner._tasks):
            if runner._tasks[key].status == "done":
                runner._tasks.pop(key)
    return {"removed": True}

# The production SPA catch-all precedes routes added by this isolated fixture.
qa_routes = [route for route in app.router.routes if getattr(route, "path", "").startswith("/qa/")]
for route in reversed(qa_routes):
    app.router.routes.remove(route)
    app.router.routes.insert(0, route)

@asynccontextmanager
async def isolated(_app):
    yield
    task_runner.get_runner().shutdown()

app.router.lifespan_context = isolated
