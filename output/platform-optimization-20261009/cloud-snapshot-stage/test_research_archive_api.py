"""Real cookie authentication and revocation, independent archive database."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from research_archive import ResearchArchive
from research_archive_router import build_router
from test_research_archive import payload

from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.request_security import RequestSecurityMiddleware
from easy_tdx.web.routers import auth


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    accounts = AccountStore(tmp_path / "accounts.db")
    alice = accounts.create_user("Alice", "Isolated-test-password!", role="user")
    bob = accounts.create_user("Bob", "Isolated-test-password!", role="user")
    admin = accounts.create_user("Admin", "Isolated-test-password!", role="admin")
    sessions = {user.username: accounts.create_session(user.id) for user in (alice, bob, admin)}
    monkeypatch.setattr(auth, "get_account_store", lambda: accounts)
    store = ResearchArchive(tmp_path / "archive.db")
    app = FastAPI()
    app.add_middleware(RequestSecurityMiddleware, allowed_origins=[], max_body=26 * 1024 * 1024)
    app.include_router(build_router(lambda: store, auth.get_current_user), prefix="/api/v1")
    with TestClient(app) as client:
        yield client, accounts, sessions, alice, store


def login(client, sessions, name="Alice"):
    client.cookies.set(auth.SESSION_COOKIE, sessions[name])


def create(client, key=None):
    key = key or str(uuid.uuid4())
    return key, client.put(
        f"/api/v1/research/archives/{key}",
        json={"kind": "chart", "payload": payload(), "name": "云端观察"},
    )


@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("get", "", None),
        ("get", "/record", None),
        ("put", "/record", {}),
        ("post", "/record/actions", {}),
    ],
)
def test_all_routes_require_session(app_client, method, suffix, body):
    client, *_ = app_client
    assert (
        client.request(method, "/api/v1/research/archives" + suffix, json=body).status_code == 401
    )


def test_cookie_owner_isolation_and_admin_has_no_override(app_client):
    client, _, sessions, _, _ = app_client
    login(client, sessions)
    key, response = create(client)
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    for actor in ["Bob", "Admin"]:
        login(client, sessions, actor)
        assert client.get("/api/v1/research/archives").json()["items"] == []
        for method, suffix, data in [
            ("get", "", None),
            ("post", "/actions", {"action": "delete", "revision": 1}),
        ]:
            res = client.request(method, f"/api/v1/research/archives/{key}{suffix}", json=data)
            assert res.status_code == 404
            absent = client.request(
                method, f"/api/v1/research/archives/{uuid.uuid4()}{suffix}", json=data
            )
            assert absent.json() == res.json()


def test_conflicting_devices_and_recycle_bin_over_http(app_client):
    client, _, sessions, _, _ = app_client
    login(client, sessions)
    key, created = create(client)
    base = f"/api/v1/research/archives/{key}"
    assert create(client, key)[1].status_code == 200
    changed = client.post(
        base + "/actions", json={"action": "edit", "revision": 1, "note": "另一设备编辑"}
    )
    assert changed.status_code == 200 and changed.json()["revision"] == 2
    assert (
        client.post(base + "/actions", json={"action": "delete", "revision": 1}).status_code == 409
    )
    deleted = client.post(base + "/actions", json={"action": "delete", "revision": 2})
    assert deleted.json()["state"] == "deleted"
    assert client.get(base).json()["payload"] == payload()
    restored = client.post(base + "/actions", json={"action": "restore", "revision": 3})
    assert restored.json()["state"] == "active"
    assert client.get(base).headers["etag"] == '"4"'


def test_revoked_session_cannot_read_or_mutate_archive(app_client):
    client, accounts, sessions, alice, _ = app_client
    login(client, sessions)
    key, _ = create(client)
    accounts.invalidate_user_sessions(alice.id)
    assert client.get(f"/api/v1/research/archives/{key}").status_code == 401
    assert (
        client.post(
            f"/api/v1/research/archives/{key}/actions", json={"action": "delete", "revision": 1}
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "extra",
    [{"owner": "bob"}, {"name": "bad", "action": "restore"}, {"revision": True}, {"revision": "1"}],
)
def test_owner_injection_and_invalid_mutations_rejected(app_client, extra):
    client, _, sessions, _, _ = app_client
    login(client, sessions)
    key, _ = create(client)
    body = {"action": "edit", "revision": 1, **extra}
    assert client.post(f"/api/v1/research/archives/{key}/actions", json=body).status_code == 422


def test_cross_origin_cookie_write_rejected(app_client):
    client, _, sessions, _, _ = app_client
    login(client, sessions)
    response = client.put(
        f"/api/v1/research/archives/{uuid.uuid4()}",
        json={"kind": "chart", "payload": payload(), "name": "x"},
        headers={"Origin": "https://untrusted.example"},
    )
    assert response.status_code == 403
    assert client.get("/api/v1/research/archives").json()["items"] == []


def test_expected_owner_header_cannot_authorize_a_different_cookie(app_client):
    client, _, sessions, alice, _ = app_client
    login(client, sessions, "Bob")
    headers = {"X-Research-Owner": alice.id}
    assert client.get("/api/v1/research/archives", headers=headers).status_code == 409
    response = client.put(
        f"/api/v1/research/archives/{uuid.uuid4()}",
        json={"kind": "chart", "payload": payload(), "name": "stale page"},
        headers=headers,
    )
    assert response.status_code == 409
    assert client.get("/api/v1/research/archives").json()["items"] == []
