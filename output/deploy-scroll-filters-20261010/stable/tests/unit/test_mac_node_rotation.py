"""MAC 全节点轮换：真实坏包、握手失败、参数不变及并发/心跳边界。"""

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import easy_tdx.mac.client as module
from easy_tdx.exceptions import TdxConnectionError, TdxDecodeError, TdxNodesExhaustedError
from easy_tdx.mac.client import AsyncMacClient, MacClient, _rotation_hosts
from easy_tdx.mac.commands.symbol_bar import SymbolBarCmd
from easy_tdx.mac.enums import Adjust, Period
from easy_tdx.web.errors import register_exception_handlers


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(module, "get_mac_hosts", lambda: ["a", "b", "c", "a"])
    monkeypatch.setattr(module, "save_best_mac_host", MagicMock())
    monkeypatch.setattr(module, "record_success", MagicMock())
    monkeypatch.setattr(module, "record_failure", MagicMock())


def command():
    return SymbolBarCmd(0, "300750", Period.DAILY, count=600, fq=Adjust.QFQ)


def packet(count=0, records=b""):
    return struct.pack("<H22sHBHI", 0, b"300750", 4, 0, count, 0) + records


def test_rotates_all_nodes_once_and_wraps():
    assert _rotation_hosts("b", None) == ["b", "c", "a"]
    assert _rotation_hosts("custom", ["a", "a", "b"]) == ["custom", "a", "b"]
    assert _rotation_hosts("a", []) == ["a"]


@pytest.mark.parametrize("body", [b"\0" * 24, packet(1), packet(2, b"\0" * 36)])
def test_truncated_response_raises(body):
    with pytest.raises(TdxDecodeError):
        command().parse_response(body)


def test_legitimate_empty_and_complete_response():
    assert command().parse_response(packet()) == []
    record = struct.pack("<II7f", 20260930, 0, 10, 12, 9, 11, 100, 20, 1000)
    assert len(command().parse_response(packet(1, record))) == 1


def install_connections(monkeypatch, asynchronous, failures):
    made = []
    requests = []
    factory_name = "AsyncTdxConnection" if asynchronous else "TdxConnection"

    def factory(host, *args):
        conn = MagicMock()

        def execute(cmd):
            requests.append((host, cmd, cmd.build_request()))
            error = failures.get(host)
            if error == "decode":
                return cmd.parse_response(b"\0" * 24)
            if isinstance(error, Exception):
                raise error
            return []  # Valid empty is a success, not a reason to rotate.

        def connect():
            if failures.get(host) == "connect":
                raise TdxConnectionError("handshake failed")

        conn.execute = (
            AsyncMock(side_effect=execute) if asynchronous else MagicMock(side_effect=execute)
        )
        conn.connect = (
            AsyncMock(side_effect=connect) if asynchronous else MagicMock(side_effect=connect)
        )
        conn.close = AsyncMock() if asynchronous else MagicMock()
        made.append((host, conn))
        return conn

    monkeypatch.setattr(module, factory_name, factory)
    return made, requests


@pytest.mark.parametrize("asynchronous", [False, True])
def test_decode_then_failed_handshake_then_success(monkeypatch, asynchronous):
    made, requests = install_connections(monkeypatch, asynchronous, {"a": "decode", "b": "connect"})
    cls = AsyncMacClient if asynchronous else MacClient
    client = cls("a", heartbeat_interval=0)
    cmd = command()
    if asynchronous:
        asyncio.run(client._execute(cmd))
    else:
        client._execute(cmd)
    assert client._host == "c"
    assert [host for host, conn in made] == ["a", "b", "c"]
    assert [host for host, cmd, wire in requests] == ["a", "c"]
    assert all(c is cmd and wire == cmd.build_request() for host, c, wire in requests)
    module.save_best_mac_host.assert_called_once_with("c")


