"""Isolated cookies/storage; real range endpoint and engine on frozen market bars."""
import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import HTTPException

_data = tempfile.TemporaryDirectory(prefix="saved-strategy-qa-")
os.environ["EASY_TDX_CONFIG_DIR"] = _data.name
os.environ.pop("EASY_TDX_ADMIN_PASSWORD", None)
os.environ.pop("EASY_TDX_SECURE_COOKIES", None)

from tests.market_matrix import entries, load_case
from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.app import _create_app
from easy_tdx.web import market_range

entry = next(e for e in entries() if e["id"] == "300450-qfq-20261002")
_, frame, snapshot = load_case(entry)
frame["is_closed"] = [row["is_closed"] for row in snapshot["data"]]
frame["period_end"] = [row["period_end"] for row in snapshot["data"]]


async def frozen_frame(_client, _mac, market, code, category, start, count, adjust):
    if (market, code, category, adjust) != (entry["instrument"]["market"], entry["code"], entry["category"], entry["adjust"]):
        raise HTTPException(503, "本地 QA 仅提供 300450 日线前复权冻结行情")
    end = len(frame) - start
    selected = frame.iloc[max(0, end-count):end].copy()
    selected.attrs = dict(frame.attrs)
    return selected


market_range.load_equity_frame = frozen_frame
get_account_store().create_user("saved-qa", "Local-saved-QA-only-2026!", role="admin", initial=True)
app = _create_app(host="127.0.0.1", enable_mac=False)
app.state.tdx_client = object()
app.state.mac_client = None
app.state.ex_client = None


@asynccontextmanager
async def no_network(_app):
    yield


app.router.lifespan_context = no_network
