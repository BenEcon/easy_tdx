"""Local-only UI fixture; imports isolated auth app, never production accounts."""
import time
from contextlib import asynccontextmanager

from qa_security_app import app
from easy_tdx.computation import computation_checkpoint
from easy_tdx.web.account_store import get_account_store
from easy_tdx.web import task_runner

store = get_account_store()
user = store.create_user("qa_operator", "LocalOnly-20261009", role="admin", initial=True)
for i in range(72):
    store.audit_operation("server_test", user.id, details={"node_count": 8, "reachable_count": i % 9})
runner = task_runner.BacktestTaskRunner(max_workers=1, max_active=8, max_per_owner=8)
task_runner._RUNNER = runner

def failure():
    raise ValueError("模拟数据不足，未输出部分结果")

def slow():
    while True:
        computation_checkpoint()
        time.sleep(0.1)

@asynccontextmanager
async def lifespan(_app):
    runner.submit(lambda: {"sample": True}, owner_id=user.id, description="均线策略 · 已完成验收样本")
    runner.submit(failure, owner_id=user.id, description="行情不足 · 错误状态验收")
    runner.submit(slow, owner_id=user.id, description="多策略计算 · 运行取消验收（模拟）")
    runner.submit(lambda: {}, owner_id=user.id, description="参数寻优 · 排队取消验收（模拟）")
    runner.submit(lambda: {}, owner_id="other-user", description="其他账户 · 不应显示")
    yield
    for state in runner.list_recent(100):
        runner.cancel(state.task_id)
    runner.shutdown()

app.router.lifespan_context = lifespan
