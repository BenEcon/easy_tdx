"""Temporary account/SQLite; actual engines and task API on two frozen stocks."""
import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import HTTPException

_data = tempfile.TemporaryDirectory(prefix="portfolio-lifecycle-qa-")
os.environ["EASY_TDX_CONFIG_DIR"] = _data.name
os.environ["EASY_TDX_TASK_BACKEND"] = "memory"
os.environ.pop("EASY_TDX_ADMIN_PASSWORD", None)
os.environ.pop("EASY_TDX_SECURE_COOKIES", None)

from tests.market_matrix import entries, load_case
from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.app import _create_app
from easy_tdx.web import market_range

frames = {}
for identity in ["300450-qfq-20261002", "600699-qfq-20260929"]:
    entry = next(e for e in entries() if e["id"] == identity)
    _, frame, snapshot = load_case(entry)
    frame["is_closed"] = [r["is_closed"] for r in snapshot["data"]]
    frame["period_end"] = [r["period_end"] for r in snapshot["data"]]
    frames[(entry["instrument"]["market"], entry["code"], entry["category"], entry["adjust"])] = frame


async def frozen_frame(_client, _mac, market, code, category, start, count, adjust):
    frame = frames.get((market, code, category, adjust))
    if frame is None:
        raise HTTPException(503, "QA 只提供 300450/600699 日线前复权冻结样本")
    end = len(frame) - start
    selected = frame.iloc[max(0, end-count):end].copy()
    selected.attrs = dict(frame.attrs)
    return selected


market_range.load_equity_frame = frozen_frame
get_account_store().create_user("portfolio-qa", "Local-portfolio-QA-2026!", role="admin", initial=True)
app = _create_app(host="127.0.0.1", enable_mac=False)
app.state.tdx_client = object()
app.state.mac_client = None
app.state.ex_client = None


@asynccontextmanager
async def no_network(_app):
    yield


app.router.lifespan_context = no_network
