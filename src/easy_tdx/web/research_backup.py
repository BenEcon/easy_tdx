"""Operator-only paired research backup and isolated restore; no HTTP endpoint.

Explicit paths only. Never overwrite an existing destination or activate a
restore. Credentials in accounts.db make even a session-free backup sensitive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import uuid
from contextlib import ExitStack, closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FILES = ("accounts.db", "research_archives.db")
FORMAT = "paired-research-backup-v1"
MAX_DB_BYTES = 4 * 1024**3


class BackupError(ValueError):
    """Safe operator-facing failure, without dumping user records."""


class _Deadline:
    def __init__(self, seconds: float) -> None:
        if not 0 < seconds <= 900:
            raise BackupError("时限必须大于 0 且不超过 900 秒")
        self.end = time.monotonic() + seconds

    def remaining(self) -> float:
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise BackupError("备份或校验超时；未生成可用完成清单")
        return remaining

    def progress(self, _status: int, _remaining: int, _total: int) -> None:
        self.remaining()


def _regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise BackupError(f"{path.name} 必须是普通文件，不接受符号链接")
    if not 0 < path.stat().st_size <= MAX_DB_BYTES:
        raise BackupError(f"{path.name} 文件为空或超过 4 GiB 工具上限，未截断")


def _directory(path: Path) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise BackupError("来源必须是现有普通目录")
    return path.resolve(strict=True)


def _destination(source: Path, destination: Path) -> Path:
    parent = destination.parent.resolve(strict=True)
    target = parent / destination.name
    if target == source or source in target.parents or target in source.parents:
        raise BackupError("目标必须独立于来源目录，不能嵌套")
    # Exclusive claim. No rename-over-existing, merging or recursive deletion.
    try:
        target.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise BackupError("目标已存在；请指定新的隔离目录，未覆盖任何文件") from exc
    os.chmod(target, 0o700)
    return target


def _connect(path: Path, deadline: _Deadline, *, writable: bool = False) -> sqlite3.Connection:
    _regular(path)
    db = sqlite3.connect(
        path.as_uri() + ("?mode=rw" if writable else "?mode=ro"),
        uri=True,
        timeout=min(5.0, deadline.remaining()),
    )
    db.row_factory = sqlite3.Row
    db.enable_load_extension(False)
    db.execute("PRAGMA trusted_schema=OFF")
    db.set_progress_handler(lambda: int(time.monotonic() >= deadline.end), 10000)
    return db


def _new_file(path: Path) -> None:
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"):
        pass


def _sync(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _sync_directory(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _hash(path: Path, deadline: _Deadline) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            deadline.remaining()
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(path: Path, value: dict[str, Any]) -> None:
    # A truncated/incomplete manifest is never accepted by verify. Keep failures
    # in place for diagnosis, instead of deleting a directory the operator chose.
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(path.parent)


def _integrity(db: sqlite3.Connection) -> None:
    if [row[0] for row in db.execute("PRAGMA integrity_check")] != ["ok"]:
        raise BackupError("数据库完整性检查未通过")
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise BackupError("数据库外键检查未通过")


def _json_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise BackupError("存档 JSON 含非有限数值")
    return number


def _json_constant(_value: str) -> None:
    raise BackupError("存档 JSON 含非有限数值")


def _validate_pair(directory: Path, deadline: _Deadline) -> dict[str, int]:
    with (
        closing(_connect(directory / FILES[0], deadline)) as accounts,
        closing(_connect(directory / FILES[1], deadline)) as archives,
    ):
        _integrity(accounts)
        _integrity(archives)
        if archives.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise BackupError("研究存档版本不受支持，未尝试自动迁移")
        tables = {
            row[0] for row in accounts.execute("SELECT name FROM sqlite_schema WHERE type='table'")
        }
        if not {"users", "sessions", "auth_rate_limits", "account_audit"} <= tables:
            raise BackupError("账户库缺少必要的账户/会话/审计结构")
        columns = {row["name"] for row in accounts.execute("PRAGMA table_info(users)")}
        if (
            not {
                "id",
                "username",
                "password_hash",
                "password_salt",
                "role",
                "active",
                "preferences",
                "created_at",
                "updated_at",
                "last_login_at",
            }
            <= columns
        ):
            raise BackupError("账户库缺少登录及偏好字段")
        users = list(accounts.execute("SELECT id,role,active FROM users"))
        owners = {row["id"] for row in users}
        if not users or not any(row["role"] == "admin" and row["active"] == 1 for row in users):
            raise BackupError("账户库没有可用管理员，不能宣称可恢复")
        if any(
            row["role"] not in {"admin", "user"} or row["active"] not in {0, 1} for row in users
        ):
            raise BackupError("账户角色/启用状态不受支持")
        # Never remap an archive by username: the original immutable account ID
        # is the ownership authority, including disabled accounts and tombstones.
        for table in ("research_archives", "archive_owners", "archive_audit"):
            if any(
                row[0] not in owners
                for row in archives.execute(f"SELECT DISTINCT owner FROM {table}")
            ):
                raise BackupError("存档归属与账户库不匹配；未转交给管理员或同名账户")
        if archives.execute(
            "SELECT 1 FROM research_archives r LEFT JOIN archive_owners o ON r.owner=o.owner "
            "WHERE o.revision IS NULL OR o.revision<r.revision LIMIT 1"
        ).fetchone():
            raise BackupError("存档目录版本缺失或落后于记录版本")
        counts = {"users": len(users), "active": 0, "deleted": 0, "purged": 0, "bytes": 0}
        for row in archives.execute("SELECT * FROM research_archives"):
            deadline.remaining()
            state, payload = row["state"], row["payload"]
            if str(uuid.UUID(row["id"])) != row["id"] or row["kind"] not in {
                "chart",
                "study",
                "backtest",
                "portfolio",
                "factor",
            }:
                raise BackupError("存档身份或类型不受支持")
            if state not in {"active", "deleted", "purged"} or row["revision"] < 1:
                raise BackupError("存档状态或修订号无效")
            if not re.fullmatch(r"[a-f0-9]{64}", row["digest"]):
                raise BackupError("存档摘要格式无效")
            if state == "purged":
                if payload is not None or row["size_bytes"] != 0 or row["name"] or row["note"]:
                    raise BackupError("永久删除记录仍含正文或容量数据")
            else:
                if (
                    not isinstance(payload, str)
                    or hashlib.sha256(payload.encode()).hexdigest() != row["digest"]
                ):
                    raise BackupError("存档正文摘要不匹配，未修复或重算")
                if len((payload + row["name"] + row["note"]).encode()) != row["size_bytes"]:
                    raise BackupError("存档容量记录与原值不匹配")
                # Validate JSON without normalizing, rewriting, dropping unknown
                # fields or re-running current rules on a historical document.
                parsed = json.loads(payload, parse_float=_json_float, parse_constant=_json_constant)
                if not isinstance(parsed, dict):
                    raise BackupError("存档正文不是 JSON 对象")
            if (state == "active") != (row["deleted_at"] is None):
                raise BackupError("存档回收站时间与状态不一致")
            counts[state] += 1
            counts["bytes"] += row["size_bytes"]
        return counts


def _discard_sessions(path: Path, deadline: _Deadline) -> int:
    with closing(_connect(path, deadline, writable=True)) as db, db:
        count = int(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        db.execute("PRAGMA secure_delete=ON")
        db.execute("DELETE FROM sessions")
    return count


def create_backup(source: Path, destination: Path, *, timeout: float = 60) -> dict[str, Any]:
    """Reserve both writers, use SQLite backup (including WAL), then sanitize copies."""
    deadline, source = _Deadline(timeout), _directory(source)
    for name in FILES:
        _regular(source / name)
    target = _destination(source, destination)
    with ExitStack() as stack:
        # Keep both reservations until both read-connection backups finish.
        # Backing up a connection in its own write transaction can deadlock.
        for name in FILES:
            lock = stack.enter_context(closing(_connect(source / name, deadline, writable=True)))
            lock.execute("BEGIN IMMEDIATE")
        snapshot_at = datetime.now(timezone.utc).isoformat()
        for name in FILES:
            _new_file(target / name)
            with (
                closing(_connect(source / name, deadline)) as original,
                closing(sqlite3.connect(target / name)) as copy,
            ):
                original.backup(copy, pages=256, progress=deadline.progress, sleep=0.01)
                # A self-contained artifact: no WAL/SHM dependency after publication.
                copy.execute("PRAGMA journal_mode=DELETE")
    removed = _discard_sessions(target / FILES[0], deadline)
    counts = _validate_pair(target, deadline)
    created_at = datetime.now(timezone.utc).isoformat()
    if created_at < snapshot_at:
        raise BackupError("系统时钟在备份期间回退，未发布完成清单")
    manifest: dict[str, Any] = {
        "format": FORMAT,
        "created_at": created_at,
        "snapshot_at": snapshot_at,
        "snapshot_policy": "paired_sqlite_write_reservations",
        "scope": "accounts_and_research_archives_only",
        "sessions": "discarded",
        "discarded_sessions": removed,
        "counts": counts,
        "files": {},
    }
    for name in FILES:
        _sync(target / name)
        manifest["files"][name] = {
            "sha256": _hash(target / name, deadline),
            "bytes": (target / name).stat().st_size,
        }
    deadline.remaining()
    _write_manifest(target / "manifest.json", manifest)
    return manifest


def verify_backup(source: Path, *, timeout: float = 60) -> dict[str, Any]:
    deadline, source = _Deadline(timeout), _directory(source)
    manifest_path = source / "manifest.json"
    _regular(manifest_path)
    if manifest_path.stat().st_size > 64 * 1024:
        raise BackupError("完成清单过大")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != FORMAT
        or manifest.get("sessions") != "discarded"
        or manifest.get("scope") != "accounts_and_research_archives_only"
        or manifest.get("snapshot_policy") != "paired_sqlite_write_reservations"
        or not isinstance(manifest.get("created_at"), str)
        or not isinstance(manifest.get("snapshot_at"), str)
        or type(manifest.get("discarded_sessions")) is not int
        or manifest["discarded_sessions"] < 0
    ):
        raise BackupError("备份完成清单不受支持或缺少会话清理声明")
    try:
        created_at = datetime.fromisoformat(manifest["created_at"])
        snapshot_at = datetime.fromisoformat(manifest["snapshot_at"])
        if created_at.tzinfo is None or snapshot_at.tzinfo is None or snapshot_at > created_at:
            raise ValueError
    except ValueError as exc:
        raise BackupError("备份时间无效") from exc
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(FILES):
        raise BackupError("备份必须完整包含账户库和研究存档库")
    for name in FILES:
        path = source / name
        _regular(path)
        entry = files[name]
        if (
            not isinstance(entry, dict)
            or entry.get("bytes") != path.stat().st_size
            or entry.get("sha256") != _hash(path, deadline)
        ):
            raise BackupError("备份文件校验不匹配，未恢复")
        if any((source / (name + suffix)).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise BackupError("备份包含日志伴随文件，不是独立完成的快照")
    if _validate_pair(source, deadline) != manifest.get("counts"):
        raise BackupError("备份统计与完成清单不匹配")
    with closing(_connect(source / FILES[0], deadline)) as db:
        if db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]:
            raise BackupError("备份不应包含可恢复的登录会话")
    deadline.remaining()
    return manifest


def restore_backup(source: Path, destination: Path, *, timeout: float = 60) -> dict[str, Any]:
    """Prepare a NEW private directory. Activation/rollback require a separate decision."""
    deadline, source = _Deadline(timeout), _directory(source)
    manifest = verify_backup(source, timeout=deadline.remaining())
    target = _destination(source, destination)
    for name in FILES:
        _new_file(target / name)
        with (source / name).open("rb") as original, (target / name).open("wb") as copy:
            while chunk := original.read(1024 * 1024):
                deadline.remaining()
                copy.write(chunk)
            copy.flush()
            os.fsync(copy.fileno())
        if _hash(target / name, deadline) != manifest["files"][name]["sha256"]:
            raise BackupError("备份在复制时发生变化，未生成恢复完成报告")
    # Revalidate copied contents before treating them as an isolated restore.
    counts = _validate_pair(target, deadline)
    _discard_sessions(target / FILES[0], deadline)
    report = {
        "format": "isolated-research-restore-v1",
        "source_created_at": manifest["created_at"],
        "counts": counts,
        "activated": False,
        "sessions": "discarded",
        "scope": "accounts_and_research_archives_only",
    }
    for name in FILES:
        _sync(target / name)
    deadline.remaining()
    _write_manifest(target / "restore-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="账户＋研究存档备份；恢复仅写入新的隔离目录")
    parser.add_argument("action", choices=["create", "verify", "restore"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if (args.action == "verify") != (args.destination is None):
        parser.error("create/restore 必须提供新 destination；verify 不接受 destination")
    try:
        if args.action == "verify":
            result = verify_backup(args.source, timeout=args.timeout)
        elif args.action == "create":
            result = create_backup(args.source, args.destination, timeout=args.timeout)
        else:
            result = restore_backup(args.source, args.destination, timeout=args.timeout)
    except (BackupError, sqlite3.Error, OSError, ValueError, TypeError, KeyError) as exc:
        message = (
            str(exc)
            if isinstance(exc, BackupError)
            else "文件、数据库或清单无效；未生成有效完成报告"
        )
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "action": args.action, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
