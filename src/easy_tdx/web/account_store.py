"""Application accounts, password authentication and persistent sessions.

The account database deliberately lives beside the existing strategy database in
``EASY_TDX_CONFIG_DIR``. Passwords are never stored directly: PBKDF2-HMAC-SHA256
with a per-user random salt is used, while session cookies contain opaque random
tokens whose SHA-256 digest is the only value persisted in SQLite.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

__all__ = ["AccountStore", "UserRecord", "get_account_store"]

_write_lock = threading.Lock()
_PBKDF2_ITERATIONS = 390_000


def _config_dir() -> Path:
    return Path(os.environ.get("EASY_TDX_CONFIG_DIR", str(Path.home() / ".easy_tdx")))


def _default_db_path() -> Path:
    return _config_dir() / "accounts.db"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def _password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class UserRecord:
    id: str
    username: str
    role: str = "user"
    active: bool = True
    preferences: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    last_login_at: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "active": self.active,
            "preferences": self.preferences,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_login_at": self.last_login_at,
        }


class AccountStore:
    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS users (
        id              TEXT PRIMARY KEY,
        username        TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash   TEXT NOT NULL,
        password_salt   TEXT NOT NULL,
        role            TEXT NOT NULL DEFAULT 'user',
        active          INTEGER NOT NULL DEFAULT 1,
        preferences     TEXT NOT NULL DEFAULT '{}',
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL,
        last_login_at   TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
    CREATE INDEX IF NOT EXISTS idx_users_active ON users(active);

    CREATE TABLE IF NOT EXISTS sessions (
        token_hash      TEXT PRIMARY KEY,
        user_id         TEXT NOT NULL,
        created_at      TEXT NOT NULL,
        expires_at      TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
    CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _default_db_path()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(self._SCHEMA)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> UserRecord:
        try:
            preferences = json.loads(row["preferences"] or "{}")
        except json.JSONDecodeError:
            preferences = {}
        return UserRecord(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            active=bool(row["active"]),
            preferences=preferences,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_login_at=row["last_login_at"] or "",
        )

    def count_users(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"])

    def count_active_admins(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM users WHERE role = 'admin' AND active = 1"
            ).fetchone()
        return int(row["count"])

    def create_user(self, username: str, password: str, role: str = "user") -> UserRecord:
        username = username.strip()
        if not username:
            raise ValueError("用户名不能为空")
        if role not in {"admin", "user"}:
            raise ValueError("角色必须是 admin 或 user")
        salt = secrets.token_bytes(16)
        digest = _password_digest(password, salt)
        now = _iso()
        user_id = uuid.uuid4().hex[:12]
        try:
            with _write_lock, self._connect() as conn:
                conn.execute(
                    """INSERT INTO users
                       (id, username, password_hash, password_salt, role, active,
                        preferences, created_at, updated_at, last_login_at)
                       VALUES (?, ?, ?, ?, ?, 1, '{}', ?, ?, '')""",
                    (
                        user_id,
                        username,
                        base64.b64encode(digest).decode("ascii"),
                        base64.b64encode(salt).decode("ascii"),
                        role,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"用户名 '{username}' 已存在") from exc
        user = self.get_user(user_id)
        if user is None:  # pragma: no cover - defensive consistency guard
            raise RuntimeError("账户创建后读取失败")
        return user

    def get_user(self, user_id: str) -> UserRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._from_row(row) if row else None

    def get_user_by_username(self, username: str) -> UserRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username.strip(),)
            ).fetchone()
        return self._from_row(row) if row else None

    def list_users(self) -> list[UserRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END, created_at"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def authenticate(self, username: str, password: str) -> UserRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username.strip(),)
            ).fetchone()
        if row is None or not bool(row["active"]):
            return None
        salt = base64.b64decode(row["password_salt"])
        expected = base64.b64decode(row["password_hash"])
        if not hmac.compare_digest(_password_digest(password, salt), expected):
            return None
        now = _iso()
        with _write_lock, self._connect() as conn:
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, row["id"]))
        user = self.get_user(row["id"])
        return user

    def create_session(self, user_id: str, days: int = 30) -> str:
        token = secrets.token_urlsafe(36)
        created = _now()
        expires = created + timedelta(days=days)
        with _write_lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (_iso(created),))
            conn.execute(
                """INSERT INTO sessions (token_hash, user_id, created_at, expires_at)
                   VALUES (?, ?, ?, ?)""",
                (_hash_token(token), user_id, _iso(created), _iso(expires)),
            )
        return token

    def get_user_for_session(self, token: str) -> UserRecord | None:
        if not token:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """SELECT u.* FROM sessions s
                   JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1""",
                (_hash_token(token), _iso()),
            ).fetchone()
        return self._from_row(row) if row else None

    def delete_session(self, token: str) -> None:
        if not token:
            return
        with _write_lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))

    def invalidate_user_sessions(self, user_id: str) -> None:
        with _write_lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def set_password(self, user_id: str, password: str) -> None:
        salt = secrets.token_bytes(16)
        digest = _password_digest(password, salt)
        with _write_lock, self._connect() as conn:
            cur = conn.execute(
                """UPDATE users SET password_hash = ?, password_salt = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    base64.b64encode(digest).decode("ascii"),
                    base64.b64encode(salt).decode("ascii"),
                    _iso(),
                    user_id,
                ),
            )
            if cur.rowcount == 0:
                raise ValueError("账户不存在")
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def update_user(
        self, user_id: str, *, role: str | None = None, active: bool | None = None
    ) -> UserRecord:
        current = self.get_user(user_id)
        if current is None:
            raise ValueError("账户不存在")
        next_role = role if role is not None else current.role
        next_active = active if active is not None else current.active
        if next_role not in {"admin", "user"}:
            raise ValueError("角色必须是 admin 或 user")
        with _write_lock, self._connect() as conn:
            conn.execute(
                "UPDATE users SET role = ?, active = ?, updated_at = ? WHERE id = ?",
                (next_role, int(next_active), _iso(), user_id),
            )
            if not next_active:
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        updated = self.get_user(user_id)
        if updated is None:  # pragma: no cover
            raise RuntimeError("账户更新后读取失败")
        return updated

    def set_preferences(self, user_id: str, preferences: dict[str, Any]) -> UserRecord:
        encoded = json.dumps(preferences, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 64 * 1024:
            raise ValueError("偏好数据不能超过 64KB")
        with _write_lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE users SET preferences = ?, updated_at = ? WHERE id = ?",
                (encoded, _iso(), user_id),
            )
            if cur.rowcount == 0:
                raise ValueError("账户不存在")
        updated = self.get_user(user_id)
        if updated is None:  # pragma: no cover
            raise RuntimeError("偏好保存后读取失败")
        return updated


_store: AccountStore | None = None
_store_lock = threading.Lock()


def get_account_store() -> AccountStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = AccountStore()
                password = os.environ.get("EASY_TDX_ADMIN_PASSWORD", "")
                if password and _store.count_users() == 0:
                    username = os.environ.get("EASY_TDX_ADMIN_USERNAME", "admin").strip() or "admin"
                    admin = _store.create_user(username, password, role="admin")
                    from easy_tdx.web.strategy_store import get_store

                    get_store().claim_unowned(admin.id)
    return _store
