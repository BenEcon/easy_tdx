"""Shared admission, disconnect cleanup and rate enforcement on actual WS routes."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from easy_tdx.web import account_store as accounts
from easy_tdx.web import realtime_limits
from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.app import _create_app
from easy_tdx.web.realtime_limits import RealtimeLimits


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "accounts.db")
    monkeypatch.setattr(accounts, "_store", store)
    app = _create_app(host="127.0.0.1", enable_mac=False)
    app.state.tdx_client = None
    client = TestClient(app)
    user = store.create_user("alice", "safe-password")
    client.cookies.set("easy_tdx_session", store.create_session(user.id))
    return client, store, user


def test_shared_atomic_connection_admission_and_expired_worker_cannot_revive(tmp_path, monkeypatch):
    path = tmp_path / "limits.db"
    stores = [RealtimeLimits(path) for _ in range(8)]
    monkeypatch.setattr(realtime_limits.time, "time", lambda: 1000.0)
    with ThreadPoolExecutor(max_workers=8) as pool:
        leases = list(pool.map(lambda store: store.acquire("alice"), stores))
    active = [lease for lease in leases if lease]
    assert len(active) == 4
    stores[0].release(active[0])
    assert stores[1].acquire("alice")
    monkeypatch.setattr(realtime_limits.time, "time", lambda: 1061.0)
    assert not stores[0].renew(active[1])
    assert not stores[0].consume(active[1])
    assert stores[0].acquire("alice")


def test_global_connection_limit_includes_other_users(tmp_path, monkeypatch):
    limits = RealtimeLimits(tmp_path / "limits.db")
    monkeypatch.setattr(limits, "MAX_CONNECTIONS", 2)
    one = limits.acquire("alice")
    assert one and limits.acquire("bob")
    assert limits.acquire("charlie") is None
    limits.release(one)
    assert limits.acquire("charlie")


def test_token_budget_shared_across_connections_reconnect_and_store_instances(
    tmp_path, monkeypatch
):
    clock = [1000.0]
    monkeypatch.setattr(realtime_limits.time, "time", lambda: clock[0])
    path = tmp_path / "limits.db"
    first, second = RealtimeLimits(path), RealtimeLimits(path)
    lease = first.acquire("alice")
    for _ in range(40):
        assert first.consume(lease)
    first.release(lease)
    replacement = second.acquire("alice")
    assert not second.consume(replacement)
    clock[0] += 1
    assert second.consume(replacement)
    assert not first.consume(replacement)
    assert first.consume(first.acquire("bob"))


def test_global_message_budget_is_atomic_and_does_not_drain_denied_user(tmp_path, monkeypatch):
    monkeypatch.setattr(realtime_limits.time, "time", lambda: 1000.0)
    limits = RealtimeLimits(tmp_path / "limits.db")
    monkeypatch.setattr(limits, "GLOBAL_BURST", 2)
    alice, bob = limits.acquire("alice"), limits.acquire("bob")
    assert limits.consume(alice) and limits.consume(bob)
    assert not limits.consume(alice)
    with limits._connect() as conn:
        assert (
            conn.execute("SELECT tokens FROM realtime_buckets WHERE id='user:alice'").fetchone()[0]
            == 39
        )


def test_route_connection_limit_and_disconnect_release(boundary):
    client, store, _ = boundary
    with ExitStack() as stack:
        for _ in range(4):
            stack.enter_context(client.websocket_connect("/api/v1/ws/realtime/SZ000001"))
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect("/api/v1/ws/realtime/SZ000001") as socket:
                socket.receive_json()
        assert denied.value.code == 4429
    with client.websocket_connect("/api/v1/ws/realtime/SZ000001") as socket:
        socket.send_json({"action": "subscribe", "symbol": "SZ000002"})
        assert socket.receive_json()["type"] == "status"
    with RealtimeLimits(store.db_path)._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM realtime_leases").fetchone()[0] == 0


def test_malformed_messages_also_consume_budget(boundary, monkeypatch):
    client, _, _ = boundary
    monkeypatch.setattr(RealtimeLimits, "USER_BURST", 2)
    with client.websocket_connect("/api/v1/ws/realtime/SZ000001") as socket:
        for _ in range(2):
            socket.send_text("{")
            assert socket.receive_json()["type"] == "error"
        socket.send_text("{")
        with pytest.raises(WebSocketDisconnect) as denied:
            socket.receive_json()
        assert denied.value.code == 4429


@pytest.mark.parametrize("payload, code", [(b"binary", 1003), ("x" * 4097, 1009)])
def test_binary_and_oversized_message_rejection_releases_lease(boundary, payload, code):
    client, store, _ = boundary
    with client.websocket_connect("/api/v1/ws/realtime/SZ000001") as socket:
        (socket.send_bytes if isinstance(payload, bytes) else socket.send_text)(payload)
        with pytest.raises(WebSocketDisconnect) as denied:
            socket.receive_json()
        assert denied.value.code == code
    with RealtimeLimits(store.db_path)._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM realtime_leases").fetchone()[0] == 0


def test_idle_revocation_closes_and_removes_event_listener(boundary, monkeypatch):
    client, store, user = boundary
    monkeypatch.setattr(RealtimeLimits, "HEARTBEAT_SECONDS", 0.02)

    class Bus:
        listeners = set()

        def subscribe_all(self, callback):
            self.listeners.add(callback)

        def unsubscribe_all(self, callback):
            self.listeners.discard(callback)

    bus = Bus()
    client.app.state.event_bus = bus
    with client.websocket_connect("/api/v1/ws/realtime/SZ000001") as socket:
        store.invalidate_user_sessions(user.id)
        with pytest.raises(WebSocketDisconnect) as denied:
            socket.receive_json()
        assert denied.value.code == 4401
    assert not bus.listeners
    with RealtimeLimits(store.db_path)._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM realtime_leases").fetchone()[0] == 0


def test_admitted_connection_exception_still_releases_lease(boundary, monkeypatch):
    from easy_tdx.web.routers import realtime

    client, store, _ = boundary

    async def fail(*args):
        raise RuntimeError("accept failure")

    monkeypatch.setattr(realtime, "_serve_realtime", fail)
    with pytest.raises(RuntimeError, match="accept failure"):
        with client.websocket_connect("/api/v1/ws/realtime/SZ000001"):
            pass
    with RealtimeLimits(store.db_path)._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM realtime_leases").fetchone()[0] == 0


def test_serve_sets_transport_limits_for_normal_and_reload(monkeypatch):
    from unittest.mock import Mock

    import uvicorn
    from click.testing import CliRunner

    import easy_tdx.web
    from easy_tdx.cli.cmd_web import serve

    run = Mock()
    monkeypatch.setattr(uvicorn, "run", run)
    monkeypatch.setattr(easy_tdx.web, "create_app", Mock(return_value=object()))
    for extra in ([], ["--reload"]):
        result = CliRunner().invoke(serve, ["--no-open-browser", *extra])
        assert result.exit_code == 0, result.output
        options = run.call_args.kwargs
        assert options["ws"] == "websockets"
        assert options["ws_max_size"] == 4096
        assert options["ws_max_queue"] == 8
        assert options["ws_per_message_deflate"] is False
