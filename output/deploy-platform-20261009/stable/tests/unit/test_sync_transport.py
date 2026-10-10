"""同步 transport 回归测试。"""

from unittest.mock import patch

from easy_tdx.exceptions import TdxConnectionError
from easy_tdx.transport.sync import TdxConnection, ping_all, ping_host


class _FakeSocket:
    def __init__(self) -> None:
        self.timeout: float | None = None
        self.connected_to: tuple[str, int] | None = None
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def connect(self, address: tuple[str, int]) -> None:
        self.connected_to = address

    def sendall(self, data: bytes) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_sync_connection_closes_socket_when_setup_fails() -> None:
    sock = _FakeSocket()
    conn = TdxConnection("127.0.0.1", port=7709, timeout=0.2)

    with (
        patch("easy_tdx.transport.sync.socket.socket", return_value=sock),
        patch.object(
            TdxConnection,
            "_send_setup",
            side_effect=TdxConnectionError("setup failed"),
        ),
    ):
        try:
            conn.connect()
        except TdxConnectionError as exc:
            assert "setup failed" in str(exc)
        else:  # pragma: no cover - 防御性断言
            raise AssertionError("expected setup failure")

    assert sock.timeout == 0.2
    assert sock.connected_to == ("127.0.0.1", 7709)
    assert sock.closed is True
    assert conn._sock is None


def test_ping_host_returns_none_when_server_closes_during_handshake() -> None:
    """握手期服务器关闭连接（_recv_exact_sock 抛 TdxConnectionError）应返回 None。

    回归：ping_host 旧版仅 except OSError，未捕获 TdxConnectionError（继承自
    TdxError(Exception) 而非 OSError），导致单个服务器握手失败就让整个
    ping_all / `easy-tdx ping` 命令崩溃。非交易时间服务器 accept 后立即 FIN
    时必现。
    """
    sock = _FakeSocket()
    with (
        patch("easy_tdx.transport.sync.socket.socket", return_value=sock),
        patch(
            "easy_tdx.transport.sync._recv_exact_sock",
            side_effect=TdxConnectionError("连接被服务器关闭"),
        ),
    ):
        result = ping_host("192.0.2.1", port=7709, timeout=0.2)

    assert result is None
    assert sock.closed is True


def test_ping_all_skips_handshake_failure_without_crash() -> None:
    """ping_all 中任一服务器握手失败（TdxConnectionError）应被跳过，不崩溃。"""

    def fake_ping(host: str, port: int, timeout: float) -> float | None:
        if host == "bad":
            raise TdxConnectionError("连接被服务器关闭")
        return 0.05

    with patch("easy_tdx.transport.sync.ping_host", side_effect=fake_ping):
        results = ping_all(hosts=["good", "bad"], port=7709, timeout=0.2)

    hosts_ok = [h for h, _ in results]
    assert "good" in hosts_ok
    assert "bad" not in hosts_ok
