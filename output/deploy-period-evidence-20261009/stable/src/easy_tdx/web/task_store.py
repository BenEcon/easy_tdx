"""Transactional durable task state, separate from account and strategy stores.

Internal supervisor API only: a lease is never an HTTP authorization credential.
Callers must authenticate active accounts before owner operations. Only a
supervisor that has observed the actual child exit may call finish_after_exit
or requeue_after_exit. Heartbeat expiry alone NEVER releases or reclaims work.
This module does not start workers or replace the existing in-memory runner.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from easy_tdx.computation import ComputationStopped
from easy_tdx.web.task_audit import (
    attach_task_accounts,
    check_task_audit_mode,
    record_task_operation,
)
from easy_tdx.web.task_payload import (
    TaskInput,
    decode_task_input,
    encode_task_input,
    input_fingerprint,
)

SCHEMA_VERSION = 7
_PHASE_UNITS = ("order_signals", "pnl_trades", "equity_bars")
_ACTIVE = "('pending','running','cancelling')"
_EXECUTING = "('running','cancelling')"
_TERMINAL = frozenset({"done", "failed", "cancelled", "timed_out"})
MAX_RESULT_BYTES = 16 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 16 * 1024 * 1024
_SUMMARY_COLUMNS = (
    "id,status,description,created_at,started_at,finished_at,error,"
    "recovery_count,last_recovery_at,last_recovery_reason,version,kind,"
    "checkpoint_grid_points,resumed_grid_points,checkpoint_scan_targets,resumed_scan_targets,"
    "checkpoint_signal_bars,resumed_signal_bars,"
    "checkpoint_order_signals,resumed_order_signals,checkpoint_pnl_trades,resumed_pnl_trades,"
    "checkpoint_equity_bars,resumed_equity_bars"
)
_LEASE_COLUMNS = (
    "id,owner,fingerprint,version,kind,status,generation,lease,worker_id,heartbeat,stop_reason,"
    "guard_protocol,guard_ready,COALESCE(length(staged_result),0) AS staged_bytes,"
    "COALESCE(length(checkpoint),0) AS checkpoint_bytes,checkpoint_fingerprint,"
    "checkpoint_grid_points,checkpoint_scan_targets,checkpoint_signal_bars,"
    "checkpoint_order_signals,checkpoint_pnl_trades,checkpoint_equity_bars"
)


class TaskStoreFull(ValueError):
    """No task was admitted, or a finished result exceeded retained storage."""


class StaleTaskLease(ValueError):
    """An obsolete worker cannot read inputs, publish or release another attempt."""


@dataclass(frozen=True)
class TaskLimits:
    active: int = 16
    active_per_owner: int = 3
    executing: int = 4
    records: int = 2000
    records_per_owner: int = 200
    retained_bytes: int = 512 * 1024 * 1024
    retained_bytes_per_owner: int = 128 * 1024 * 1024

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise ValueError("任务配额必须是正整数")


@dataclass(frozen=True)
class TaskLease:
    task_id: str
    generation: int
    token: str
    worker_id: str


def _identity(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError("账户或执行者标识无效")


def _result_bytes(value: dict[str, Any]) -> bytes:
    def validate(item: Any, depth: int = 0) -> None:
        if depth > 32:
            raise ValueError("任务结果嵌套过深")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("任务结果键必须为字符串")
            for child in item.values():
                validate(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                validate(child, depth + 1)
        elif item is not None and not isinstance(item, str | bool | int | float):
            raise ValueError("任务结果包含非 JSON 类型")

    validate(value)
    buffer = BytesIO()
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for chunk in encoder.iterencode(value):
        encoded = chunk.encode()
        if buffer.tell() + len(encoded) > MAX_RESULT_BYTES:
            raise TaskStoreFull("完整结果超过单任务存储上限")
        buffer.write(encoded)
    return buffer.getvalue()


def _public(
    row: sqlite3.Row, *, result: bool = False, execution_version: str | None = None
) -> dict[str, Any]:
    """Explicit allowlist; never expose inputs, owner, worker identity or lease."""
    return {
        "task_id": row["id"],
        "status": row["status"],
        "description": row["description"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "elapsed": (row["finished_at"] or time.time()) - (row["started_at"] or row["created_at"]),
        "error": row["error"],
        "recovery_count": row["recovery_count"],
        "last_recovery_at": row["last_recovery_at"],
        "last_recovery_reason": row["last_recovery_reason"],
        "kind": row["kind"],
        "checkpoint_grid_points": row["checkpoint_grid_points"],
        "resumed_grid_points": row["resumed_grid_points"],
        "checkpoint_scan_targets": row["checkpoint_scan_targets"],
        "resumed_scan_targets": row["resumed_scan_targets"],
        "checkpoint_signal_bars": row["checkpoint_signal_bars"],
        "resumed_signal_bars": row["resumed_signal_bars"],
        **{
            f"{prefix}_{unit}": row[f"{prefix}_{unit}"]
            for unit in _PHASE_UNITS
            for prefix in ("checkpoint", "resumed")
        },
        "execution_compatible": row["version"] == execution_version
        if execution_version is not None
        else None,
        "result": json.loads(row["result"]) if result and row["result"] is not None else None,
    }


class TaskStore:
    def __init__(self, path: Path, *, limits: TaskLimits | None = None) -> None:
        self.path = path.resolve()
        self.limits = limits or TaskLimits()
        # The caller supplies an existing, privately permissioned config directory.
        # Do not silently select an account database or create arbitrary parents.
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3, 4, 5, 6, SCHEMA_VERSION):
                raise ValueError("任务库版本不兼容，请使用匹配版本或经验证的迁移")
            if version == 0:
                existing = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if existing:
                    raise ValueError("不能将已有其他用途的数据库初始化为任务库")
                conn.execute("""CREATE TABLE tasks (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    version TEXT NOT NULL, kind TEXT NOT NULL, payload BLOB NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                        ('pending','running','cancelling','done','failed','cancelled','timed_out')),
                    description TEXT NOT NULL, created_at REAL NOT NULL,
                    started_at REAL, finished_at REAL, heartbeat REAL,
                    generation INTEGER NOT NULL DEFAULT 0, lease TEXT, worker_id TEXT,
                    result BLOB, error TEXT, stop_reason TEXT,
                    retained_bytes INTEGER NOT NULL CHECK(retained_bytes >= 0))""")
                conn.execute("CREATE INDEX tasks_owner ON tasks(owner, created_at, id)")
                conn.execute("CREATE INDEX tasks_reuse ON tasks(owner, fingerprint, status)")
                conn.execute("CREATE INDEX tasks_claim ON tasks(status, version, created_at, id)")
                conn.execute(
                    "CREATE TABLE task_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO task_settings VALUES ('limits',?)",
                    (json.dumps(vars(self.limits), sort_keys=True),),
                )
                version = 1
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
            expected_columns = {
                "id",
                "owner",
                "fingerprint",
                "version",
                "kind",
                "payload",
                "status",
                "description",
                "created_at",
                "started_at",
                "finished_at",
                "heartbeat",
                "generation",
                "lease",
                "worker_id",
                "result",
                "error",
                "stop_reason",
                "retained_bytes",
            }
            if version >= 2:
                expected_columns.update({"staged_result", "staged_error", "staged_status"})
            if version >= 3:
                expected_columns.update(
                    {
                        "guard_protocol",
                        "guard_ready",
                        "recovery_count",
                        "last_recovery_at",
                        "last_recovery_reason",
                    }
                )
            if version >= 4:
                expected_columns.update(
                    {
                        "checkpoint",
                        "checkpoint_fingerprint",
                        "checkpoint_grid_points",
                        "resumed_grid_points",
                    }
                )
            if version >= 5:
                expected_columns.update({"checkpoint_scan_targets", "resumed_scan_targets"})
            if version >= 6:
                expected_columns.update({"checkpoint_signal_bars", "resumed_signal_bars"})
            if version >= 7:
                expected_columns.update(
                    f"{prefix}_{unit}"
                    for unit in _PHASE_UNITS
                    for prefix in ("checkpoint", "resumed")
                )
            if tables != {"tasks", "task_settings"} or columns != expected_columns:
                raise ValueError("任务库结构不匹配，拒绝修改现有数据库")
            policy = conn.execute("SELECT value FROM task_settings WHERE key='limits'").fetchone()
            try:
                stored_limits = TaskLimits(**json.loads(policy[0]))
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError("任务库配额配置损坏") from exc
            if limits is not None and limits != stored_limits:
                raise ValueError("任务库配额与启动配置不一致，拒绝进程间使用不同配额")
            self.limits = stored_limits
            if version == 1:
                conn.execute("ALTER TABLE tasks ADD COLUMN staged_result BLOB")
                conn.execute("ALTER TABLE tasks ADD COLUMN staged_error TEXT")
                conn.execute("ALTER TABLE tasks ADD COLUMN staged_status TEXT")
            if version < 3:
                conn.execute("ALTER TABLE tasks ADD COLUMN guard_protocol TEXT")
                conn.execute("ALTER TABLE tasks ADD COLUMN guard_ready INTEGER NOT NULL DEFAULT 0")
                conn.execute(
                    "ALTER TABLE tasks ADD COLUMN recovery_count INTEGER NOT NULL DEFAULT 0"
                )
                conn.execute("ALTER TABLE tasks ADD COLUMN last_recovery_at REAL")
                conn.execute("ALTER TABLE tasks ADD COLUMN last_recovery_reason TEXT")
            if version < 4:
                conn.execute("ALTER TABLE tasks ADD COLUMN checkpoint BLOB")
                conn.execute("ALTER TABLE tasks ADD COLUMN checkpoint_fingerprint TEXT")
                conn.execute(
                    "ALTER TABLE tasks ADD COLUMN checkpoint_grid_points INTEGER NOT NULL DEFAULT 0"
                )
                conn.execute(
                    "ALTER TABLE tasks ADD COLUMN resumed_grid_points INTEGER NOT NULL DEFAULT 0"
                )
            if version < 5:
                conn.execute(
                    "ALTER TABLE tasks ADD COLUMN checkpoint_scan_targets "
                    "INTEGER NOT NULL DEFAULT 0"
                )
                conn.execute(
                    "ALTER TABLE tasks ADD COLUMN resumed_scan_targets INTEGER NOT NULL DEFAULT 0"
                )
            if version < 6:
                conn.execute(
                    "ALTER TABLE tasks ADD COLUMN checkpoint_signal_bars INTEGER NOT NULL DEFAULT 0"
                )
                conn.execute(
                    "ALTER TABLE tasks ADD COLUMN resumed_signal_bars INTEGER NOT NULL DEFAULT 0"
                )
            if version < 7:
                for unit in _PHASE_UNITS:
                    for prefix in ("checkpoint", "resumed"):
                        conn.execute(
                            f"ALTER TABLE tasks ADD COLUMN {prefix}_{unit} "
                            "INTEGER NOT NULL DEFAULT 0"
                        )
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path.as_uri(), timeout=5, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _usage(self, conn: sqlite3.Connection, owner: str) -> sqlite3.Row:
        row: sqlite3.Row = conn.execute(
            f"SELECT COUNT(*) AS records, COALESCE(SUM(owner=?),0) AS own_records, "
            f"COALESCE(SUM(status IN {_ACTIVE}),0) AS active, "
            f"COALESCE(SUM(owner=? AND status IN {_ACTIVE}),0) AS own_active, "
            "COALESCE(SUM(retained_bytes),0) AS bytes, "
            "COALESCE(SUM(CASE WHEN owner=? THEN retained_bytes ELSE 0 END),0) AS own_bytes "
            "FROM tasks",
            (owner, owner, owner),
        ).fetchone()
        return row

    def submit(
        self, owner: str, value: TaskInput, *, description: str = "", use_cache: bool = True
    ) -> tuple[dict[str, Any], bool]:
        _identity(owner)
        if not isinstance(description, str) or len(description) > 240:
            raise ValueError("任务描述过长或类型无效")
        if type(use_cache) is not bool:
            raise ValueError("缓存选项必须是布尔值")
        payload = encode_task_input(value)
        fingerprint = input_fingerprint(payload)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # A cancellation request is not a reusable running calculation.
            reuse_states = "('pending','running','done')" if use_cache else "('pending','running')"
            old = conn.execute(
                f"SELECT {_SUMMARY_COLUMNS},NULL AS result FROM tasks "
                f"WHERE owner=? AND fingerprint=? AND status IN {reuse_states} "
                "ORDER BY CASE status WHEN 'done' THEN 1 ELSE 0 END, created_at DESC, id LIMIT 1",
                (owner, fingerprint),
            ).fetchone()
            if old is not None:
                return _public(old), True
            usage = self._usage(conn, owner)
            if (
                usage["active"] >= self.limits.active
                or usage["own_active"] >= self.limits.active_per_owner
            ):
                raise TaskStoreFull("活动任务配额已满，请等待或取消现有任务")
            if (
                usage["records"] >= self.limits.records
                or usage["own_records"] >= self.limits.records_per_owner
            ):
                raise TaskStoreFull("任务保留数量已满，请清理不再需要的已结束任务")
            if (
                usage["bytes"] + len(payload) > self.limits.retained_bytes
                or usage["own_bytes"] + len(payload) > self.limits.retained_bytes_per_owner
            ):
                raise TaskStoreFull("任务存储配额已满，未提交计算")
            task_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO tasks(id,owner,fingerprint,version,kind,payload,status,"
                "description,created_at,retained_bytes) "
                "VALUES (?,?,?,?,?,?,'pending',?,?,?)",
                (
                    task_id,
                    owner,
                    fingerprint,
                    value.execution_version,
                    value.kind,
                    payload,
                    description,
                    time.time(),
                    len(payload),
                ),
            )
            return _public(self._owned(conn, owner, task_id)), False

    @staticmethod
    def _owned(
        conn: sqlite3.Connection, owner: str, task_id: str, *, include_result: bool = False
    ) -> sqlite3.Row:
        result_column = "result" if include_result else "NULL AS result"
        row: sqlite3.Row | None = conn.execute(
            f"SELECT {_SUMMARY_COLUMNS},{result_column} FROM tasks WHERE id=? AND owner=?",
            (task_id, owner),
        ).fetchone()
        if row is None:
            raise KeyError("任务不存在")
        return row

    def get(
        self, owner: str, task_id: str, *, execution_version: str | None = None
    ) -> dict[str, Any]:
        _identity(owner)
        with self.connect() as conn:
            return _public(
                self._owned(conn, owner, task_id, include_result=True),
                result=True,
                execution_version=execution_version,
            )

    def summary(self, owner: str, task_id: str) -> dict[str, Any]:
        _identity(owner)
        with self.connect() as conn:
            return _public(self._owned(conn, owner, task_id))

    def list_tasks(
        self, owner: str, *, limit: int = 20, execution_version: str | None = None
    ) -> list[dict[str, Any]]:
        _identity(owner)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("任务列表数量必须为 1–200")
        with self.connect() as conn:
            return [
                _public(row, execution_version=execution_version)
                for row in conn.execute(
                    f"SELECT {_SUMMARY_COLUMNS},NULL AS result FROM tasks "
                    "WHERE owner=? ORDER BY created_at DESC,id DESC LIMIT ?",
                    (owner, limit),
                )
            ]

    def cancel(self, owner: str, task_id: str, *, account_db: Path | None = None) -> dict[str, Any]:
        _identity(owner)
        with self.connect() as conn:
            if account_db is not None:
                attach_task_accounts(conn, self.path, account_db)
            conn.execute("BEGIN IMMEDIATE")
            if account_db is not None:
                check_task_audit_mode(conn)
            row = self._owned(conn, owner, task_id)
            if row["status"] == "pending":
                conn.execute(
                    "UPDATE tasks SET status='cancelled',finished_at=?,"
                    "stop_reason='cancelled',checkpoint=NULL,checkpoint_fingerprint=NULL,"
                    "checkpoint_grid_points=0,checkpoint_scan_targets=0,checkpoint_signal_bars=0,"
                    "checkpoint_order_signals=0,checkpoint_pnl_trades=0,checkpoint_equity_bars=0,"
                    "retained_bytes=length(payload) WHERE id=?",
                    (time.time(), task_id),
                )
            elif row["status"] == "running":
                conn.execute(
                    "UPDATE tasks SET status='cancelling',stop_reason='cancelled' WHERE id=?",
                    (task_id,),
                )
            if account_db is not None and row["status"] in {"pending", "running"}:
                record_task_operation(conn, "task_cancel", owner, task_id)
            return _public(self._owned(conn, owner, task_id))

    def claim(
        self, execution_version: str, worker_id: str, *, guard_protocol: str | None = None
    ) -> TaskLease | None:
        _identity(execution_version)
        _identity(worker_id)
        if guard_protocol not in (None, "flock-v1"):
            raise ValueError("未知执行存活证明协议")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            executing = conn.execute(
                f"SELECT COUNT(*) FROM tasks WHERE status IN {_EXECUTING}"
            ).fetchone()[0]
            if executing >= self.limits.executing:
                return None
            row = conn.execute(
                "SELECT id,generation FROM tasks WHERE status='pending' AND version=? "
                "ORDER BY created_at,id LIMIT 1",
                (execution_version,),
            ).fetchone()
            if row is None:
                return None
            lease = TaskLease(row["id"], row["generation"] + 1, uuid.uuid4().hex, worker_id)
            now = time.time()
            conn.execute(
                "UPDATE tasks SET status='running',generation=?,lease=?,worker_id=?,"
                "started_at=?,heartbeat=?,guard_protocol=?,guard_ready=0,"
                "resumed_grid_points=0,resumed_scan_targets=0,resumed_signal_bars=0,"
                "resumed_order_signals=0,resumed_pnl_trades=0,resumed_equity_bars=0 WHERE id=?",
                (lease.generation, lease.token, worker_id, now, now, guard_protocol, lease.task_id),
            )
            return lease

    @staticmethod
    def _leased(
        conn: sqlite3.Connection, lease: TaskLease, *, include_input: bool = False
    ) -> sqlite3.Row:
        columns = _LEASE_COLUMNS + (",payload" if include_input else "")
        row: sqlite3.Row | None = conn.execute(
            f"SELECT {columns} FROM tasks WHERE id=? AND generation=? AND lease=? "
            f"AND worker_id=? AND status IN {_EXECUTING}",
            (lease.task_id, lease.generation, lease.token, lease.worker_id),
        ).fetchone()
        if row is None:
            raise StaleTaskLease("任务执行代次已失效，拒绝读取或写入")
        return row

    def load_input(self, lease: TaskLease, *, execution_version: str) -> TaskInput:
        with self.connect() as conn:
            row = self._leased(conn, lease, include_input=True)
            return decode_task_input(
                row["payload"], execution_version=execution_version, fingerprint=row["fingerprint"]
            )

    def lease_owner(self, lease: TaskLease) -> str:
        with self.connect() as conn:
            return str(self._leased(conn, lease)["owner"])

    def load_checkpoint(
        self, lease: TaskLease, *, execution_version: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        with self.connect() as conn:
            row = self._leased(conn, lease)
            if row["status"] == "cancelling":
                raise ComputationStopped(
                    "timed_out" if row["stop_reason"] == "timed_out" else "cancelled"
                )
            if row["version"] != execution_version:
                raise ValueError("检查点执行版本与冻结任务不一致")
            encoded = conn.execute(
                "SELECT checkpoint FROM tasks WHERE id=?", (lease.task_id,)
            ).fetchone()[0]
            digest = row["checkpoint_fingerprint"]
            if encoded is None:
                if digest is not None:
                    raise ValueError("检查点内容缺失，拒绝冒充从头计算")
                return None, None
            if len(encoded) > MAX_CHECKPOINT_BYTES or not isinstance(digest, str):
                raise ValueError("检查点大小或指纹无效")
            restored = decode_task_input(
                encoded, execution_version=execution_version, fingerprint=digest
            )
            if (
                restored.kind != row["kind"]
                or restored.frames
                or restored.context
                != {"task_id": lease.task_id, "input_fingerprint": row["fingerprint"]}
            ):
                raise ValueError("检查点不属于当前冻结输入")
            return restored.request, digest

    def save_checkpoint(
        self,
        lease: TaskLease,
        state: dict[str, Any],
        *,
        execution_version: str,
        previous_fingerprint: str | None,
        grid_points: int = 0,
        scan_targets: int = 0,
        signal_bars: int = 0,
        order_signals: int = 0,
        pnl_trades: int = 0,
        equity_bars: int = 0,
    ) -> str:
        """CAS + lease fencing; partial work never becomes a public result."""
        if any(
            type(count) is not int or not 0 <= count <= 100000
            for count in (grid_points, scan_targets)
        ):
            raise ValueError("检查点工作单元计数无效")
        if any(
            type(count) is not int or not 0 <= count <= 10000000
            for count in (signal_bars, order_signals, pnl_trades, equity_bars)
        ):
            raise ValueError("回测阶段检查点计数无效")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._leased(conn, lease)
            if row["status"] == "cancelling":
                raise ComputationStopped(
                    "timed_out" if row["stop_reason"] == "timed_out" else "cancelled"
                )
            if row["version"] != execution_version:
                raise ValueError("检查点执行版本与冻结任务不一致")
            if row["checkpoint_fingerprint"] != previous_fingerprint:
                raise StaleTaskLease("检查点已被更新，拒绝覆盖较新的计算状态")
            encoded = encode_task_input(
                TaskInput(
                    row["kind"],
                    execution_version,
                    state,
                    (),
                    {"task_id": lease.task_id, "input_fingerprint": row["fingerprint"]},
                )
            )
            if len(encoded) > MAX_CHECKPOINT_BYTES:
                raise TaskStoreFull("计算检查点超过单任务存储上限")
            usage = self._usage(conn, row["owner"])
            added = len(encoded) - row["checkpoint_bytes"]
            if (
                usage["bytes"] + added > self.limits.retained_bytes
                or usage["own_bytes"] + added > self.limits.retained_bytes_per_owner
            ):
                raise TaskStoreFull("计算检查点超过保留存储配额")
            digest = input_fingerprint(encoded)
            conn.execute(
                "UPDATE tasks SET checkpoint=?,checkpoint_fingerprint=?,checkpoint_grid_points=?,"
                "checkpoint_scan_targets=?,checkpoint_signal_bars=?,"
                "checkpoint_order_signals=?,checkpoint_pnl_trades=?,checkpoint_equity_bars=?,"
                "retained_bytes=retained_bytes+? WHERE id=?",
                (
                    encoded,
                    digest,
                    grid_points,
                    scan_targets,
                    signal_bars,
                    order_signals,
                    pnl_trades,
                    equity_bars,
                    added,
                    lease.task_id,
                ),
            )
            return digest

    def checkpoint_used(
        self,
        lease: TaskLease,
        fingerprint: str,
        grid_points: int,
        *,
        scan_targets: int = 0,
        signal_bars: int = 0,
        order_signals: int = 0,
        pnl_trades: int = 0,
        equity_bars: int = 0,
    ) -> None:
        """Count validated, consumed prefix points, not merely existing bytes."""
        if (
            any(
                type(count) is not int or not 0 <= count <= 100000
                for count in (grid_points, scan_targets)
            )
            or any(
                type(count) is not int or not 0 <= count <= 10000000
                for count in (signal_bars, order_signals, pnl_trades, equity_bars)
            )
            or grid_points + scan_targets + signal_bars + order_signals + pnl_trades + equity_bars
            == 0
        ):
            raise ValueError("续算工作单元计数无效")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._leased(conn, lease)
            if row["status"] == "cancelling":
                raise ComputationStopped(
                    "timed_out" if row["stop_reason"] == "timed_out" else "cancelled"
                )
            if row["checkpoint_fingerprint"] != fingerprint:
                raise StaleTaskLease("复用的检查点已变化")
            if grid_points > row["checkpoint_grid_points"]:
                raise ValueError("复用组合数不能超过已保存检查点")
            if scan_targets > row["checkpoint_scan_targets"]:
                raise ValueError("复用扫描条目数不能超过已保存检查点")
            if signal_bars > row["checkpoint_signal_bars"]:
                raise ValueError("复用信号生成 bar 数不能超过已保存检查点")
            for unit, count in zip(
                _PHASE_UNITS, (order_signals, pnl_trades, equity_bars), strict=True
            ):
                if count > row[f"checkpoint_{unit}"]:
                    raise ValueError("复用阶段计数不能超过已保存检查点")
            conn.execute(
                "UPDATE tasks SET resumed_grid_points=MAX(resumed_grid_points,?),"
                "resumed_scan_targets=MAX(resumed_scan_targets,?),"
                "resumed_signal_bars=MAX(resumed_signal_bars,?),"
                "resumed_order_signals=MAX(resumed_order_signals,?),"
                "resumed_pnl_trades=MAX(resumed_pnl_trades,?),"
                "resumed_equity_bars=MAX(resumed_equity_bars,?) WHERE id=?",
                (
                    grid_points,
                    scan_targets,
                    signal_bars,
                    order_signals,
                    pnl_trades,
                    equity_bars,
                    lease.task_id,
                ),
            )

    def guard_state(self, lease: TaskLease) -> tuple[str | None, bool]:
        with self.connect() as conn:
            row = self._leased(conn, lease)
            return row["guard_protocol"], bool(row["guard_ready"])

    def mark_guard_ready(self, lease: TaskLease) -> None:
        """Persist once before spawn; a missing ready guard is never death proof."""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._leased(conn, lease)
            if row["guard_protocol"] != "flock-v1" or row["guard_ready"]:
                raise ValueError("执行锁协议不匹配或此代次已准备启动")
            conn.execute("UPDATE tasks SET guard_ready=1 WHERE id=?", (lease.task_id,))

    def leased_tasks(self) -> list[TaskLease]:
        """No clock filter: liveness is proved by OS-held guards, not heartbeats."""
        with self.connect() as conn:
            return [
                TaskLease(row["id"], row["generation"], row["lease"], row["worker_id"])
                for row in conn.execute(
                    f"SELECT id,generation,lease,worker_id FROM tasks WHERE status IN {_EXECUTING}"
                )
            ]

    def heartbeat(self, lease: TaskLease) -> str | None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._leased(conn, lease)
            conn.execute("UPDATE tasks SET heartbeat=? WHERE id=?", (time.time(), lease.task_id))
            return str(row["stop_reason"]) if row["stop_reason"] is not None else None

    def request_timeout(self, lease: TaskLease) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._leased(conn, lease)
            if row["status"] == "running":
                conn.execute(
                    "UPDATE tasks SET status='cancelling',stop_reason='timed_out' WHERE id=?",
                    (lease.task_id,),
                )

    @staticmethod
    def _validate_outcome(result: dict[str, Any] | None, error: str | None) -> None:
        if (result is None) == (error is None):
            raise ValueError("必须且只能提供完整结果或失败原因")
        if error is not None and (not isinstance(error, str) or not error.strip()):
            raise ValueError("失败原因不能为空")
        if result is not None and not isinstance(result, dict):
            raise ValueError("任务结果必须是完整结果字典")

    def _prepare_outcome(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        result: dict[str, Any] | None,
        error: str | None,
    ) -> tuple[str, bytes | None, str | None]:
        if row["status"] == "cancelling":
            return str(row["stop_reason"]), None, None
        if error is not None:
            return "failed", None, error[:1000]
        try:
            assert result is not None
            encoded = _result_bytes(result)
            usage = self._usage(conn, row["owner"])
            added = len(encoded) - row["staged_bytes"]
            if (
                usage["bytes"] + added > self.limits.retained_bytes
                or usage["own_bytes"] + added > self.limits.retained_bytes_per_owner
            ):
                raise TaskStoreFull("完整结果超出任务存储配额")
            return "done", encoded, None
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            return "failed", None, "完整结果无法安全保存：" + str(exc)[:240]

    @staticmethod
    def _finish(
        conn: sqlite3.Connection,
        lease: TaskLease,
        status: str,
        encoded: bytes | None,
        error: str | None,
    ) -> None:
        conn.execute(
            "UPDATE tasks SET status=?,result=?,error=?,finished_at=?,lease=NULL,worker_id=NULL,"
            "staged_result=NULL,staged_error=NULL,staged_status=NULL,"
            "checkpoint=NULL,checkpoint_fingerprint=NULL,"
            "checkpoint_grid_points=0,checkpoint_scan_targets=0,checkpoint_signal_bars=0,"
            "checkpoint_order_signals=0,checkpoint_pnl_trades=0,checkpoint_equity_bars=0,"
            "retained_bytes=length(payload)+? WHERE id=?",
            (status, encoded, error, time.time(), len(encoded or b""), lease.task_id),
        )

    def finish_after_exit(
        self, lease: TaskLease, *, result: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        """Supervisor only, after exit: cancellation wins over any late result."""
        self._validate_outcome(result, error)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._leased(conn, lease)
            self._finish(conn, lease, *self._prepare_outcome(conn, row, result, error))

    def stage_result(
        self, lease: TaskLease, *, result: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        """Worker writes private outcome; this does NOT finish or release its slot."""
        self._validate_outcome(result, error)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._leased(conn, lease)
            if row["status"] == "cancelling":
                return
            status, encoded, message = self._prepare_outcome(conn, row, result, error)
            conn.execute(
                "UPDATE tasks SET staged_status=?,staged_result=?,staged_error=?,"
                "retained_bytes=length(payload)+COALESCE(length(checkpoint),0)+? WHERE id=?",
                (status, encoded, message, len(encoded or b""), lease.task_id),
            )

    def finish_staged_after_exit(self, lease: TaskLease, exit_code: int) -> None:
        """Supervisor must pass the code from wait/poll, never a guessed success."""
        if type(exit_code) is not int:
            raise ValueError("必须提供实际子进程退出码")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._leased(conn, lease)
            if row["status"] == "cancelling":
                self._finish(conn, lease, str(row["stop_reason"]), None, None)
                return
            staged = conn.execute(
                "SELECT staged_status,staged_result,staged_error FROM tasks WHERE id=?",
                (lease.task_id,),
            ).fetchone()
            if exit_code == 0 and staged["staged_status"] in {"done", "failed"}:
                self._finish(
                    conn,
                    lease,
                    staged["staged_status"],
                    staged["staged_result"],
                    staged["staged_error"],
                )
            else:
                self._finish(
                    conn,
                    lease,
                    "failed",
                    None,
                    f"计算进程退出（代码 {exit_code}），未发布完整有效结果",
                )

    def requeue_after_exit(self, lease: TaskLease, *, reason: str = "service_shutdown") -> None:
        """Supervisor verified old child death; retain validated resume material.

        Requested cancellation/timeout is finalized, never retried. A following
        claim gets a new generation and token, fencing any stale actor.
        """
        if reason not in {"service_shutdown", "supervisor_lost"}:
            raise ValueError("未知重新计算原因")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._leased(conn, lease)
            if row["status"] == "cancelling":
                self._finish(conn, lease, str(row["stop_reason"]), None, None)
            else:
                conn.execute(
                    "UPDATE tasks SET status='pending',started_at=NULL,heartbeat=NULL,"
                    "lease=NULL,worker_id=NULL,staged_status=NULL,staged_result=NULL,"
                    "staged_error=NULL,retained_bytes=length(payload)+COALESCE(length(checkpoint),0),"
                    "guard_protocol=NULL,"
                    "resumed_grid_points=0,resumed_scan_targets=0,resumed_signal_bars=0,"
                    "resumed_order_signals=0,resumed_pnl_trades=0,resumed_equity_bars=0,"
                    "guard_ready=0,recovery_count=recovery_count+1,"
                    "last_recovery_at=?,last_recovery_reason=? WHERE id=?",
                    (time.time(), reason, lease.task_id),
                )

    def stalled(self, *, before: float) -> list[TaskLease]:
        """Supervisor inspection only: no reclaim or release on stale heartbeat."""
        if (
            not isinstance(before, int | float)
            or isinstance(before, bool)
            or not math.isfinite(before)
        ):
            raise ValueError("心跳截止时间无效")
        with self.connect() as conn:
            return [
                TaskLease(row["id"], row["generation"], row["lease"], row["worker_id"])
                for row in conn.execute(
                    f"SELECT id,generation,lease,worker_id FROM tasks WHERE status IN {_EXECUTING} "
                    "AND heartbeat<? ORDER BY heartbeat,id",
                    (before,),
                )
            ]

    def delete(self, owner: str, task_id: str, *, account_db: Path | None = None) -> None:
        _identity(owner)
        with self.connect() as conn:
            if account_db is not None:
                attach_task_accounts(conn, self.path, account_db)
            conn.execute("BEGIN IMMEDIATE")
            if account_db is not None:
                check_task_audit_mode(conn)
            row = self._owned(conn, owner, task_id)
            if row["status"] not in _TERMINAL:
                raise ValueError("不能删除仍在排队、执行或取消中的任务")
            conn.execute("DELETE FROM tasks WHERE id=? AND owner=?", (task_id, owner))
            if account_db is not None:
                record_task_operation(conn, "task_delete", owner, task_id)
