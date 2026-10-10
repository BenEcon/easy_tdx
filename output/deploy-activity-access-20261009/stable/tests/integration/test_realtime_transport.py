"""Loopback-only actual Uvicorn/WebSocket framing; never contacts market servers."""

import json
import socket
import threading
import time

import pytest
import uvicorn

from easy_tdx.web import account_store as accounts
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.app import _create_app
from easy_tdx.web.realtime_limits import RealtimeLimits


@pytest.fixture
def live_boundary(tmp_path, monkeypatch):
    monkeypatch.setenv("EASY_TDX_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("EASY_TDX_ALLOWED_ORIGINS", raising=False)
    store = AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(accounts, "_store", store)
    monkeypatch.setattr(RealtimeLimits, "MAX_USER_CONNECTIONS", 1)
    user = store.create_user("alice", "safe-password")
    token = store.create_session(user.id)
    app = _create_app(host="127.0.0.1", enable_mac=False)
    app.state.tdx_client = None
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            lifespan="off",
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
        yield f"ws://127.0.0.1:{port}/api/v1/ws/realtime/SZ000001", token, store, user
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        assert not thread.is_alive(), "Local test server did not stop"


@pytest.mark.parametrize("fragmented", [False, True])
def test_transport_rejects_oversize_before_application_consumes_message(live_boundary, fragmented):
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect

    url, token, store, user = live_boundary
    with connect(
        url,
        additional_headers={"Cookie": f"easy_tdx_session={token}"},
        open_timeout=3,
        close_timeout=3,
    ) as connection:
        connection.send(json.dumps({"action": "subscribe", "symbol": "SZ000002"}))
        assert json.loads(connection.recv(timeout=3))["type"] == "status"
        with RealtimeLimits(store.db_path)._connect() as conn:
            before = conn.execute(
                "SELECT tokens, updated FROM realtime_buckets WHERE id=?", (f"user:{user.id}",)
            ).fetchone()
        connection.send(["x" * 2048] * 3 if fragmented else "x" * 4097)
        with pytest.raises(ConnectionClosed) as closed:
            connection.recv(timeout=3)
        assert closed.value.rcvd.code == 1009
        with RealtimeLimits(store.db_path)._connect() as conn:
            after = conn.execute(
                "SELECT tokens, updated FROM realtime_buckets WHERE id=?", (f"user:{user.id}",)
            ).fetchone()
        assert after == before  # Oversize was rejected before ASGI route parsed/charged it.


def test_actual_connection_quota_close_reason_reaches_client(live_boundary):
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect

    url, token, _, _ = live_boundary
    options = dict(
        additional_headers={"Cookie": f"easy_tdx_session={token}"}, open_timeout=3, close_timeout=3
    )
    with connect(url, **options) as first:
        with connect(url, **options) as excess:
            with pytest.raises(ConnectionClosed) as closed:
                excess.recv(timeout=3)
            assert closed.value.rcvd.code == 4429
            assert "连接数" in closed.value.rcvd.reason
        first.send(json.dumps({"action": "subscribe", "symbol": "SZ000002"}))
        assert json.loads(first.recv(timeout=3))["type"] == "status"
