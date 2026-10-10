"""Real loopback transport, simulated proxy headers, isolated accounts.

These tests prove the ASGI transport boundary, not Cloudflare or TLS deployment.
The peer probe exists only in this fixture and is never added to the product.
"""

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import Request

from easy_tdx.cli.proxy import validated_forwarded_allow_ips
from easy_tdx.web import account_store as accounts
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.app import _create_app


@pytest.fixture(
    params=["127.0.0.1", "127.0.0.0/8", "192.0.2.1"],
    ids=["trusted-proxy", "trusted-network", "untrusted-peer"],
)
def proxy_boundary(request, tmp_path, monkeypatch):
    trusted = request.param != "192.0.2.1"
    monkeypatch.setenv("EASY_TDX_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("EASY_TDX_SECURE_COOKIES", "1")
    monkeypatch.delenv("EASY_TDX_ALLOWED_ORIGINS", raising=False)
    store = AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(accounts, "_store", store)
    user = store.create_user("alice", "safe-password")
    token = store.create_session(user.id)
    app = _create_app(host="127.0.0.1", enable_mac=False)
    app.state.tdx_client = None

    @app.get("/peer")
    async def peer(request: Request):
        return {"peer": request.client.host, "scheme": request.url.scheme}

    # The product's SPA catch-all is already registered. Keep this test-only
    # probe ahead of it so the assertions inspect ASGI scope, not index.html.
    app.router.routes.insert(0, app.router.routes.pop())

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            lifespan="off",
            proxy_headers=True,
            forwarded_allow_ips=validated_forwarded_allow_ips(request.param),
            ws="websockets",
            ws_max_size=4096,
            ws_max_queue=8,
            ws_per_message_deflate=False,
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        assert server.started
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
        ) as client:
            yield client, port, trusted, token, store
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        assert not thread.is_alive(), "Local proxy-boundary server did not stop"


def test_only_trusted_transport_can_change_client_and_scheme(proxy_boundary):
    client, _, trusted, _, _ = proxy_boundary
    response = client.get(
        "/peer",
        headers={
            "X-Forwarded-For": "203.0.113.99, 198.51.100.27",
            "X-Forwarded-Proto": "https",
            "CF-Connecting-IP": "203.0.113.1",
            "X-Real-IP": "203.0.113.2",
            "Forwarded": "for=203.0.113.3;proto=https",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "peer": "198.51.100.27" if trusted else "127.0.0.1",
        "scheme": "https" if trusted else "http",
    }
    # CDN-specific and alternative headers never independently override ASGI client.
    assert client.get("/peer", headers={"CF-Connecting-IP": "203.0.113.1"}).json()["peer"] == (
        "127.0.0.1"
    )


def test_empty_or_invalid_forwarding_does_not_invent_client_or_scheme(proxy_boundary):
    client, _, _, _, _ = proxy_boundary
    response = client.get(
        "/peer",
        headers={"X-Forwarded-For": "", "X-Forwarded-Proto": "javascript"},
    )
    assert response.json() == {"peer": "127.0.0.1", "scheme": "http"}


def test_rightmost_proxy_identity_wins_over_duplicate_forged_prefix(proxy_boundary):
    client, _, trusted, _, _ = proxy_boundary
    response = client.get(
        "/peer",
        headers=[
            ("X-Forwarded-For", "203.0.113.99"),
            ("X-Forwarded-For", "198.51.100.27"),
        ],
    )
    assert response.json()["peer"] == ("198.51.100.27" if trusted else "127.0.0.1")


def test_origin_and_secure_cookie_work_with_validated_scheme(proxy_boundary):
    client, _, trusted, _, _ = proxy_boundary
    headers = {
        "Host": "tdx.test",
        "X-Forwarded-For": "198.51.100.27",
        "X-Forwarded-Proto": "https",
        "Origin": "https://tdx.test",
    }
    response = client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={"username": "alice", "password": "safe-password"},
    )
    assert response.status_code == (200 if trusted else 403)
    if not trusted:
        headers["Origin"] = "http://tdx.test"
        response = client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"username": "alice", "password": "safe-password"},
        )
        assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "; secure" in cookie and "; httponly" in cookie and "samesite=lax" in cookie
    assert (
        client.post(
            "/api/v1/auth/logout", headers={**headers, "Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )


def test_forged_forwarded_prefix_cannot_reset_peer_login_budget(proxy_boundary):
    client, _, trusted, _, _ = proxy_boundary
    for i in range(30):
        # A trusted proxy appends the actual peer after the attacker-controlled prefix.
        # Untrusted direct peers cannot pick a new budget by varying any header.
        headers = {
            "X-Forwarded-For": f"203.0.113.{i + 1}, 198.51.100.27",
            "CF-Connecting-IP": f"203.0.113.{i + 1}",
        }
        response = client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"username": f"unknown{i}", "password": "wrong-password"},
        )
        assert response.status_code == 401
    limited = client.post(
        "/api/v1/auth/login",
        headers={"X-Forwarded-For": "203.0.113.240, 198.51.100.27"},
        json={"username": "unknown30", "password": "wrong-password"},
    )
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    other = client.post(
        "/api/v1/auth/login",
        headers={"X-Forwarded-For": "198.51.100.28"},
        json={"username": "different-peer", "password": "wrong-password"},
    )
    assert other.status_code == (401 if trusted else 429)


def test_forwarded_websocket_scheme_must_come_from_trusted_peer(proxy_boundary):
    from websockets.exceptions import InvalidStatus
    from websockets.sync.client import connect

    _, port, trusted, token, store = proxy_boundary
    options = {
        "origin": f"https://127.0.0.1:{port}",
        "additional_headers": {
            "Cookie": f"easy_tdx_session={token}",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-For": "198.51.100.27",
        },
        "open_timeout": 3,
        "close_timeout": 3,
    }
    url = f"ws://127.0.0.1:{port}/api/v1/ws/realtime/SZ000001"
    if not trusted:
        with pytest.raises(InvalidStatus) as denied:
            with connect(url, **options):
                pytest.fail("Untrusted proto header must not create an HTTPS origin")
        assert denied.value.response.status_code == 403
        return
    with connect(url, **options) as connection:
        connection.send(json.dumps({"action": "subscribe", "symbol": "SZ000002"}))
        assert json.loads(connection.recv(timeout=3))["type"] == "status"
    assert store.get_user_for_session(token) is not None
