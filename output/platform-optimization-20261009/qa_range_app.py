"""Local synthetic fixture; real range/research endpoints, no production accounts."""
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from easy_tdx.web.deps import get_client, get_mac_client_optional
from easy_tdx.web.routers.bars import router as bars_router
from easy_tdx.web.routers.research import router as research_router

ROOT = Path(__file__).resolve().parents[2]


class FixtureFeed:
    async def get_stock_kline(self, market, code, period, start, count, times, **kwargs):
        dates = pd.bdate_range(end=datetime(2026, 9, 30), periods=920)
        i = np.arange(len(dates))
        price = 30 + i * .01 + np.sin(i / (5 + int(code[-1])))
        frame = pd.DataFrame(dict(datetime=dates, open=price-.1, high=price+.3,
                                  low=price-.3, close=price, vol=100000+i*100,
                                  amount=(100000+i*100)*price))
        end = len(frame) - start
        return frame.iloc[max(0, end-count):end].copy()


app = FastAPI()
feed = FixtureFeed()
app.dependency_overrides[get_client] = lambda: feed
app.dependency_overrides[get_mac_client_optional] = lambda: feed
app.include_router(bars_router, prefix='/api/v1')
app.include_router(research_router, prefix='/api/v1')
app.mount('/assets', StaticFiles(directory=ROOT/'web-ui/dist/assets'))
user = dict(id='fixture-only', username='本地模拟验收', role='admin', preferences={}, active=True)


@app.get('/api/v1/auth/status')
def status():
    return dict(user=user, authenticated=True, setup_required=False)


@app.api_route('/api/v1/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH'])
async def other(path: str, request: Request):
    if path.startswith('auth/me'):
        return {'user': user}
    return {'data': [], 'count': 0, 'strategies': []}


@app.get('/{path:path}')
def index(path: str):
    return FileResponse(ROOT/'web-ui/dist/index.html')
