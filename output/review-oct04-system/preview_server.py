"""Local-only observation endpoint for UI acceptance; no quote/user services."""
from fastapi import FastAPI
from unittest.mock import AsyncMock
import pandas as pd
from easy_tdx.web.routers.chanlun_observations import router
from easy_tdx.web.routers import bars, board_mac, chanlun_replay

app = FastAPI()
app.include_router(router, prefix='/api/v1')
for extra in (bars.router, board_mac.router, chanlun_replay.router):
    app.include_router(extra, prefix='/api/v1')
frame = pd.DataFrame([
    {'datetime': pd.Timestamp('2025-01-06') + pd.Timedelta(days=i),
     'open': 10+i*.1, 'high': 12+i*.1, 'low': 9+i*.1, 'close': 11+i*.1, 'vol': 100+i, 'amount': 1000}
    for i in range(40)
])
standard, mac = AsyncMock(), AsyncMock()
standard.get_index_bars.return_value = frame
mac.get_stock_kline.return_value = frame
mac.get_board_list.return_value = pd.DataFrame([
    {'code':'881155','market':90,'name':'银行'}, {'code':'881156','market':90,'name':'半导体'},
])
app.state.tdx_client = standard
app.state.mac_client = mac

@app.get('/api/v1/auth/status')
def auth():
    return {'setup_required':False,'user':{'id':999,'username':'本地验收','role':'user','preferences':{}}}

@app.post('/api/v1/indicator/compute')
def indicators():
    return {'data': []}
