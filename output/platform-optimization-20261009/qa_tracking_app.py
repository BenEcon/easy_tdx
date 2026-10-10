"""Local-only UI checks: isolated account store, real frozen market observations.

Board directory/membership are explicit UI fixtures, not production membership.
Fund quote absence is intentionally reported as an error (no substituted stock data).
"""
from fastapi import APIRouter, HTTPException
from qa_evidence_app import app, entries, load_case, CONFIG
from easy_tdx.web.account_store import AccountStore
from pathlib import Path

store = AccountStore(Path(CONFIG.name) / 'tracking-accounts.db')
first = store.create_user('tracking-qa', 'Isolated-qa-pass123!', role='admin')
second = store.create_user('other-qa', 'Isolated-qa-pass123!', role='user')
owner = first.id
qa = APIRouter(prefix='/api/v1')

@qa.get('/auth/status')
def status():
    return dict(user=store.get_user(owner).to_public_dict(), authenticated=True, setup_required=False)

@qa.get('/auth/me')
def me():
    return {'user': store.get_user(owner).to_public_dict()}

@qa.put('/auth/me/preferences')
def preferences(body: dict):
    return {'user': store.set_preferences(owner, body['preferences']).to_public_dict()}

@qa.post('/qa/switch/{identity}')
def switch(identity: str):
    global owner
    owner = second.id if identity == 'second' else first.id
    return {'ok': True}

@qa.get('/board-mac/list')
def boards():
    return {'data':[{'code':'881218','name':'测试行业（真实板块行情）','market':1},{'code':'881219','name':'测试失败板块','market':1}], 'count':2}

@qa.get('/board-mac/members')
def members(board_symbol: str, count: int):
    if count != 100000:
        raise HTTPException(400, '未请求全部成员')
    if board_symbol == '881219':
        raise HTTPException(503, 'QA：成员节点失败')
    return {'data':[{'market':0,'code':'300750','name':'宁德时代'},{'market':1,'code':'600699','name':'均胜电子'}], 'count':2}

@qa.get('/bars/research')
def research(kind: str, code: str, category: str):
    match = next((e for e in entries() if e['id'].startswith(f'{kind}-{code}-') and e['category'] == category), None)
    if not match:
        raise HTTPException(503, 'QA：无此冻结行情')
    return load_case(match)[2]

app.router.routes = qa.routes + app.router.routes
