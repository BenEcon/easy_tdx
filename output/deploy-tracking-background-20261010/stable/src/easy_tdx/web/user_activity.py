"""Bounded admin-only activity records. No passwords, tokens or raw bodies."""

from __future__ import annotations

import ipaddress
import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

BEIJING = timezone(timedelta(hours=8))
RETENTION_DAYS = 90
EVENT_LIMIT = 100_000


def day_key(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, BEIJING).date().isoformat()


def clean_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(address) if "%" not in value else ""
    except ValueError:
        return ""


class ActivityStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS activity_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
                  occurred REAL NOT NULL, kind TEXT NOT NULL, ip TEXT NOT NULL,
                  feature TEXT NOT NULL, outcome TEXT NOT NULL, details TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS activity_event_owner ON activity_events(owner,id);
                CREATE INDEX IF NOT EXISTS activity_event_time ON activity_events(occurred);
                CREATE TABLE IF NOT EXISTS activity_days (
                  owner TEXT NOT NULL, day TEXT NOT NULL, active_seconds INTEGER NOT NULL DEFAULT 0,
                  queries INTEGER NOT NULL DEFAULT 0, logins INTEGER NOT NULL DEFAULT 0,
                  last_seen REAL NOT NULL, PRIMARY KEY(owner,day));
                CREATE TABLE IF NOT EXISTS activity_presence (
                  owner TEXT PRIMARY KEY, last_ping REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS activity_geo (
                  ip TEXT PRIMARY KEY, result TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS activity_meta (
                  key TEXT PRIMARY KEY, value REAL NOT NULL);
            """)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _prune(db: sqlite3.Connection, now: float) -> None:
        cutoff = now - RETENTION_DAYS * 86400
        db.execute("DELETE FROM activity_events WHERE occurred < ?", (cutoff,))
        db.execute(
            "DELETE FROM activity_events WHERE id <= "
            "(SELECT COALESCE(MAX(id),0)-? FROM activity_events)",
            (EVENT_LIMIT,),
        )
        db.execute("DELETE FROM activity_days WHERE day < ?", (day_key(cutoff),))
        db.execute("DELETE FROM activity_presence WHERE last_ping < ?", (cutoff,))
        db.execute("DELETE FROM activity_geo WHERE expires < ?", (now - 86400,))

    @staticmethod
    def _day(
        db: sqlite3.Connection,
        owner: str,
        now: float,
        *,
        seconds: int = 0,
        queries: int = 0,
        logins: int = 0,
    ) -> None:
        db.execute(
            """INSERT INTO activity_days VALUES (?,?,?,?,?,?)
          ON CONFLICT(owner,day) DO UPDATE SET
          active_seconds=active_seconds+excluded.active_seconds,
          queries=queries+excluded.queries,logins=logins+excluded.logins,
          last_seen=MAX(last_seen,excluded.last_seen)""",
            (owner, day_key(now), seconds, queries, logins, now),
        )

    def heartbeat(self, owner: str, *, restart: bool = False) -> None:
        # Server clock only; one watermark per user makes multiple tabs/devices a union.
        now = int(time.time())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT last_ping FROM activity_presence WHERE owner=?", (owner,)
            ).fetchone()
            elapsed = now - int(prior[0]) if prior else 0
            if prior and elapsed < 5:
                return
            self._prune(db, now)
            seconds = min(elapsed, 30) if not restart and 0 < elapsed <= 45 else 0
            start = now - seconds
            midnight = (
                datetime.fromtimestamp(now, BEIJING)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .timestamp()
            )
            before = max(0, int(midnight - start)) if seconds else 0
            if before:
                self._day(db, owner, midnight - 1, seconds=before)
            self._day(db, owner, now, seconds=seconds - before)
            db.execute(
                "INSERT INTO activity_presence VALUES (?,?) "
                "ON CONFLICT(owner) DO UPDATE SET last_ping=excluded.last_ping",
                (owner, now),
            )

    def record(
        self,
        owner: str,
        kind: str,
        ip: str,
        feature: str,
        outcome: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        if kind not in {"login", "query"} or outcome not in {"accepted", "failed"}:
            raise ValueError("invalid activity event")
        encoded = json.dumps(details or {}, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode()) > 24_000:
            raise ValueError("activity metadata exceeds bound")
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO activity_events(owner,occurred,kind,ip,feature,outcome,details) "
                "VALUES (?,?,?,?,?,?,?)",
                (owner, now, kind, clean_ip(ip), feature[:80], outcome, encoded),
            )
            self._prune(db, now)
            self._day(db, owner, now, queries=int(kind == "query"), logins=int(kind == "login"))

    def summary(self, days: int) -> dict[str, dict[str, Any]]:
        cutoff = day_key(time.time() - (days - 1) * 86400)
        with self.connect() as db:
            rows = db.execute(
                """SELECT d.owner,SUM(active_seconds) active_seconds,SUM(queries) queries,
              SUM(logins) logins,MAX(last_seen) last_seen,MAX(p.last_ping) last_ping
              FROM activity_days d LEFT JOIN activity_presence p ON p.owner=d.owner
              WHERE day>=? GROUP BY d.owner""",
                (cutoff,),
            ).fetchall()
        return {row["owner"]: dict(row) for row in rows}

    def events(
        self,
        *,
        days: int,
        owner: str | None = None,
        kind: str | None = None,
        before: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        midnight = datetime.fromtimestamp(time.time(), BEIJING).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=days - 1)
        where = ["e.occurred>=?"]
        params: list[Any] = [midnight.timestamp()]
        for column, value in (("owner", owner), ("kind", kind)):
            if value is not None:
                where.append(f"e.{column}=?")
                params.append(value)
        if before is not None:
            where.append("e.id<?")
            params.append(before)
        with self.connect() as db:
            rows = db.execute(
                "SELECT e.*,g.result location FROM activity_events e "
                "LEFT JOIN activity_geo g ON g.ip=e.ip AND g.expires>? WHERE "
                + " AND ".join(where)
                + " ORDER BY e.id DESC LIMIT ?",
                [time.time(), *params, limit + 1],
            ).fetchall()
        items = []
        for row in rows[:limit]:
            item = dict(row)
            item["details"] = json.loads(item["details"])
            item["location"] = json.loads(item["location"]) if item["location"] else None
            items.append(item)
        return {"items": items, "next_cursor": items[-1]["id"] if len(rows) > limit else None}

    def event_ip(self, event_id: int) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT ip FROM activity_events WHERE id=? AND occurred>=?",
                (event_id, time.time() - RETENTION_DAYS * 86400),
            ).fetchone()
        return str(row[0]) if row else None

    def reserve_geo(self, ip: str) -> dict[str, Any] | None:
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT result,expires FROM activity_geo WHERE ip=?", (ip,)).fetchone()
            if row and row[1] > now:
                return dict(json.loads(row[0]))
            day = int(now // 86400)
            quota = dict(
                db.execute(
                    "SELECT key,value FROM activity_meta "
                    "WHERE key IN ('geo_day','geo_count','geo_last')"
                ).fetchall()
            )
            count = int(quota.get("geo_count", 0)) if quota.get("geo_day") == day else 0
            if count >= 500 or now - quota.get("geo_last", 0) < 1:
                return {"state": "limited", "label": "归属地查询限频，请稍后重试"}
            for key, value in (("geo_day", day), ("geo_count", count + 1), ("geo_last", now)):
                db.execute(
                    "INSERT INTO activity_meta VALUES (?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value),
                )
            pending = json.dumps(
                {"state": "pending", "label": "查询中，请稍后刷新"}, ensure_ascii=False
            )
            db.execute(
                "INSERT INTO activity_geo VALUES (?,?,?) ON CONFLICT(ip) DO UPDATE "
                "SET result=excluded.result,expires=excluded.expires",
                (ip, pending, now + 15),
            )
        return None

    def save_geo(self, ip: str, result: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        result = {**result, "checked_at": now, "source": "ipwho.is"}
        with self.connect() as db:
            db.execute(
                "INSERT INTO activity_geo VALUES (?,?,?) ON CONFLICT(ip) DO UPDATE "
                "SET result=excluded.result,expires=excluded.expires",
                (
                    ip,
                    json.dumps(result, ensure_ascii=False),
                    now + (30 * 86400 if result["state"] == "ok" else 600),
                ),
            )
        return result


@lru_cache(maxsize=8)
def _store(path: Path) -> ActivityStore:
    return ActivityStore(path)


def get_activity_store() -> ActivityStore:
    from easy_tdx.web.account_store import get_account_store

    return _store(get_account_store().db_path.with_name("user_activity.db"))
