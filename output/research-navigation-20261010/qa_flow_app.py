"""Local end-to-end research QA: frozen feeds, real HTTP, engines and SQLite.

No production credentials, external quotes, algorithm or final-result mocks.
"""
import os
import tempfile
from contextlib import asynccontextmanager

_directory = tempfile.TemporaryDirectory(prefix="research-flow-qa-")
os.environ["EASY_TDX_CONFIG_DIR"] = _directory.name
os.environ["EASY_TDX_TASK_BACKEND"] = "memory"
os.environ.pop("EASY_TDX_ADMIN_PASSWORD", None)
os.environ.pop("EASY_TDX_SECURE_COOKIES", None)

import pandas as pd
from fastapi import HTTPException
from easy_tdx.mac.enums import Period
from easy_tdx.web import market_data, market_range
from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.app import _create_app
from easy_tdx.web.schemas import DataFrameResponse
from tests.market_matrix import entries, load_case

frozen = {}
for entry in entries():
    if entry["id"].startswith(("stock-300750-", "index-000001-", "board-881218-")):
        _, frame, snapshot = load_case(entry)
        frame["is_closed"] = [row["is_closed"] for row in snapshot["data"]]
        frame["period_end"] = [row["period_end"] for row in snapshot["data"]]
        frozen[(entry["code"], entry["category"])] = (frame, snapshot)


async def equity(_client, _mac, market, code, category, start, count, adjust, **kwargs):
    if market != "SZ" or code != "300750" or adjust != "QFQ" or start != 0:
        raise HTTPException(503, "QA 未提供该冻结行情，不连接真实节点")
    pair = frozen.get((code, category))
    if pair is None:
        raise HTTPException(503, "QA 未提供该周期")
    frame = pair[0].copy(deep=True)
    if count < len(frame):
        raise HTTPException(503, "QA 不截短冻结输入")
    return frame


market_data.load_equity_frame = equity
market_range.load_equity_frame = equity


class FrozenClient:
    async def get_security_quotes(self, symbols):
        return pd.DataFrame([{"code": code, "name": "宁德时代" if code == "300750" else code} for _, code in symbols])

    async def get_board_list(self, **kwargs):
        return pd.DataFrame([{"code": "881218", "market": 1, "name": "汽车零部件", "board_type": 0}])

    async def get_belong_board(self, **kwargs):
        return pd.DataFrame()

    async def get_stock_kline(self, market, code, period, start, count, times, **kwargs):
        category = {Period.DAILY: "DAY", Period.WEEKLY: "WEEK", Period.MONTHLY: "MONTH", Period.MIN_30: "MIN_30"}.get(period)
        pair = frozen.get((code, category))
        if market != 1 or code not in {"000001", "881218"} or pair is None or start != 0:
            raise HTTPException(503, "QA 未提供该指数／板块行情")
        return pair[0].copy(deep=True)


get_account_store().create_user("flow-qa", "Local-flow-QA-2026!", role="admin", initial=True)
app = _create_app(host="127.0.0.1", enable_mac=False)
app.state.tdx_client = FrozenClient()
app.state.mac_client = FrozenClient()
app.state.ex_client = None


@asynccontextmanager
async def no_network(_app):
    yield


app.router.lifespan_context = no_network

# Expose expected immutable fixtures only on this isolated QA app.
from fastapi import Depends
from easy_tdx.web.routers.auth import get_current_user


@app.get("/qa/fixture/{code}/{category}")
def fixture(code: str, category: str, user=Depends(get_current_user)):
    frame, snapshot = frozen[(code, category)]
    return {"data": DataFrameResponse.from_dataframe(frame).data, "metadata": snapshot["metadata"]}


app.router.routes.insert(0, app.router.routes.pop())
