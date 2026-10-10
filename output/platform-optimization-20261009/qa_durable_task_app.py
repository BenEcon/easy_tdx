"""Isolated browser fixture: real auth/store/API, synthetic status records only."""
import os
from dataclasses import replace

from qa_security_app import app
from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_service import get_durable_store
from easy_tdx.web.task_version import execution_version

os.environ["EASY_TDX_TASK_BACKEND"] = "durable"
accounts = get_account_store()
fresh = accounts.count_users() == 0
if fresh:
    user = accounts.create_user("qa_operator", "LocalOnly-20261009", role="admin", initial=True)
    other = accounts.create_user("qa_other", "LocalOnly-20261009")
store = get_durable_store()
version = execution_version()

def record(number, description, terminal=None):
    item = TaskInput("backtest", version, {"fixture_number": number}, (), {})
    row, _ = store.submit(user.id, item, description=description)
    if terminal is not None:
        lease = store.claim(version, "fixture-no-child-started")
        if terminal == "failed":
            store.finish_after_exit(lease, error="模拟行情不足，未发布部分结果。")
        else:
            store.finish_after_exit(lease, result={"fixture_only": True})
    return row, item

if fresh:
    record(1, "均线策略 · 已完成演示记录", "done")
    record(2, "参数寻优 · 失败原因演示", "failed")
    _, value = record(3, "信号雷达 · 异常重启后重新排队（演示）")
    lease = store.claim(version, "fixture-exited-before-spawn")
    store.requeue_after_exit(lease, reason="supervisor_lost")
    store.submit(user.id, replace(value, execution_version="fixture-older-version"),
                 description="组合回测 · 等待匹配版本（演示）")
    store.submit(other.id, replace(value, execution_version="fixture-older-version"),
                 description="其他用户数据不可见")
print(f"Isolated durable UI fixture config: {accounts.db_path.parent}", flush=True)
