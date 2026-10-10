"""Real application boundaries: authentication, browser origins and bounded input."""

import re

import pytest
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from easy_tdx.web import account_store as accounts
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.app import _create_app as create_app
from easy_tdx.web.request_security import RequestSecurityMiddleware
from easy_tdx.web.routers.auth import get_current_user, require_admin


@pytest.fixture
def app(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(accounts, "_store", store)
    monkeypatch.delenv("EASY_TDX_ALLOWED_ORIGINS", raising=False)
    value = create_app(host="127.0.0.1", enable_mac=False)
    value.state.tdx_client = None
    # Do not enter lifespan: these tests never contact upstream market nodes.
    return value, store


def test_every_market_and_compute_route_has_application_authentication(app):
    value, _ = app
    client = TestClient(value)
    checked = 0
    for route in value.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1/"):
            continue
        if route.path.startswith(("/api/v1/auth/", "/api/v1/admin/users")):
            continue
        assert {get_current_user, require_admin}.intersection(
            dep.call for dep in route.dependant.dependencies
        ), route.path
        path = re.sub(r"\{[^}]+\}", "test", route.path)
        method = sorted(route.methods - {"HEAD", "OPTIONS"})[0]
        assert client.request(method, path, json={}).status_code == 401, route.path
        checked += 1
    assert checked >= 77  # All currently mounted non-auth HTTP API routes, not a sample.


def test_login_page_bootstrap_remains_public_and_existing_user_can_query(app):
    value, store = app
    client = TestClient(value)
    assert client.get("/api/v1/auth/status").status_code == 200
    user = store.create_user("alice", "safe-password")
    client.cookies.set("easy_tdx_session", store.create_session(user.id))
    assert client.get("/api/v1/backtest/tasks").status_code == 200
    assert client.get("/api/v1/auth/me").json()["user"]["id"] == user.id
    assert client.get("/api/v1/does-not-exist").status_code == 404


@pytest.mark.parametrize(
    "origin", ["https://evil.invalid", "null", "http://testserver.evil.invalid"]
)
def test_cross_origin_writes_rejected_even_with_valid_cookie(app, origin):
    value, store = app
    client = TestClient(value)
    user = store.create_user("alice", "safe-password")
    token = store.create_session(user.id)
    client.cookies.set("easy_tdx_session", token)
    response = client.post("/api/v1/auth/logout", headers={"Origin": origin})
    assert response.status_code == 403
    assert store.get_user_for_session(token) is not None


def test_same_origin_and_explicit_development_origin_accepted(app, monkeypatch):
    value, _ = app
    assert (
        TestClient(value)
        .post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "http://testserver",
            },
        )
        .status_code
        == 200
    )
    monkeypatch.setenv("EASY_TDX_ALLOWED_ORIGINS", "http://localhost:5173")
    dev = TestClient(create_app(host="127.0.0.1", enable_mac=False))
    response = dev.post("/api/v1/auth/logout", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    monkeypatch.setenv("EASY_TDX_ALLOWED_ORIGINS", "*")
    with pytest.raises(ValueError):
        create_app(host="127.0.0.1", enable_mac=False)


def test_auth_body_limit_precedes_parsing_and_originless_cross_site_is_rejected(app):
    value, _ = app
    client = TestClient(value)
    assert client.post("/api/v1/auth/login", content=b"x" * 8193).status_code == 413
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={
                "Sec-Fetch-Site": "cross-site",
            },
        ).status_code
        == 403
    )


@pytest.mark.asyncio
async def test_chunked_body_limit_without_content_length_and_no_partial_dispatch():
    dispatched = []

    async def downstream(scope, receive, send):
        dispatched.append(True)

    middleware = RequestSecurityMiddleware(downstream, [], max_body=8)
    messages = iter(
        [
            {"type": "http.request", "body": b"12345", "more_body": True},
            {"type": "http.request", "body": b"6789", "more_body": False},
        ]
    )
    responses = []

    async def receive():
        return next(messages)

    async def send(message):
        responses.append(message)

    await middleware(
        {
            "type": "http",
            "path": "/api/v1/run",
            "method": "POST",
            "headers": [],
            "scheme": "http",
            "server": ("localhost", 80),
            "query_string": b"",
        },
        receive,
        send,
    )
    assert not dispatched
    assert responses[0]["status"] == 413


def test_body_is_replayed_once_and_preferences_preserve_existing_allowance():
    value = FastAPI()
    value.add_middleware(RequestSecurityMiddleware, allowed_origins=[])

    @value.put("/api/v1/auth/me/preferences")
    async def echo(request: Request):
        return {"bytes": len(await request.body())}

    assert TestClient(value).put(
        "/api/v1/auth/me/preferences",
        content=b"x" * 64000,
    ).json() == {"bytes": 64000}


def test_websocket_rejects_anonymous_and_wrong_origin(app):
    value, store = app
    client = TestClient(value)
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect("/api/v1/ws/realtime/SZ000001"):
            pass
    assert denied.value.code == 4401
    user = store.create_user("alice", "safe-password")
    client.cookies.set("easy_tdx_session", store.create_session(user.id))
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect(
            "/api/v1/ws/realtime/SZ000001",
            headers={
                "Origin": "https://evil.invalid",
            },
        ):
            pass
    assert denied.value.code == 4403


def test_websocket_validates_messages_limits_subscriptions_and_revokes_session(app):
    value, store = app
    client = TestClient(value)
    user = store.create_user("alice", "safe-password")
    token = store.create_session(user.id)
    client.cookies.set("easy_tdx_session", token)
    with client.websocket_connect("/api/v1/ws/realtime/SZ000001") as socket:
        for message in ([1], {"action": "subscribe", "symbol": 123}):
            socket.send_json(message)
            assert socket.receive_json()["type"] == "error"
        for index in range(2, 33):
            socket.send_json({"action": "subscribe", "symbol": f"SZ{index:06}"})
            assert socket.receive_json()["type"] == "status"
        socket.send_json({"action": "subscribe", "symbol": "SZ000033"})
        assert socket.receive_json()["type"] == "error"
        store.invalidate_user_sessions(user.id)
        socket.send_json({"action": "unsubscribe", "symbol": "SZ000032"})
        # An in-flight receive may acknowledge a control message, but the next
        # loop must close; no snapshot can be pushed using a revoked identity.
        with pytest.raises(WebSocketDisconnect) as denied:
            while True:
                socket.receive_json()
        assert denied.value.code == 4401
