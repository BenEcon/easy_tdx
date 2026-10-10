"""Local isolated synthetic browser acceptance; no production data or servers."""
import os
import tempfile
from contextlib import asynccontextmanager

_directory = tempfile.TemporaryDirectory(prefix="tdx-self-qa-")
os.environ["EASY_TDX_CONFIG_DIR"] = _directory.name
os.environ.pop("EASY_TDX_ADMIN_PASSWORD", None)
os.environ.pop("EASY_TDX_SECURE_COOKIES", None)

import numpy as np
import pandas as pd
import uvicorn
from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.app import _create_app
from easy_tdx.web.bar_snapshot import annotate_snapshot
from easy_tdx.web.routers import research


async def fetch(_client, _mac, market, code, category, start, count, adjust):
    t = np.arange(count, dtype=float)
    c = 30 * np.exp(.0001 * (int(code[-2:]) + 1) * t + .05 * np.sin(t / 8))
    f = pd.DataFrame({"datetime": pd.bdate_range(end="2026-09-30", periods=count),
                      "close": c, "open": c * .998, "high": c * 1.01, "low": c * .99,
                      "vol": 1000 + 10 * t, "amount": c * 100000, "is_closed": True})
    f.attrs["snapshot_metadata"] = annotate_snapshot(
        f.to_dict("records"), category, source="SYNTHETIC_QA",
        requested_adjust=adjust, actual_adjust=adjust, bar_time="end",
    )["metadata"]
    f.attrs["snapshot_metadata"]["qa_note"] = "合成验收（非实盘）"
    return f


class Quotes:
    async def get_security_quotes(self, stocks):
        return pd.DataFrame([{"code": "000001", "name": "合成验收（非实盘）", "price": 30}])


app = _create_app(host="127.0.0.1", enable_mac=False, enable_ex=False)
research.fetch_adjusted_bars = fetch


@asynccontextmanager
async def lifespan(app):
    app.state.tdx_client = Quotes()
    app.state.mac_client = None
    app.state.ex_client = None
    get_account_store().create_user("selfqa", "Local-self-qa-2026", role="admin", initial=True)
    yield


app.router.lifespan_context = lifespan
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=57854)
