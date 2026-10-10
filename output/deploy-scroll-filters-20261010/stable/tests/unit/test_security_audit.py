"""Audit schema migration, administrator access and stable filtered pagination."""

import asyncio
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from easy_tdx.web import account_store as accounts
from easy_tdx.web.account_store import AccountStore, UserRecord
from easy_tdx.web.routers import auth, server


@pytest.fixture
def store(tmp_path, monkeypatch):
    value = AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(accounts, "_store", value)
    return value


def test_audit_migration_preserves_old_events_and_users(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(AccountStore._SCHEMA)
        conn.execute(
            "INSERT INTO account_audit (occurred_at,action,outcome) VALUES (?,?,?)",
            ("2026-10-09T00:00:00Z", "login", "denied"),
        )
    migrated = AccountStore(path)
    user = migrated.create_user("alice", "test-password")
    again = AccountStore(path)
    rows = again.list_audit()["items"]
    assert len(rows) == 2
    assert rows[-1]["action"] == "login"
    assert rows[-1]["details"] == {}
    assert again.get_user(user.id).username == "alice"


def test_filter_and_cursor_do_not_duplicate_when_new_events_arrive(store):
    user = store.create_user("alice", "test-password")
    for _ in range(6):
        store.audit_login(user)
    page = store.list_audit(action="login", outcome="success", limit=2)
    store.audit_login(user)
    following = store.list_audit(
        action="login", outcome="success", limit=2, before=page["next_cursor"]
    )
    ids = [item["id"] for item in [*page["items"], *following["items"]]]
    assert len(ids) == len(set(ids)) == 4
    assert ids == sorted(ids, reverse=True)
    assert all(item["actor_name"] == "alice" for item in page["items"])
    assert store.list_audit(action="login", outcome="denied")["items"] == []
    assert store.list_audit(before=1)["next_cursor"] is None


def test_role_change_details_and_sanitized_operation_fields(store):
    user = store.create_user("alice", "test-password")
    store.update_user(user.id, role="admin", actor_id=user.id)
    event = store.list_audit(action="update_user")["items"][0]
    assert event["details"] == {
        "role_before": "user",
        "role_after": "admin",
        "active_before": True,
        "active_after": True,
    }
    with pytest.raises(ValueError):
        store.audit_operation("server_test", user.id, details={"password": "never-store"})
    with pytest.raises(ValueError):
        store.audit_operation("server_test", user.id, details={"node_after": "x" * 5000})


def test_audit_retention_is_bounded(store):
    with store._connect() as conn:
        conn.executemany(
            "INSERT INTO account_audit (occurred_at,action,outcome) VALUES (?,?,?)",
            [("2026-10-09T00:00:00Z", "login", "denied")] * 10010,
        )
    store.audit_login(None)
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM account_audit").fetchone()[0] == 10000


def test_audit_http_requires_admin_and_bounds_pagination(store):
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    member = store.create_user("member", "test-password")
    admin = store.create_user("admin", "test-password", "admin")
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/audit").status_code == 401
        client.cookies.set(auth.SESSION_COOKIE, store.create_session(member.id))
        assert client.get("/api/v1/admin/audit").status_code == 403
        client.cookies.set(auth.SESSION_COOKIE, store.create_session(admin.id))
        assert client.get("/api/v1/admin/audit").status_code == 200
        for query in ("limit=101", "limit=0", "before=0", "outcome=secret", "action=login%27"):
            assert client.get(f"/api/v1/admin/audit?{query}").status_code == 422


@pytest.mark.asyncio
async def test_disconnected_probe_holds_slot_and_audits_actual_completion(store, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def probe(*_args):
        started.set()
        assert release.wait(5)
        return [("node-a", 0.01)]

    monkeypatch.setattr(server, "ping_all", probe)
    monkeypatch.setattr(server, "get_known_hosts", lambda: ["node-a"])
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(tdx_client=None)))
    admin = UserRecord(id="admin", username="admin", role="admin")
    caller = asyncio.create_task(server.test_hosts(server.ServerTestRequest(), request, admin))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        with pytest.raises(HTTPException) as error:
            await server.test_hosts(server.ServerTestRequest(), request, admin)
        assert error.value.status_code == 429
    finally:
        release.set()
        await request.app.state.server_probe_task
    records = store.list_audit(action="server_test")["items"]
    assert len(records) == 1
    assert records[0]["details"] == {"node_count": 1, "reachable_count": 1}


@pytest.mark.asyncio
async def test_disconnected_switch_finishes_persistence_and_audit(store, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    persisted = []

    class Client:
        _host = "node-a"

        async def reconnect_to(self, host):
            started.set()
            await release.wait()
            self._host = host

    client = Client()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(tdx_client=client)))
    monkeypatch.setattr(server, "get_known_hosts", lambda: ["node-a", "node-b"])
    monkeypatch.setattr(server, "save_best_host", persisted.append)
    admin = UserRecord(id="admin", username="admin", role="admin")
    command = server.ServerSwitchRequest(host="node-b")
    caller = asyncio.create_task(server.switch_host(command, request, admin))
    await started.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    with pytest.raises(HTTPException) as error:
        await server.switch_host(command, request, admin)
    assert error.value.status_code == 429
    release.set()
    assert (await request.app.state.server_switch_task).ok
    assert persisted == ["node-b"]
    assert store.list_audit(action="server_switch")["items"][0]["details"] == {
        "node_before": "node-a",
        "node_after": "node-b",
    }
