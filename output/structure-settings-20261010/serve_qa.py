"""Loopback-only synthetic UI acceptance; no accounts, market or production access."""
from pathlib import Path
import pandas as pd
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from easy_tdx.web.routers.chanlun_replay import router as replay
from easy_tdx.web.routers.chanlun_observations import router as study
from easy_tdx.web.bar_snapshot import annotate_snapshot

root = Path(__file__).resolve().parents[2]
app = FastAPI()
app.include_router(replay, prefix='/api/v1')
app.include_router(study, prefix='/api/v1')
user = dict(id='structure-qa',username='模拟验收',role='admin',active=True,preferences={},tracking_allowed=True)

@app.get('/api/v1/auth/status')
def status():
    return dict(user=user, authenticated=True, setup_required=False)

@app.get('/api/v1/bars')
def bars(category: str='DAY', adjust: str='QFQ', count: int=600):
    freq = 'D' if category == 'DAY' else '30min'
    rows = [dict(datetime=str(t),open=20+i%16,close=20+i%16,low=19+i%16,high=21+i%16,vol=100+i,amount=2000)
            for i,t in enumerate(pd.date_range('2026-01-01',periods=min(count,160),freq=freq))]
    snapshot = annotate_snapshot(rows, category, source='QA_SYNTHETIC', requested_adjust=adjust,
                                 actual_adjust=adjust, bar_time='end')
    return snapshot

@app.api_route('/api/v1/{path:path}',methods=['GET','POST','PUT','PATCH'])
def stub(path: str, request: Request):
    if path.startswith('chanlun/replay') or path=='chanlun/observations':
        raise AssertionError('Unrouted computation')
    return dict(user=user,active=True,role='admin',data=[],items=[],tasks=[],count=0)

app.mount('/assets',StaticFiles(directory=root/'web-ui/dist/assets'))
@app.get('/{path:path}')
def spa(path: str):
    return FileResponse(root/'web-ui/dist/index.html')

if __name__=='__main__':
    uvicorn.run(app,host='127.0.0.1',port=8773)
