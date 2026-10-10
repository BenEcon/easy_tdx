"""Owner-scoped immutable research archives.

Data here is a client-provided archive, NOT a server-verified market snapshot.
All writes, quota reservations and revisions use one SQLite write transaction.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def get_research_archive() -> ResearchArchive:
    # Keep the archive next to the actual account database, including packaged
    # installations and tests. No process-wide cache of an old account directory.
    from easy_tdx.web.account_store import get_account_store

    return ResearchArchive(get_account_store().db_path.with_name("research_archives.db"))


class ArchiveError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class ArchiveLimits:
    object_bytes: int = 25 * 1024 * 1024
    owner_bytes: int = 128 * 1024 * 1024
    instance_bytes: int = 1024 * 1024 * 1024
    owner_items: int = 100
    owner_receipts: int = 1000
    instance_receipts: int = 10000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _text(value: Any, limit: int, field: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ArchiveError(422, f"{field}格式或长度不正确")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ArchiveError(422, f"{field}含无效 Unicode 字符") from exc
    return value


def _id(value: str) -> str:
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise ArchiveError(422, "存档 ID 必须为规范 UUID") from exc
    return value


def _dump(value: Any) -> str:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        encoded.encode("utf-8")
        return encoded
    except (TypeError, ValueError, RecursionError, OverflowError, UnicodeError) as exc:
        raise ArchiveError(422, "存档必须是完整、有限数值的 JSON") from exc


_PERIODS = {"DAY", "WEEK", "MONTH", "MIN_1", "MIN_5", "MIN_15", "MIN_30", "MIN_60", "MIN_120"}


def _archive_time(value: Any, *, clock: bool = False) -> datetime:
    if (
        not isinstance(value, str)
        or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?",
            value,
        )
        or (clock and len(value) == 10)
    ):
        raise ValueError("invalid archive time")
    offset = re.search(r"[+-](\d{2}):(\d{2})$", value)
    if offset and (int(offset[1]) > 23 or int(offset[2]) > 59):
        raise ValueError("invalid archive offset")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # Match the application's exchange-local clock, never the machine timezone.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone(timedelta(hours=8)))


def _bars(bars: Any, metadata: Any) -> None:
    if not isinstance(bars, list) or not 1 <= len(bars) <= 8000 or not isinstance(metadata, dict):
        raise ArchiveError(422, "行情或来源元信息不完整")
    prior: datetime | None = None
    for bar in bars:
        if not isinstance(bar, dict):
            raise ArchiveError(422, "行情格式不正确")
        try:
            instant = _archive_time(bar["datetime"], clock=True)
            if prior is not None and instant <= prior:
                raise ValueError
            prices = [bar[key] for key in ("open", "close", "low", "high")]
            if any(type(n) not in (int, float) or not math.isfinite(n) for n in prices):
                raise ValueError
            op, close, low, high = prices
            if low > min(op, close) or high < max(op, close):
                raise ValueError
            for key in ("vol", "amount"):
                if key in bar and (
                    type(bar[key]) not in (int, float) or not math.isfinite(bar[key])
                ):
                    raise ValueError
            if "is_closed" in bar and type(bar["is_closed"]) is not bool:
                raise ValueError
            prior = instant
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
            raise ArchiveError(422, "行情时间、顺序或 OHLC 数值不正确") from exc


def encode_archive(kind: str, payload: Any, limit: int) -> tuple[str, str]:
    encoded = _dump(payload)
    if len(encoded.encode("utf-8")) > limit:
        raise ArchiveError(413, "单份存档超过容量上限")
    if not isinstance(payload, dict):
        raise ArchiveError(422, "存档格式不正确")
    if kind in {"chart", "study"}:
        try:
            _archive_time(payload.get("cutoff" if kind == "chart" else "as_of"))
        except (ValueError, OverflowError) as exc:
            raise ArchiveError(422, "存档截止时间不正确") from exc
    if kind == "chart":
        if type(payload.get("schema")) is not int or payload["schema"] != 1:
            raise ArchiveError(422, "不支持此图表快照版本")
        _text(payload.get("title"), 500, "标题")
        _text(payload.get("cutoff"), 64, "截止时间")
        target = payload.get("target")
        if (
            not isinstance(target, dict)
            or not isinstance(target.get("kind"), str)
            or target["kind"] not in {"stock", "index", "board"}
        ):
            raise ArchiveError(422, "标的类型不正确")
        if not isinstance(payload.get("preferences"), dict) or not isinstance(
            payload.get("layers"), dict
        ):
            raise ArchiveError(422, "图表设置不完整")
        charts = payload.get("charts")
        if not isinstance(charts, list) or not 1 <= len(charts) <= 12:
            raise ArchiveError(422, "快照需包含 1 至 12 个周期")
        seen = set()
        for chart in charts:
            if (
                not isinstance(chart, dict)
                or not isinstance(chart.get("category"), str)
                or chart.get("category") not in _PERIODS
                or chart["category"] in seen
            ):
                raise ArchiveError(422, "图表周期不正确或重复")
            seen.add(chart["category"])
            _bars(chart.get("bars"), chart.get("metadata"))
            result = chart.get("result")
            if not isinstance(result, dict) or not all(
                isinstance(result.get(key), list) for key in ("bis", "xds", "zss", "bcs", "mmds")
            ):
                raise ArchiveError(422, "分析结果不完整")
    elif kind == "study":
        if payload.get("format") != "chanlun-research-snapshot-v2":
            raise ArchiveError(422, "不支持此多周期研究快照版本")
        result, series = payload.get("result"), payload.get("series")
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("rows"), list)
            or not isinstance(series, list)
            or not 1 <= len(series) <= 12
        ):
            raise ArchiveError(422, "多周期原始行情或研究结果不完整")
        periods: set[str] = set()
        for item in series:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("snapshot"), dict)
                or not isinstance(item.get("category"), str)
                or item["category"] not in _PERIODS
                or item["category"] in periods
            ):
                raise ArchiveError(422, "多周期原始行情不完整")
            periods.add(item["category"])
            _bars(item["snapshot"].get("bars"), item["snapshot"].get("metadata"))
        rows: set[str] = set()
        for row in result["rows"]:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("category"), str)
                or row["category"] not in _PERIODS
                or row["category"] in rows
                or ("error" in row and not isinstance(row["error"], str))
                or (not row.get("error") and row["category"] not in periods)
            ):
                raise ArchiveError(422, "多周期研究记录与原行情不匹配")
            rows.add(row["category"])
        if not rows:
            raise ArchiveError(422, "多周期研究未包含记录")
        _text(payload.get("as_of"), 64, "截止时间")
    else:
        raise ArchiveError(422, "未知研究存档类型")
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ResearchArchive:
    def __init__(self, path: Path, limits: ArchiveLimits | None = None) -> None:
        self.path, self.limits = path, limits or ArchiveLimits()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ArchiveError(503, "研究存档数据库版本不受支持")
            db.execute("""CREATE TABLE IF NOT EXISTS research_archives (
                owner TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
                payload TEXT, digest TEXT NOT NULL, name TEXT NOT NULL, note TEXT NOT NULL,
                size_bytes INTEGER NOT NULL, revision INTEGER NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
                state TEXT NOT NULL CHECK(state IN ('active','deleted','purged')),
                PRIMARY KEY(owner,id))""")
            db.execute(
                "CREATE TABLE IF NOT EXISTS archive_owners "
                "(owner TEXT PRIMARY KEY, revision INTEGER NOT NULL)"
            )
            db.execute("""CREATE TABLE IF NOT EXISTS archive_audit (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
                archive_id TEXT NOT NULL, action TEXT NOT NULL, revision INTEGER NOT NULL,
                occurred_at TEXT NOT NULL)""")
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _owner(owner: str) -> None:
        _text(owner, 128, "账户")

    @staticmethod
    def _row(db: sqlite3.Connection, owner: str, key: str) -> sqlite3.Row:
        row = db.execute(
            "SELECT * FROM research_archives WHERE owner=? AND id=?", (owner, key)
        ).fetchone()
        if row is None:
            raise ArchiveError(404, "存档不存在或不属于当前账户")
        assert isinstance(row, sqlite3.Row)
        return row

    @staticmethod
    def _record(row: sqlite3.Row, *, payload: bool = False) -> dict[str, Any]:
        result = {
            key: row[key]
            for key in (
                "id",
                "kind",
                "digest",
                "name",
                "note",
                "size_bytes",
                "revision",
                "created_at",
                "updated_at",
                "deleted_at",
                "state",
            )
        }
        result["provenance"] = "client_archive_not_server_verified"
        if payload:
            if row["state"] == "purged":
                raise ArchiveError(410, "存档已永久删除，不可恢复")
            if hashlib.sha256(row["payload"].encode("utf-8")).hexdigest() != row["digest"]:
                raise ArchiveError(503, "存档完整性校验失败，未返回不完整结果")
            result["payload"] = json.loads(row["payload"])
        return result

    @staticmethod
    def _changed(db: sqlite3.Connection, row: sqlite3.Row, action: str) -> None:
        db.execute(
            "INSERT INTO archive_owners VALUES (?,1) "
            "ON CONFLICT(owner) DO UPDATE SET revision=revision+1",
            (row["owner"],),
        )
        db.execute(
            "INSERT INTO archive_audit(owner,archive_id,action,revision,occurred_at) "
            "VALUES (?,?,?,?,?)",
            (row["owner"], row["id"], action, row["revision"], row["updated_at"]),
        )
        db.execute(
            "DELETE FROM archive_audit WHERE sequence <= "
            "(SELECT COALESCE(MAX(sequence),0)-5000 FROM archive_audit)"
        )

    def _quota(
        self, db: sqlite3.Connection, owner: str, delta: int, *, creating: bool = False
    ) -> None:
        own = db.execute(
            "SELECT COALESCE(SUM(size_bytes),0),COUNT(*),COALESCE(SUM(state!='purged'),0) "
            "FROM research_archives WHERE owner=?",
            (owner,),
        ).fetchone()
        all_rows = db.execute(
            "SELECT COALESCE(SUM(size_bytes),0),COUNT(*) FROM research_archives"
        ).fetchone()
        if (
            own[0] + delta > self.limits.owner_bytes
            or all_rows[0] + delta > self.limits.instance_bytes
        ):
            raise ArchiveError(413, "云端存档容量不足；回收站仍占容量，可导出后永久删除")
        if creating and (
            own[2] >= self.limits.owner_items
            or own[1] >= self.limits.owner_receipts
            or all_rows[1] >= self.limits.instance_receipts
        ):
            raise ArchiveError(413, "云端存档数量或幂等记录已达上限")

    def create(
        self, owner: str, key: str, kind: str, payload: Any, name: str, note: str = ""
    ) -> tuple[dict[str, Any], bool]:
        self._owner(owner)
        _id(key)
        _text(name, 120, "名称")
        _text(note, 4000, "备注", empty=True)
        encoded, digest = encode_archive(kind, payload, self.limits.object_bytes)
        size = len((encoded + name + note).encode("utf-8"))
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT * FROM research_archives WHERE owner=? AND id=?", (owner, key)
            ).fetchone()
            if old:
                if old["state"] == "purged":
                    raise ArchiveError(410, "存档已永久删除；请用新的 ID 创建新存档")
                if old["digest"] != digest or old["kind"] != kind:
                    raise ArchiveError(409, "同一 ID 对应不同内容，不能覆盖原始存档")
                return self._record(old), False
            self._quota(db, owner, size, creating=True)
            now = _now()
            db.execute(
                "INSERT INTO research_archives VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (owner, key, kind, encoded, digest, name, note, size, 1, now, now, None, "active"),
            )
            row = self._row(db, owner, key)
            self._changed(db, row, "create")
            return self._record(row), True

    def get(self, owner: str, key: str) -> dict[str, Any]:
        self._owner(owner)
        _id(key)
        with self._connect() as db:
            return self._record(self._row(db, owner, key), payload=True)

    def list(self, owner: str) -> dict[str, Any]:
        self._owner(owner)
        with self._connect() as db:
            db.execute("BEGIN")
            items = [
                self._record(row)
                for row in db.execute(
                    "SELECT id,kind,digest,name,note,size_bytes,revision,created_at,"
                    "updated_at,deleted_at,state FROM research_archives "
                    "WHERE owner=? AND state!='purged' ORDER BY updated_at DESC,id",
                    (owner,),
                )
            ]
            version = db.execute(
                "SELECT revision FROM archive_owners WHERE owner=?", (owner,)
            ).fetchone()
            receipts = db.execute(
                "SELECT COUNT(*) FROM research_archives WHERE owner=?", (owner,)
            ).fetchone()[0]
            return {
                "items": items,
                "revision": version[0] if version else 0,
                "quota": {
                    "used_bytes": sum(item["size_bytes"] for item in items),
                    "max_bytes": self.limits.owner_bytes,
                    "used_items": len(items),
                    "max_items": self.limits.owner_items,
                    "object_bytes": self.limits.object_bytes,
                    "used_receipts": receipts,
                    "max_receipts": self.limits.owner_receipts,
                },
            }

    def mutate(
        self,
        owner: str,
        key: str,
        revision: int,
        action: str,
        *,
        name: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        self._owner(owner)
        _id(key)
        if (
            type(revision) is not int
            or revision < 1
            or action not in {"edit", "delete", "restore", "purge"}
        ):
            raise ArchiveError(422, "操作或版本不正确")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self._row(db, owner, key)
            if old["revision"] != revision:
                raise ArchiveError(409, "存档已被其他页面修改，请刷新后重试")
            if old["state"] == "purged":
                raise ArchiveError(410, "存档已永久删除，不可恢复")
            now, state, deleted = _now(), old["state"], old["deleted_at"]
            new_name, new_note, data, size = (
                old["name"],
                old["note"],
                old["payload"],
                old["size_bytes"],
            )
            if action == "edit":
                new_name = _text(name, 120, "名称") if name is not None else new_name
                new_note = _text(note, 4000, "备注", empty=True) if note is not None else new_note
                if (new_name, new_note) == (old["name"], old["note"]):
                    return self._record(old)
                size = len((data + new_name + new_note).encode("utf-8"))
                self._quota(db, owner, size - old["size_bytes"])
            elif action == "delete":
                if state == "deleted":
                    return self._record(old)
                state, deleted = "deleted", now
            elif action == "restore":
                if state == "active":
                    return self._record(old)
                state, deleted = "active", None
            else:
                if state != "deleted":
                    raise ArchiveError(409, "必须先移入回收站，才能永久删除")
                state, data, size, new_name, new_note = "purged", None, 0, "", ""
            db.execute(
                "UPDATE research_archives SET name=?,note=?,payload=?,size_bytes=?,"
                "state=?,deleted_at=?,revision=revision+1,updated_at=? WHERE owner=? AND id=?",
                (new_name, new_note, data, size, state, deleted, now, owner, key),
            )
            row = self._row(db, owner, key)
            self._changed(db, row, action)
            return self._record(row)
