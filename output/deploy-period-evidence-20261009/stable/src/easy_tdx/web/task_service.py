"""Authenticated Web bridge to the independent, durable research service.

The rollout explicitly selects durable via EASY_TDX_TASK_BACKEND. It never
silently falls back to threads if the database/worker is unavailable. Compute
workers run separately; API restarts cannot stop or own these children.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException

from easy_tdx.computation import computation_checkpoint
from easy_tdx.web.account_store import get_account_store
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_store import TaskStore
from easy_tdx.web.task_version import execution_version


def task_backend() -> Literal["memory", "durable"]:
    backend = os.environ.get("EASY_TDX_TASK_BACKEND", "memory")
    if backend not in {"memory", "durable"}:
        raise ValueError("EASY_TDX_TASK_BACKEND 必须为 memory 或 durable，拒绝静默回退")
    return "durable" if backend == "durable" else "memory"


@lru_cache(maxsize=4)
def _store(path: Path) -> TaskStore:
    return TaskStore(path)


def get_durable_store() -> TaskStore:
    # The initialized account store determines the namespace. No request may
    # select an arbitrary database path or another user's config directory.
    path = get_account_store().db_path.resolve().with_name("research-tasks.db")
    try:
        return _store(path)
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, "任务存储暂不可用，未切换到临时执行器") from exc


def submit_frozen(
    owner: str, description: str, build_input: Callable[[str], TaskInput]
) -> tuple[dict[str, Any], bool]:
    user = get_account_store().get_user(owner)
    if user is None or not user.active:
        raise HTTPException(401, "账户已失效，未提交后台计算")
    version = execution_version()
    value = build_input(version)
    computation_checkpoint()
    if value.execution_version != version:
        raise ValueError("冻结输入的执行版本不匹配")
    try:
        return get_durable_store().submit(owner, value, description=description)
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, "任务保存失败，请重新查询任务列表后重试") from exc


def read_tasks(owner: str, limit: int) -> list[dict[str, Any]]:
    try:
        return get_durable_store().list_tasks(
            owner, limit=limit, execution_version=execution_version()
        )
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, "任务列表暂不可用，请稍后重试") from exc


def read_task(owner: str, task_id: str) -> dict[str, Any]:
    try:
        return get_durable_store().get(owner, task_id, execution_version=execution_version())
    except KeyError as exc:
        raise HTTPException(404, "任务不存在或不属于当前账户") from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, "任务记录暂不可用，请稍后重试") from exc


def cancel_task(owner: str, task_id: str) -> dict[str, Any]:
    try:
        store = get_durable_store()
        state = store.cancel(owner, task_id, account_db=get_account_store().db_path)
    except KeyError as exc:
        raise HTTPException(404, "任务不存在或不属于当前账户") from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, "取消请求未确认，请重新查询任务状态") from exc
    return state


def delete_task(owner: str, task_id: str) -> None:
    try:
        get_durable_store().delete(owner, task_id, account_db=get_account_store().db_path)
    except KeyError as exc:
        raise HTTPException(404, "任务不存在或不属于当前账户") from exc
    except (sqlite3.Error, OSError) as exc:
        raise HTTPException(503, "删除结果未确认，请重新查询任务列表") from exc
