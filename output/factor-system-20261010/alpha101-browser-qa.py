"""Local QA only: frozen real prices, disposable account, no upstream requests."""
import os
import tempfile
from contextlib import asynccontextmanager

_directory = tempfile.TemporaryDirectory(prefix="tdx-alpha101-qa-")
os.environ["EASY_TDX_CONFIG_DIR"] = _directory.name
os.environ.pop("EASY_TDX_ADMIN_PASSWORD", None)
os.environ.pop("EASY_TDX_SECURE_COOKIES", None)

import pandas as pd
import uvicorn
from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.app import _create_app
from easy_tdx.web.routers import research
from tests.unit.test_gtja191_vwap import long_frozen


async def fetch(_client, _mac, market, code, category, start, count, adjust):
    if adjust != "NONE" or str(category) not in {"DAY", "BarCategory.DAY"}:
        raise ValueError("QA仅有明确不复权日线冻结行情")
    number = 0 if str(market) in {"SZ", "Market.SZ", "0"} else 1
    frame = long_frozen(f"{number}-{code}-DAILY-NONE.json")
    if count > len(frame) or start:
        raise ValueError("QA冻结数据最多320根，未截断请求或扩展虚假行情")
    frame.attrs["snapshot_metadata"].update(requested_adjust=adjust, qa_note="真实冻结行情；非实时服务")
    return frame.iloc[-count:].copy()


class Quotes:
    async def get_security_quotes(self, stocks):
        return pd.DataFrame([{"code":"000001","name":"平安银行（冻结核验）","price":30}])


app = _create_app(host="127.0.0.1",enable_mac=False,enable_ex=False)
research.fetch_adjusted_bars = fetch


@asynccontextmanager
async def lifespan(app):
    app.state.tdx_client = Quotes()
    app.state.mac_client = None
    app.state.ex_client = None
    get_account_store().create_user("alphaqa","Local-alpha101-qa-2026",role="admin",initial=True)
    yield


app.router.lifespan_context = lifespan
if __name__ == "__main__":
    uvicorn.run(app,host="127.0.0.1",port=57859)
