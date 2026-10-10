"""TdxClient._execute 的指数退避重连测试（sync + async）。

之前 _execute 的 4 次 _RETRY_DELAYS 退避重连路径零测试（审计报告 #9），
仅 async 有 transport 层的真实重连测试，未覆盖 _execute 自身的退避循环。
本文件 mock _conn.execute 让前 N 次抛 TdxConnectionError、第 N+1 次成功，
并 patch time.sleep / asyncio.sleep 验证退避序列。
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from easy_tdx.client import _RETRY_DELAYS, AsyncTdxClient, TdxClient
from easy_tdx.commands.security_count import GetSecurityCountCmd
from easy_tdx.exceptions import TdxConnectionError
from easy_tdx.models.enums import Market

# --------------------------------------------------------------------------- #
# 同步 _execute 重连
# --------------------------------------------------------------------------- #


class TestSyncExecuteReconnect:
    def test_reconnect_succeeds_on_second_attempt(self) -> None:
        """首次抛 TdxConnectionError，重连后第 1 次重试成功。"""
        with patch("easy_tdx.client.TdxConnection") as mock_conn_cls:
            mock_conn = MagicMock()
            # execute 首次抛错，重连后（第1次重试）成功
            mock_conn.execute.side_effect = [
                TdxConnectionError("disconnected"),
                1000,  # 重连后成功
            ]
            mock_conn_cls.return_value = mock_conn

            client = TdxClient("1.1.1.1", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)
            with patch("easy_tdx.client.time.sleep"):  # 跳过真实 sleep
                result = client._execute(GetSecurityCountCmd(Market.SH))
            assert result == 1000
            # 应重连了 1 次（首次失败 + 1 次重试成功）
            assert mock_conn.close.call_count == 1

    def test_all_retries_exhausted_raises_last(self) -> None:
        """4 次重试全部失败，应抛出最后一个异常。"""
        with patch("easy_tdx.client.TdxConnection") as mock_conn_cls:
            mock_conn = MagicMock()
            # 首次 + 4 次重试全部失败
            mock_conn.execute.side_effect = TdxConnectionError("always down")
            mock_conn_cls.return_value = mock_conn

            client = TdxClient("1.1.1.1", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)
            with patch("easy_tdx.client.time.sleep") as mock_sleep:
                with pytest.raises(TdxConnectionError):
                    client._execute(GetSecurityCountCmd(Market.SH))
            # 应 sleep 了 4 次（_RETRY_DELAYS 长度）
            assert mock_sleep.call_count == len(_RETRY_DELAYS)

    def test_no_reconnect_when_disabled(self) -> None:
        """auto_reconnect=False 时首次失败立即抛出，不重试。"""
        with patch("easy_tdx.client.TdxConnection") as mock_conn_cls:
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = TdxConnectionError("down")
            mock_conn_cls.return_value = mock_conn

            client = TdxClient("1.1.1.1", 7709, 1.0, auto_reconnect=False, heartbeat_interval=0)
            with patch("easy_tdx.client.time.sleep") as mock_sleep:
                with pytest.raises(TdxConnectionError):
                    client._execute(GetSecurityCountCmd(Market.SH))
            # 禁用重连时不应 sleep
            mock_sleep.assert_not_called()

    def test_retry_uses_exponential_backoff_delays(self) -> None:
        """验证 sleep 调用的延迟序列与 _RETRY_DELAYS 一致。"""
        with patch("easy_tdx.client.TdxConnection") as mock_conn_cls:
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = TdxConnectionError("down")
            mock_conn_cls.return_value = mock_conn

            client = TdxClient("1.1.1.1", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)
            with patch("easy_tdx.client.time.sleep") as mock_sleep:
                with pytest.raises(TdxConnectionError):
                    client._execute(GetSecurityCountCmd(Market.SH))
            actual_delays = [call.args[0] for call in mock_sleep.call_args_list]
            assert tuple(actual_delays) == _RETRY_DELAYS


# --------------------------------------------------------------------------- #
# 异步 _execute 重连
# --------------------------------------------------------------------------- #


class TestAsyncExecuteReconnect:
    def test_async_reconnect_succeeds_on_second_attempt(self) -> None:
        async def main() -> int:
            with patch("easy_tdx.client.AsyncTdxConnection") as mock_conn_cls:
                mock_conn = MagicMock()
                call_count = [0]

                async def _execute(cmd: object) -> int:
                    call_count[0] += 1
                    if call_count[0] == 1:
                        raise TdxConnectionError("down")
                    return 2000

                async def _noop() -> None:
                    return None

                mock_conn.execute = _execute
                mock_conn.close = _noop
                mock_conn.connect = _noop
                mock_conn_cls.return_value = mock_conn

                client = AsyncTdxClient(
                    "1.1.1.1", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0
                )
                with patch("easy_tdx.client.asyncio.sleep", new=AsyncMockSleep()):
                    result = await client._execute(GetSecurityCountCmd(Market.SH))
                return result

        assert asyncio.run(main()) == 2000

    def test_async_all_retries_exhausted(self) -> None:
        async def main() -> None:
            with patch("easy_tdx.client.AsyncTdxConnection") as mock_conn_cls:
                mock_conn = MagicMock()

                async def _execute(cmd: object) -> int:
                    raise TdxConnectionError("always down")

                async def _noop() -> None:
                    return None

                mock_conn.execute = _execute
                mock_conn.close = _noop
                mock_conn.connect = _noop
                mock_conn_cls.return_value = mock_conn

                client = AsyncTdxClient(
                    "1.1.1.1", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0
                )
                with patch("easy_tdx.client.asyncio.sleep", new=AsyncMockSleep()) as mock_sleep:
                    with pytest.raises(TdxConnectionError):
                        await client._execute(GetSecurityCountCmd(Market.SH))
                    assert mock_sleep.call_count == len(_RETRY_DELAYS)

        asyncio.run(main())


class AsyncMockSleep:
    """轻量 async sleep 替身，记录调用次数但不真实等待。"""

    def __init__(self) -> None:
        self.call_count = 0

    async def __call__(self, delay: float) -> None:
        self.call_count += 1
