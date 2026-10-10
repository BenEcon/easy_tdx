"""Atomic task mutations and account audit, using SQLite rollback journals.

Paths are server-owned, never HTTP input. SQLite attached commits are not
crash-atomic under WAL; reject unsupported modes rather than silently changing
live database configuration or accepting an unaudited mutation.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

from easy_tdx.web.account_store import AccountStore


def attach_task_accounts(conn: sqlite3.Connection, task_path: Path, account_path: Path) -> None:
    task_path = task_path.resolve(strict=True)
    account_path = account_path.resolve(strict=True)
    if account_path.parent != task_path.parent or account_path.samefile(task_path):
        raise sqlite3.OperationalError("任务与账户数据库必须位于同一私有配置目录且相互独立")
    # mode=rw prevents accidental creation if the configured account DB disappears.
    conn.execute("ATTACH DATABASE ? AS task_accounts", (account_path.as_uri() + "?mode=rw",))
    for schema in ("main", "task_accounts"):
        conn.execute(f"PRAGMA {schema}.synchronous=EXTRA")
        if conn.execute(f"PRAGMA {schema}.synchronous").fetchone()[0] != 3:
            raise sqlite3.OperationalError("无法启用任务审计的持久化同步保证")


def check_task_audit_mode(conn: sqlite3.Connection) -> None:
    # Check after BEGIN IMMEDIATE holds both writer reservations; checking only
    # before BEGIN would allow a concurrent WAL switch between check and write.
    for schema in ("main", "task_accounts"):
        mode = conn.execute(f"PRAGMA {schema}.journal_mode").fetchone()[0]
        if mode not in {"delete", "truncate", "persist"}:
            raise sqlite3.OperationalError("任务审计需要磁盘回滚日志模式，不支持 WAL 或内存日志")


def record_task_operation(
    conn: sqlite3.Connection,
    action: Literal["task_cancel", "task_delete"],
    owner: str,
    task_id: str,
) -> None:
    AccountStore._audit(
        conn, action, owner, None, details={"task_id": task_id}, schema="task_accounts"
    )