@pytest.mark.parametrize("asynchronous", [False, True])
def test_all_failed_has_full_trace_and_bounded_attempts(monkeypatch, asynchronous):
    made, requests = install_connections(
        monkeypatch,
        asynchronous,
        {"a": "decode", "b": "connect", "c": TdxConnectionError("timeout")},
    )
    client = (AsyncMacClient if asynchronous else MacClient)("a", heartbeat_interval=0)
    with pytest.raises(TdxNodesExhaustedError) as info:
        if asynchronous:
            asyncio.run(client._execute(command()))
        else:
            client._execute(command())
    assert [host for host, error in info.value.attempts] == ["a", "b", "c"]
    assert len(made) == 3
    module.save_best_mac_host.assert_not_called()


@pytest.mark.parametrize(
    "error", [TdxDecodeError("bad"), TdxConnectionError("down"), ValueError("bug")]
)
@pytest.mark.parametrize("asynchronous", [False, True])
def test_disabled_retry_or_programming_error_not_swallowed(monkeypatch, error, asynchronous):
    made, requests = install_connections(monkeypatch, asynchronous, {"a": error})
    client = (AsyncMacClient if asynchronous else MacClient)(
        "a", auto_reconnect=isinstance(error, ValueError), heartbeat_interval=0
    )
    with pytest.raises(type(error)):
        if asynchronous:
            asyncio.run(client._execute(command()))
        else:
            client._execute(command())
    assert len(made) == 1


@pytest.mark.parametrize("asynchronous", [False, True])
def test_initial_connection_rotates_after_handshake_failure(monkeypatch, asynchronous):
    made, requests = install_connections(
        monkeypatch, asynchronous, {"a": "connect", "b": "connect"}
    )
    client = (AsyncMacClient if asynchronous else MacClient)("a", heartbeat_interval=0)
    if asynchronous:
        asyncio.run(client.connect())
    else:
        client.connect()
    assert client._host == "c"
    # Handshake alone never persists an unverified data node.
    module.save_best_mac_host.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_requests_reuse_verified_node(monkeypatch):
    made, requests = install_connections(monkeypatch, True, {"a": "decode", "b": "connect"})
    client = AsyncMacClient("a", heartbeat_interval=0)
    await asyncio.gather(client._execute(command()), client._execute(command()))
    assert [host for host, cmd, wire in requests] == ["a", "c", "c"]
    module.save_best_mac_host.assert_called_once_with("c")


@pytest.mark.asyncio
async def test_heartbeat_can_rotate_without_cancelling_itself(monkeypatch):
    made, requests = install_connections(monkeypatch, True, {"a": "decode", "b": "connect"})
    client = AsyncMacClient("a", heartbeat_interval=0)

    async def heartbeat_request():
        client._heartbeat_task = asyncio.current_task()
        await client._execute(command())
        await asyncio.sleep(0)  # Pending self-cancellation would surface here.
        assert not asyncio.current_task().cancelled()

    await asyncio.wait_for(asyncio.create_task(heartbeat_request()), timeout=1)


def test_save_failure_does_not_discard_success(monkeypatch):
    install_connections(monkeypatch, False, {})
    module.save_best_mac_host.side_effect = OSError("readonly config")
    assert MacClient("a", heartbeat_interval=0)._execute(command()) == []


def test_exhaustion_is_503_not_empty_data_or_internal_error():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/probe")
    def probe():
        raise TdxNodesExhaustedError([("a", "decode"), ("b", "timeout")])

    response = TestClient(app).get("/probe")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert "全部 2 个" in response.json()["detail"]


@pytest.mark.parametrize("asynchronous", [False, True])
def test_recovers_when_last_failed_node_comes_back(monkeypatch, asynchronous):
    failures = {"a": "decode", "b": "connect", "c": "connect"}
    made, requests = install_connections(monkeypatch, asynchronous, failures)
    client = (AsyncMacClient if asynchronous else MacClient)("a", heartbeat_interval=0)

    async def run_async():
        with pytest.raises(TdxNodesExhaustedError):
            await client._execute(command())
        failures.pop("c")
        assert await client._execute(command()) == []

    if asynchronous:
        asyncio.run(run_async())
    else:
        with pytest.raises(TdxNodesExhaustedError):
            client._execute(command())
        failures.pop("c")
        assert client._execute(command()) == []
    assert [host for host, conn in made] == ["a", "b", "c", "c"]
    module.save_best_mac_host.assert_called_once_with("c")
