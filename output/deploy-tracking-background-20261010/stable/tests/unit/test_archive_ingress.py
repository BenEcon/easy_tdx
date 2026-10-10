"""Formal app routing and pre-body upload boundaries, without upstream network."""

import asyncio
import json
import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from easy_tdx.web import account_store as accounts
from easy_tdx.web import archive_ingress
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.app import _create_app
from easy_tdx.web.request_security import RequestSecurityMiddleware
from easy_tdx.web.research_archive import ResearchArchive
from easy_tdx.web.resource_admission import LIMITS, ResourceStore
from tests.unit.test_research_archive import payload


@pytest.fixture
def identity(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(accounts, "_store", store)
    user = store.create_user("upload-user", "safe-upload-password")
    return store, user, store.create_session(user.id)


def upload_scope(token="", **changes):
    return {
        "type": "http",
        "method": "PUT",
        "path": f"/api/v1/research/archives/{uuid.uuid4()}",
        "headers": [(b"cookie", f"easy_tdx_session={token}".encode())],
        "scheme": "http",
        "server": ("testserver", 80),
        "query_string": b"",
        **changes,
    }


def leases(store):
    resource = ResourceStore(store.db_path)
    with resource.connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM resource_leases").fetchone()[0]


def test_formal_app_archive_routes_and_persistent_store(identity):
    store, user, token = identity
    app = _create_app(host="127.0.0.1", enable_mac=False)
    client = TestClient(app)  # No lifespan / market connection.
    client.cookies.set("easy_tdx_session", token)
    key = str(uuid.uuid4())
    base = f"/api/v1/research/archives/{key}"
    original = payload()
    original["largeTestField"] = "x" * (8 * 1024 * 1024)
    response = client.put(base, json={"kind": "chart", "name": "研究", "payload": original})
    assert response.status_code == 201, response.text[:300]
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["id"] == key
    assert "payload" not in response.json()  # Create returns metadata, not a second large body.
    second = TestClient(_create_app(host="127.0.0.1", enable_mac=False))
    second.cookies.set("easy_tdx_session", token)
    assert second.get(base).json()["payload"] == original
    assert second.get("/api/v1/research/archives").json()["items"][0]["id"] == key
    assert store.db_path.with_name("research_archives.db").is_file()
    assert leases(store) == 0
    store.invalidate_user_sessions(user.id)
    assert second.get(base).status_code == 401
    assert second.put(base, json={}).status_code == 401


async def test_disconnected_waiter_does_not_release_running_sqlite_write(identity, monkeypatch):
    store, user, token = identity
    entered, finish, exited = threading.Event(), threading.Event(), threading.Event()
    create = ResearchArchive.create

    def delayed_create(self, *args):
        entered.set()
        try:
            assert finish.wait(5)
            return create(self, *args)
        finally:
            exited.set()

    monkeypatch.setattr(ResearchArchive, "create", delayed_create)
    scope = upload_scope(token)
    scope["headers"].append((b"content-type", b"application/json"))
    body = json.dumps({"kind": "chart", "name": "durable-write", "payload": payload()}).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        pass

    app = _create_app(host="127.0.0.1", enable_mac=False)
    task = asyncio.create_task(app(scope, receive, send))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        assert leases(store) == 2  # Upload + ordinary data slots.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert leases(store) == 2  # Worker has not stopped merely because HTTP left.
    finally:
        finish.set()
    assert await asyncio.to_thread(exited.wait, 5)
    for _ in range(100):
        if leases(store) == 0:
            break
        await asyncio.sleep(0.01)
    assert leases(store) == 0
    archive = ResearchArchive(store.db_path.with_name("research_archives.db"))
    key = scope["path"].rsplit("/", 1)[1]
    assert archive.get(user.id, key)["payload"] == payload()
    # A lost response can mean committed; the captured ID remains safe to retry.
    assert archive.create(user.id, key, "chart", payload(), "durable-write")[1] is False


def test_formal_app_enforces_payload_limit_inside_envelope(identity):
    store, _, token = identity
    client = TestClient(_create_app(host="127.0.0.1", enable_mac=False))
    client.cookies.set("easy_tdx_session", token)
    original = payload()
    original["tooLarge"] = "x" * (25 * 1024 * 1024)
    response = client.put(
        f"/api/v1/research/archives/{uuid.uuid4()}",
        json={"kind": "chart", "name": "oversize", "payload": original},
    )
    assert response.status_code == 413
    assert "单份存档" in response.json()["detail"]
    assert client.get("/api/v1/research/archives").json()["items"] == []
    assert leases(store) == 0


async def test_cancellation_during_reservation_releases_late_lease(identity, monkeypatch):
    store, _, token = identity
    entered, release, released = threading.Event(), threading.Event(), threading.Event()
    acquire = ResourceStore.acquire
    original_release = ResourceStore.release

    def delayed_acquire(self, *args):
        entered.set()
        assert release.wait(5)
        return acquire(self, *args)

    def mark_release(self, key):
        original_release(self, key)
        released.set()

    monkeypatch.setattr(ResourceStore, "acquire", delayed_acquire)
    monkeypatch.setattr(ResourceStore, "release", mark_release)

    async def forbidden(*args):
        raise AssertionError("Cancelled upload must not read or dispatch")

    task = asyncio.create_task(
        RequestSecurityMiddleware(forbidden, [], archive_uploads=True)(
            upload_scope(token),
            forbidden,
            forbidden,
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    assert await asyncio.to_thread(released.wait, 5)
    assert leases(store) == 0


async def test_session_revoked_during_upload_rechecked_before_writing(identity):
    store, user, token = identity
    app = _create_app(host="127.0.0.1", enable_mac=False)
    sent = []
    body = json.dumps({"kind": "chart", "name": "revoked", "payload": payload()}).encode()

    async def receive():
        assert leases(store) == 1
        store.invalidate_user_sessions(user.id)
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    scope = upload_scope(token)
    scope["headers"].append((b"content-type", b"application/json"))
    await app(scope, receive, send)
    assert sent[0]["status"] == 401
    assert not store.db_path.with_name("research_archives.db").exists()
    assert leases(store) == 0


@pytest.mark.parametrize("kind", ["anonymous", "revoked", "wrong-owner", "origin", "quota"])
async def test_rejected_upload_does_not_read_body(identity, kind):
    store, user, token = identity
    scope = upload_scope(token)
    held = None
    if kind == "anonymous":
        scope["headers"] = []
    elif kind == "revoked":
        store.invalidate_user_sessions(user.id)
    elif kind == "wrong-owner":
        scope["headers"].append((b"x-research-owner", b"someone-else"))
    elif kind == "origin":
        scope["headers"].append((b"origin", b"https://evil.invalid"))
    else:
        held = ResourceStore(store.db_path).acquire(user.id, "archive_upload")
    sent = []

    async def forbidden(*args):
        raise AssertionError("Rejected upload read body or reached downstream")

    async def send(message):
        sent.append(message)

    try:
        await RequestSecurityMiddleware(forbidden, [], archive_uploads=True)(scope, forbidden, send)
        assert (
            sent[0]["status"]
            == {
                "anonymous": 401,
                "revoked": 401,
                "wrong-owner": 409,
                "origin": 403,
                "quota": 429,
            }[kind]
        )
    finally:
        if held:
            ResourceStore(store.db_path).release(held)
    assert leases(store) == 0


@pytest.mark.parametrize(
    "ending", ["disconnect", "oversize", "timeout", "cancel", "success", "crash"]
)
async def test_stream_termination_always_releases_capacity(identity, monkeypatch, ending):
    store, _, token = identity
    monkeypatch.setattr(archive_ingress, "ARCHIVE_BODY_LIMIT", 8)
    monkeypatch.setattr(archive_ingress, "ARCHIVE_BODY_TIMEOUT", 0.05)
    received, sent, dispatched = asyncio.Event(), [], []

    async def receive():
        received.set()
        assert leases(store) == 1
        if ending in {"timeout", "cancel"}:
            await asyncio.Event().wait()
        if ending == "disconnect":
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": b"123456789" if ending == "oversize" else b"1234"}

    async def downstream(scope, replay, send):
        dispatched.append((await replay())["body"])
        assert leases(store) == 1
        if ending == "crash":
            raise RuntimeError("synthetic downstream failure")

    async def send(message):
        sent.append(message)

    task = asyncio.create_task(
        RequestSecurityMiddleware(downstream, [], archive_uploads=True)(
            upload_scope(token),
            receive,
            send,
        )
    )
    if ending == "cancel":
        await received.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif ending == "crash":
        with pytest.raises(RuntimeError):
            await task
    else:
        await task
    assert leases(store) == 0
    assert bool(dispatched) == (ending in {"success", "crash"})
    if ending in {"oversize", "timeout"}:
        assert sent[0]["status"] == (413 if ending == "oversize" else 408)


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("POST", "00000000-0000-0000-0000-000000000000"),
        ("PUT", "not-a-uuid"),
        ("PUT", "00000000-0000-0000-0000-000000000000/actions"),
        ("PUT", "00000000-0000-0000-0000-000000000000/"),
    ],
)
async def test_large_body_exception_does_not_apply_to_other_routes(identity, method, suffix):
    _, _, token = identity
    scope = upload_scope(token, method=method, path="/api/v1/research/archives/" + suffix)
    scope["headers"].append((b"content-length", str(8 * 1024 * 1024 + 1).encode()))
    sent = []

    async def forbidden(*args):
        raise AssertionError("Must reject by original body limit")

    async def send(message):
        sent.append(message)

    await RequestSecurityMiddleware(forbidden, [], archive_uploads=True)(scope, forbidden, send)
    assert sent[0]["status"] == 413


async def test_multi_account_global_limit_is_shared_across_store_instances(identity, monkeypatch):
    store, user, token = identity
    monkeypatch.setitem(LIMITS, "archive_upload", (1, 2))
    first = ResourceStore(store.db_path)
    held = [first.acquire("other-1", "archive_upload"), first.acquire("other-2", "archive_upload")]
    sent = []

    async def forbidden(*args):
        raise AssertionError("Global limit must precede body")

    async def send(message):
        sent.append(message)

    try:
        await RequestSecurityMiddleware(forbidden, [], archive_uploads=True)(
            upload_scope(token), forbidden, send
        )
        assert sent[0]["status"] == 429
        assert leases(store) == 2
    finally:
        for key in held:
            first.release(key)
    assert leases(store) == 0
