"""Local-only fixture app: real analysis routes, no account DB and no live orders."""
import json
from pathlib import Path
from datetime import datetime, timedelta
from math import sin
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from easy_tdx.web.routers.chanlun_observations import router as study_router
from easy_tdx.web.routers.chanlun_replay import router as replay_router
from easy_tdx.web.bar_snapshot import annotate_snapshot

ROOT=Path(__file__).resolve().parents[2]
app=FastAPI()
app.include_router(study_router,prefix='/api/v1')
app.include_router(replay_router,prefix='/api/v1')
app.mount('/assets',StaticFiles(directory=ROOT/'web-ui/dist/assets'))
user=dict(id='local-qa',username='研究验收',role='admin',preferences={},active=True)

@app.get('/api/v1/auth/status')
def status():
    return dict(user=user,authenticated=True,setup_required=False)

@app.get('/api/v1/bars')
def bars(category:str='DAY'):
    # Explicit fixture data. Short enough for repeated browser QA; actual engine computes everything.
    step=timedelta(days=1) if category in ('DAY','WEEK','MONTH') else timedelta(minutes=int(category[4:]))
    end=datetime(2026,9,30,15)
    rows=[]
    for i in range(160):
        price=30+i*.015+2*sin(i/5)
        rows.append(dict(datetime=(end-step*(159-i)).isoformat(sep=' '),open=price-.1,high=price+.3,low=price-.3,close=price,vol=100000+i*100+20000*sin(i/3),amount=1000000))
    return annotate_snapshot(rows,category,source='LOCAL_QA',requested_adjust='QFQ',actual_adjust='QFQ',bar_time='end',now=datetime(2026,10,9,8))

@app.api_route('/api/v1/{path:path}',methods=['GET','POST','PATCH','PUT'])
async def other(path:str,request:Request):
    if path.startswith('auth/me'):
        return {'user':user}
    return {'data':[],'count':0}

@app.get('/{path:path}')
def index(path:str):
    return FileResponse(ROOT/'web-ui/dist/index.html')
