"""Temporary accounts + explicitly synthetic OHLCV; full production routes/UI."""
import os
import tempfile
from contextlib import asynccontextmanager
import numpy as np
import pandas as pd

_data=tempfile.TemporaryDirectory(prefix="factor-lab-qa-")
os.environ["EASY_TDX_CONFIG_DIR"]=_data.name
os.environ.pop("EASY_TDX_ADMIN_PASSWORD",None)
os.environ.pop("EASY_TDX_SECURE_COOKIES",None)
from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.app import _create_app
from easy_tdx.web.routers import research

async def synthetic(_client,_mac,market,code,category,start,count,adjust):
    n=int(code)%97+1
    t=np.arange(count,dtype=float)
    close=30*np.exp(.0001*n*t/97+.035*np.sin(t/(4+n%8)+n))
    frame=pd.DataFrame({"datetime":pd.bdate_range(end="2026-09-30",periods=count),"open":close*.998,"high":close*1.01,"low":close*.99,"close":close,"vol":1000+20*n+50*np.cos(t/6),"amount":close*2000,"is_closed":True})
    frame.attrs["snapshot_metadata"]={"source":"QA_SYNTHETIC","requested_adjust":adjust,"actual_adjust":adjust,"category":category,"completion_note":"明确合成行情，仅本地界面验收","volume_policy":"synthetic","historical_data_vintage":False,"observed_at":"2026-10-09T15:00:00+08:00"}
    return frame

research.fetch_adjusted_bars=synthetic
get_account_store().create_user("factor-qa","Local-factor-QA-only-2026!",role="admin",initial=True)
app=_create_app(host="127.0.0.1",enable_mac=False)
app.state.tdx_client=object()
app.state.mac_client=None
app.state.ex_client=None
@asynccontextmanager
async def no_network(_app):
    yield
app.router.lifespan_context=no_network
