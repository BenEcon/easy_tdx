"""Isolated SQLite and real frozen engine inputs; never connects to market nodes."""
import os
import tempfile
from contextlib import asynccontextmanager

_data = tempfile.TemporaryDirectory(prefix="portfolio-archive-qa-")
os.environ["EASY_TDX_CONFIG_DIR"] = _data.name
os.environ["EASY_TDX_TASK_BACKEND"] = "memory"
os.environ.pop("EASY_TDX_ADMIN_PASSWORD", None)
os.environ.pop("EASY_TDX_SECURE_COOKIES", None)

from fastapi import Depends, HTTPException
from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.app import _create_app
from easy_tdx.web.routers import backtest
from tests.unit.test_scan_evidence import frozen

frames = {}
for case, symbol, category in [
    ("300450-qfq-20261002", "SZ:300450", "DAY"),
    ("600699-qfq-20260929", "SH:600699", "DAY"),
    ("stock-300750-day-20261009", "SZ:300750", "DAY"),
    ("stock-300750-min_30-20261009", "SZ:300750", "MIN_30"),
]:
    frames[(symbol, category)] = frozen(case)[0].frames[0]


async def history(_client, _mac, market, code, category, adjust, start, end):
    frame = frames.get((f"{market}:{code}", category))
    if frame is None or adjust != "QFQ":
        raise HTTPException(503, "QA 未提供该冻结行情，未连接真实节点")
    return frame.copy(deep=True)


backtest._history_frame = history
get_account_store().create_user("portfolio-qa", "Local-portfolio-QA-2026!", role="admin", initial=True)
app = _create_app(host="127.0.0.1", enable_mac=False)
app.state.tdx_client = object()
app.state.mac_client = None
app.state.ex_client = None


@asynccontextmanager
async def no_network(_app):
    yield


app.router.lifespan_context = no_network

from easy_tdx.web.routers.auth import get_current_user
from easy_tdx.web.task_runner import get_runner


@app.post("/qa/evict")
def evict(user=Depends(get_current_user)):
    runner = get_runner()
    with runner._lock:
        for key in list(runner._tasks):
            row = runner._tasks[key]
            if row.status == "done" and row.owner_id == user.id:
                runner._tasks.pop(key)
    return {"ok": True}


# The production SPA fallback is already mounted; QA-only route must precede it.
app.router.routes.insert(0, app.router.routes.pop())
