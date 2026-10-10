"""Isolated synthetic browser service; no production accounts or live queries."""
import os
import tempfile
from contextlib import asynccontextmanager

_directory = tempfile.TemporaryDirectory(prefix="tdx-benchmark-qa-")
os.environ["EASY_TDX_CONFIG_DIR"] = _directory.name
os.environ.pop("EASY_TDX_ADMIN_PASSWORD", None)
os.environ.pop("EASY_TDX_SECURE_COOKIES", None)

import pandas as pd
import uvicorn
from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.app import _create_app
from easy_tdx.web import factor_benchmark
from easy_tdx.web.routers import research
from tests.unit.test_gtja191_benchmark import pair


async def fetch(_client, _mac, market, code, category, start, count, adjust):
    stock, _ = pair(length=count)
    stock["close"] += int(code[-1]) * .01
    stock.attrs["snapshot_metadata"].update(requested_adjust=adjust,actual_adjust=adjust,category=category,source="SYNTHETIC_QA",qa_note="合成验收非实盘")
    return stock


async def index(symbol, category, count, client, mac_client):
    _, frame = pair(length=count)
    market, code = symbol.split(":")
    frame.attrs["snapshot_metadata"].update(category=category,qa_note="合成验收非实盘",instrument={"kind":"index","market":market,"code":code})
    return frame


class Quotes:
    async def get_security_quotes(self, stocks):
        return pd.DataFrame([{"code":"000001","name":"合成验收非实盘","price":30}])


app = _create_app(host="127.0.0.1",enable_mac=False,enable_ex=False)
research.fetch_adjusted_bars = fetch
factor_benchmark.load_factor_benchmark = index


@asynccontextmanager
async def lifespan(app):
    app.state.tdx_client = Quotes()
    app.state.mac_client = None
    app.state.ex_client = None
    get_account_store().create_user("benchqa","Local-benchmark-qa-2026",role="admin",initial=True)
    yield


app.router.lifespan_context=lifespan
if __name__=="__main__": uvicorn.run(app,host="127.0.0.1",port=int(os.environ.get("FACTOR_QA_PORT","57855")))
