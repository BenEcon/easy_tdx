"""SQLite-backed realtime leases and token buckets shared by all web workers."""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class RealtimeLimits:
    MAX_USER_CONNECTIONS = 4
    MAX_CONNECTIONS = 64
    LEASE_SECONDS = 60
    HEARTBEAT_SECONDS = 15
    USER_BURST = 40
    USER_RATE = 1.0
    GLOBAL_BURST = 256
    GLOBAL_RATE = 8.0

    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS realtime_leases (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS realtime_owner ON realtime_leases(owner);
                CREATE TABLE IF NOT EXISTS realtime_buckets (
                    id TEXT PRIMARY KEY, tokens REAL NOT NULL, updated REAL NOT NULL
                );
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=2)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def acquire(self, owner: str) -> str | None:
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM realtime_leases WHERE expires <= ?", (now,))
            conn.execute("DELETE FROM realtime_buckets WHERE updated < ?", (now - 120,))
            total, own = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(owner = ?), 0) FROM realtime_leases", (owner,)
            ).fetchone()
            if total >= self.MAX_CONNECTIONS or own >= self.MAX_USER_CONNECTIONS:
                return None
            lease = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO realtime_leases VALUES (?, ?, ?)",
                (lease, owner, now + self.LEASE_SECONDS),
            )
            return lease

    def renew(self, lease: str) -> bool:
        now = time.time()
        with self._connect() as conn:
            # Expired workers must close, not revive a lease already replaced by another worker.
            return (
                conn.execute(
                    "UPDATE realtime_leases SET expires = ? WHERE id = ? AND expires > ?",
                    (now + self.LEASE_SECONDS, lease, now),
                ).rowcount
                == 1
            )

    def release(self, lease: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM realtime_leases WHERE id = ?", (lease,))

    def consume(self, lease: str) -> bool:
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT owner FROM realtime_leases WHERE id = ? AND expires > ?", (lease, now)
            ).fetchone()
            if row is None:
                return False
            updates = []
            for key, burst, rate in (
                (f"user:{row[0]}", self.USER_BURST, self.USER_RATE),
                ("global", self.GLOBAL_BURST, self.GLOBAL_RATE),
            ):
                previous = conn.execute(
                    "SELECT tokens, updated FROM realtime_buckets WHERE id = ?", (key,)
                ).fetchone()
                tokens = (
                    min(burst, previous[0] + max(0, now - previous[1]) * rate)
                    if previous
                    else burst
                )
                if tokens < 1:
                    return False
                updates.append((key, tokens - 1, now))
            conn.executemany("INSERT OR REPLACE INTO realtime_buckets VALUES (?, ?, ?)", updates)
            return True
