"""Persistent login limits, atomic account invariants and session revocation."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easy_tdx.web import account_store as accounts
from easy_tdx.web.account_store import AccountStore, LoginThrottled, SetupAlreadyComplete
from easy_tdx.web.errors import register_exception_handlers
from easy_tdx.web.routers.auth import router


@pytest.fixture
def store(tmp_path, monkeypatch):
    value = AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(accounts, "_store", value)
    return value


def test_setup_is_atomic_across_independent_store_instances(store):
    def initialize(index):
        other = AccountStore(store.db_path)
        try:
            return other.create_user(f"admin{index}", "test-password", "admin", initial=True)
        except SetupAlreadyComplete:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        users = list(pool.map(initialize, range(4)))
    assert sum(user is not None for user in users) == store.count_users() == 1


def test_last_admin_check_is_in_same_transaction_as_change(store):
    admins = [store.create_user(f"admin{i}", "test-password", "admin") for i in range(2)]

    def demote(user):
        try:
            AccountStore(store.db_path).update_user(user.id, role="user")
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(demote, admins))
    assert sum(results) == 1
    assert store.count_active_admins() == 1


def test_rate_limit_survives_store_recreation_normalizes_account_and_expires(store, monkeypatch):
    monkeypatch.setattr(accounts.time, "time", lambda: 1000)
    for i in range(8):
        store.reserve_login_attempt("Alice", f"peer{i}")
    with pytest.raises(LoginThrottled) as error:
        AccountStore(store.db_path).reserve_login_attempt(" ALICE ", "new-peer")
    assert error.value.retry_after == 301
    monkeypatch.setattr(accounts.time, "time", lambda: 1300)
    store.reserve_login_attempt("Alice", "peer")


def test_peer_limit_stops_username_rotation(store):
    for i in range(30):
        store.reserve_login_attempt(f"user{i}", "same-peer")
    with pytest.raises(LoginThrottled):
        store.reserve_login_attempt("different", "same-peer")


def test_installation_limit_stops_both_identity_and_peer_rotation(store):
    for i in range(200):
        store.reserve_login_attempt(f"user{i}", f"peer{i}")
    with pytest.raises(LoginThrottled):
        store.reserve_login_attempt("different", "different")


def test_concurrent_limit_reservations_cannot_overbook(store):
    def reserve(_index):
        try:
            AccountStore(store.db_path).reserve_login_attempt("alice", "same-peer")
            return True
        except LoginThrottled:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(24))) == 8


@pytest.mark.parametrize("operation", ["password", "role", "disable", "logout_all"])
def test_sensitive_changes_revoke_all_existing_sessions(store, operation):
    store.create_user("admin", "test-password", "admin")
    user = store.create_user("alice", "test-password")
    tokens = [store.create_session(user.id) for _ in range(2)]
    if operation == "password":
        store.set_password(user.id, "new-password", actor_id=user.id)
    elif operation == "role":
        store.update_user(user.id, role="admin")
    elif operation == "disable":
        store.update_user(user.id, active=False)
    else:
        store.invalidate_user_sessions(user.id)
    assert all(store.get_user_for_session(token) is None for token in tokens)


def test_unknown_account_still_performs_password_hash(store, monkeypatch):
    calls = []
    monkeypatch.setattr(accounts, "_password_digest", lambda *args: calls.append(args))
    assert store.authenticate("missing", "test-password") is None
    assert len(calls) == 1


def test_http_login_throttled_before_password_work_and_has_retry_after(store, monkeypatch):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    calls = []
    monkeypatch.setattr(store, "authenticate", lambda *args: calls.append(args))
    with TestClient(app) as client:
        for _ in range(8):
            assert (
                client.post(
                    "/api/v1/auth/login",
                    json={
                        "username": "missing",
                        "password": "wrong-password",
                    },
                ).status_code
                == 401
            )
        denied = client.post(
            "/api/v1/auth/login",
            json={
                "username": "missing",
                "password": "wrong-password",
            },
        )
        assert denied.status_code == 429
        assert int(denied.headers["retry-after"]) > 0
    assert len(calls) == 8


def test_logout_all_http_revokes_other_device_and_clears_cookie(store):
    user = store.create_user("alice", "test-password")
    token, other = store.create_session(user.id), store.create_session(user.id)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        client.cookies.set("easy_tdx_session", token)
        response = client.post("/api/v1/auth/logout-all")
        assert response.status_code == 200
        assert "Max-Age=0" in response.headers["set-cookie"]
    assert store.get_user_for_session(token) is None
    assert store.get_user_for_session(other) is None


def test_audit_records_actions_without_credentials(store):
    user = store.create_user("alice", "private-password")
    token = store.create_session(user.id)
    store.set_password(user.id, "changed-password", actor_id=user.id)
    store.audit_login(None)
    store.audit_login(user)
    with store._connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM account_audit ORDER BY id")]
    assert [row["action"] for row in rows] == ["create_user", "set_password", "login", "login"]
    assert rows[-2]["outcome"] == "denied"
    encoded = str(rows)
    assert all(secret not in encoded for secret in ("private-password", "changed-password", token))
