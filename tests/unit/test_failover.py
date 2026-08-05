"""跨主机故障转移（failover）测试。

验证 8 个 client 的 ``_execute`` 在同主机重试耗尽（``_RETRY_DELAYS`` 走完仍
``TdxConnectionError``）后，会通过 ``select_best_host_sync`` / ``_async`` 重新
测速、切到延迟最低的另一台服务器再试一轮。同时覆盖：

- ``select_best_host_sync`` 的节流（30s 窗口内不重复测速）与"跳过当前 host"语义。
- ``auto_reconnect=False`` 时 failover 不触发。
- ``get_market_stat`` 空数据时触发 failover 再试。
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from easy_tdx._health import _FAILURE_DECAY, reset_health
from easy_tdx._reconnect import (
    _FAILOVER_PING_THROTTLE_SEC,
    _WORKING_HOST_MAX_ATTEMPTS,
    find_working_host_sync,
    select_best_host_sync,
)
from easy_tdx.client import TdxClient
from easy_tdx.commands.security_count import GetSecurityCountCmd
from easy_tdx.exceptions import TdxConnectionError
from easy_tdx.models.bar import SecurityBar
from easy_tdx.models.enums import KlineCategory, Market
from easy_tdx.models.stats import HistoricalFundFlow


@pytest.fixture(autouse=True)
def _isolate_health_and_throttle():
    """每个测试前后重置健康分 + 节流时间戳，避免跨测试污染。

    failover 与空数据转移现在会写健康分（record_failure/success），
    若不重置，一个测试里降权的 host 会影响后续测试的 rank_by_health 排序。
    """
    import easy_tdx._reconnect as r

    r._last_failover_ts = 0.0
    reset_health()
    yield
    reset_health()
    r._last_failover_ts = 0.0


# --------------------------------------------------------------------------- #
# select_best_host_sync 单元逻辑
# --------------------------------------------------------------------------- #


class TestSelectBestHostSync:
    def setup_method(self) -> None:
        # 每个测试前重置节流时间戳，避免上一个测试的节流窗口泄漏
        import easy_tdx._reconnect as r

        r._last_failover_ts = 0.0

    def test_returns_lowest_latency_host_excluding_current(self) -> None:
        """返回延迟最低且与 current_host 不同的主机。"""
        ping_fn = MagicMock(
            return_value=[("fast", 0.01), ("slow", 0.5)]  # 已按延迟升序
        )
        save_fn = MagicMock()

        result = select_best_host_sync(["fast", "slow", "cur"], ping_fn, save_fn, 7709, 1.0, "cur")
        assert result == "fast"
        ping_fn.assert_called_once_with(["fast", "slow", "cur"], 7709, 1.0)
        save_fn.assert_called_once_with("fast")

    def test_skips_current_host_even_if_it_is_fastest(self) -> None:
        """当前主机恰好延迟最低时，应跳过它取次优。"""
        ping_fn = MagicMock(return_value=[("cur", 0.01), ("other", 0.02)])
        save_fn = MagicMock()

        result = select_best_host_sync(["cur", "other"], ping_fn, save_fn, 7709, 1.0, "cur")
        assert result == "other"
        save_fn.assert_called_once_with("other")

    def test_returns_none_when_only_current_reachable(self) -> None:
        """只有当前主机可达时返回 None（不切换、不持久化）。"""
        ping_fn = MagicMock(return_value=[("cur", 0.01)])
        save_fn = MagicMock()

        result = select_best_host_sync(["cur"], ping_fn, save_fn, 7709, 1.0, "cur")
        assert result is None
        save_fn.assert_not_called()

    def test_returns_none_when_no_host_reachable(self) -> None:
        """所有候选都不可达时返回 None。"""
        ping_fn = MagicMock(return_value=[])
        save_fn = MagicMock()

        result = select_best_host_sync(["a", "b"], ping_fn, save_fn, 7709, 1.0, "cur")
        assert result is None
        save_fn.assert_not_called()

    def test_throttle_skips_ping_within_window(self) -> None:
        """节流窗口内（30s）第二次调用直接返回 None，不触发测速。"""
        ping_fn = MagicMock(return_value=[("other", 0.01)])
        save_fn = MagicMock()

        # 第一次：正常测速，返回 other
        first = select_best_host_sync(["cur", "other"], ping_fn, save_fn, 7709, 1.0, "cur")
        assert first == "other"
        assert ping_fn.call_count == 1

        # 第二次（立即）：应被节流，跳过测速
        second = select_best_host_sync(["cur", "other"], ping_fn, save_fn, 7709, 1.0, "cur")
        assert second is None
        # 测速调用次数不应增加
        assert ping_fn.call_count == 1

    def test_throttle_window_is_configurable_constant(self) -> None:
        """节流窗口常量存在且为正（防回归：误改成 0 会关闭节流）。"""
        assert _FAILOVER_PING_THROTTLE_SEC > 0


# --------------------------------------------------------------------------- #
# find_working_host_sync 单元逻辑（多 host 轮询直到验证通过）
# --------------------------------------------------------------------------- #


class TestFindWorkingHostSync:
    def test_returns_first_host_passing_validation(self) -> None:
        """按延迟顺序逐台测试，返回第一台通过验证的 host。"""
        ranked = [("fast", 0.01), ("mid", 0.05), ("slow", 0.5)]
        # fast 验证失败，mid 通过
        try_fn = MagicMock(side_effect=[False, True, True])
        save_fn = MagicMock()

        result = find_working_host_sync(ranked, try_fn, save_fn, "cur")
        assert result == "mid"
        save_fn.assert_called_once_with("mid")
        # 只测到通过那台为止（slow 未被测试）
        assert try_fn.call_count == 2

    def test_skips_current_host(self) -> None:
        """跳过 current_host，不对其调用验证函数。"""
        ranked = [("cur", 0.01), ("other", 0.02)]
        try_fn = MagicMock(return_value=True)
        save_fn = MagicMock()

        result = find_working_host_sync(ranked, try_fn, save_fn, "cur")
        assert result == "other"
        # cur 被跳过，只验证了 other
        try_fn.assert_called_once_with("other")

    def test_returns_none_when_all_fail_validation(self) -> None:
        """所有候选验证都失败时返回 None。"""
        ranked = [("a", 0.01), ("b", 0.02)]
        try_fn = MagicMock(return_value=False)
        save_fn = MagicMock()

        result = find_working_host_sync(ranked, try_fn, save_fn, "cur")
        assert result is None
        save_fn.assert_not_called()

    def test_respects_max_attempts(self) -> None:
        """max_attempts 限制最多测试的候选数。"""
        ranked = [("a", 0.01), ("b", 0.02), ("c", 0.03)]
        try_fn = MagicMock(return_value=False)
        save_fn = MagicMock()

        result = find_working_host_sync(ranked, try_fn, save_fn, "cur", max_attempts=2)
        assert result is None
        # 只测了前 2 台（受 max_attempts 限制），c 未测
        assert try_fn.call_count == 2

    def test_validation_exception_skips_host_not_aborts(self) -> None:
        """单台验证抛异常只跳过该台，继续尝试下一台。"""
        ranked = [("boom", 0.01), ("good", 0.02)]
        save_fn = MagicMock()

        def _try(host: str) -> bool:
            if host == "boom":
                raise RuntimeError("connection refused")
            return True

        result = find_working_host_sync(ranked, _try, save_fn, "cur")
        assert result == "good"
        save_fn.assert_called_once_with("good")

    def test_default_max_attempts_constant(self) -> None:
        """默认 max_attempts 常量存在且合理（防回归）。"""
        assert _WORKING_HOST_MAX_ATTEMPTS == 5


# --------------------------------------------------------------------------- #
# TdxClient._execute 跨主机故障转移
# --------------------------------------------------------------------------- #


class TestTdxClientFailover:
    def setup_method(self) -> None:
        import easy_tdx._reconnect as r

        r._last_failover_ts = 0.0

    def test_failover_switches_host_after_retries_exhausted(self) -> None:
        """同主机 4 次重试全失败后，应跨主机切到新 host 并成功。"""
        with (
            patch("easy_tdx.client.TdxConnection") as mock_conn_cls,
            patch("easy_tdx.client.time.sleep"),
            patch("easy_tdx.client.select_best_host_sync", return_value="new-host") as mock_select,
        ):
            mock_conn = MagicMock()
            # 首次 + 4 次重试全失败，第 6 次（failover 后）成功
            mock_conn.execute.side_effect = [
                TdxConnectionError("down"),  # 首次
                TdxConnectionError("down"),  # 重试1
                TdxConnectionError("down"),  # 重试2
                TdxConnectionError("down"),  # 重试3
                TdxConnectionError("down"),  # 重试4
                1234,  # failover 到新 host 后成功
            ]
            mock_conn_cls.return_value = mock_conn

            client = TdxClient("bad-host", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)
            result = client._execute(GetSecurityCountCmd(Market.SH))

            assert result == 1234
            # failover 被调用，且传入的 current_host 是坏主机
            mock_select.assert_called_once()
            args = mock_select.call_args
            assert args.args[-1] == "bad-host"  # current_host
            # client 的 host 已切换到新主机
            assert client._host == "new-host"

    def test_failover_returns_none_keeps_host_and_raises(self) -> None:
        """failover 未找到更优 host（返回 None）时，保持原 host 并抛出。"""
        with (
            patch("easy_tdx.client.TdxConnection") as mock_conn_cls,
            patch("easy_tdx.client.time.sleep"),
            patch("easy_tdx.client.select_best_host_sync", return_value=None),
        ):
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = TdxConnectionError("always down")
            mock_conn_cls.return_value = mock_conn

            client = TdxClient("bad-host", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)
            with pytest.raises(TdxConnectionError):
                client._execute(GetSecurityCountCmd(Market.SH))
            # host 未被切换
            assert client._host == "bad-host"

    def test_no_failover_when_auto_reconnect_disabled(self) -> None:
        """auto_reconnect=False 时首次失败立即抛出，不进入 failover。"""
        with (
            patch("easy_tdx.client.TdxConnection") as mock_conn_cls,
            patch("easy_tdx.client.time.sleep"),
            patch("easy_tdx.client.select_best_host_sync") as mock_select,
        ):
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = TdxConnectionError("down")
            mock_conn_cls.return_value = mock_conn

            client = TdxClient("bad-host", 7709, 1.0, auto_reconnect=False, heartbeat_interval=0)
            with pytest.raises(TdxConnectionError):
                client._execute(GetSecurityCountCmd(Market.SH))
            # failover 完全未被调用
            mock_select.assert_not_called()


# --------------------------------------------------------------------------- #
# MacClient 跨主机故障转移（v1.19.4 兼容性：不污染标准 best_host）
# --------------------------------------------------------------------------- #


class TestMacClientFailover:
    """锁定 v1.19.4 修复：MacClient 的 failover 必须用 save_best_mac_host，
    而非 save_best_host，否则会把 MAC 服务器写进标准 best_host 配置项造成污染。

    该 bug 曾在将 failover 改动从旧分支 cherry-pick 到含 v1.19.4 修复的 main 时
    复现（_execute 的 failover 沿用了旧的 save_best_host）。本测试防止再次倒退。
    """

    def setup_method(self) -> None:
        import easy_tdx._reconnect as r

        r._last_failover_ts = 0.0

    def test_failover_uses_save_best_mac_host_not_save_best_host(self) -> None:
        """MacClient failover 持久化时必须调 save_best_mac_host。"""
        from easy_tdx.mac.client import MacClient
        from easy_tdx.mac.commands.kline_offset import KlineOffsetCmd

        with (
            patch("easy_tdx.mac.client.TdxConnection") as mock_conn_cls,
            patch("easy_tdx.mac.client.time.sleep"),
            patch(
                "easy_tdx.mac.client.select_best_host_sync", return_value="new-mac-host"
            ) as mock_select,
        ):
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = [
                TdxConnectionError("down"),
                TdxConnectionError("down"),
                TdxConnectionError("down"),
                TdxConnectionError("down"),
                TdxConnectionError("down"),
                999,  # failover 后成功
            ]
            mock_conn_cls.return_value = mock_conn

            client = MacClient("bad-mac-host", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)
            client._execute(KlineOffsetCmd(0, 1))

            mock_select.assert_called_once()
            # 第 3 个位置参数是 save_fn，必须是 save_best_mac_host（防 v1.19.4 回归）
            from easy_tdx.config import save_best_mac_host

            save_fn = mock_select.call_args.args[2]
            assert save_fn is save_best_mac_host, (
                "MacClient failover 必须用 save_best_mac_host，"
                "否则污染标准 best_host（v1.19.4 修复）"
            )


# --------------------------------------------------------------------------- #
# get_market_stat 空数据故障转移
# --------------------------------------------------------------------------- #


class TestMarketStatEmptyFailover:
    def setup_method(self) -> None:
        import easy_tdx._reconnect as r

        r._last_failover_ts = 0.0

    def _make_quote(self) -> object:
        """构造一个字段合法的统计指数 quote，让 get_market_stat 计算路径走通。"""
        from easy_tdx.models.quote import SecurityQuote

        # 880005：price=涨家数/10, open=跌家数/10, low=平/10, high=总数/10
        return SecurityQuote(
            market=Market.SH,
            code="880005",
            price=159.3,  # → up=1593
            pre_close=0.0,
            open=379.0,  # → down=3790
            high=552.8,  # → total=5528
            low=13.5,  # → neutral=135
            vol=0.0,
            cur_vol=0.0,
            amount=2.58e12,
            s_vol=0.0,
            b_vol=0.0,
            active1=0,
            active2=0,
            bid1=0.0,
            bid_vol1=0.0,
            bid2=0.0,
            bid_vol2=0.0,
            bid3=0.0,
            bid_vol3=0.0,
            bid4=0.0,
            bid_vol4=0.0,
            bid5=0.0,
            bid_vol5=0.0,
            ask1=0.0,
            ask_vol1=0.0,
            ask2=0.0,
            ask_vol2=0.0,
            ask3=0.0,
            ask_vol3=0.0,
            ask4=0.0,
            ask_vol4=0.0,
            ask5=0.0,
            ask_vol5=0.0,
            rise_speed=0.0,
            limit_up=None,
            limit_down=None,
        )

    def test_empty_quotes_finds_working_host_and_returns_data(self) -> None:
        """空 quotes 时按延迟顺序逐台实测，找到返回数据的 host。"""
        quote = self._make_quote()
        client = TdxClient("bad-host", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)

        # _execute: 首次空（bad-host）→ 验证 hostA 空 → 验证 hostB 非空 → 最终再取一次
        with (
            patch.object(client, "_execute", side_effect=[[], [], [quote], [quote]]) as mock_exec,
            patch.object(client, "_reconnect") as mock_reconnect,
            patch(
                "easy_tdx.client.ping_all",
                return_value=[("hostA", 0.01), ("hostB", 0.02)],
            ),
        ):
            df = client.get_market_stat()

        # _execute 调用序列：1 首次 + 2 次 find_working_host 验证(hostA空、hostB非空) + 1 最终取值
        assert mock_exec.call_count == 4
        # _reconnect 切换到 hostA、hostB（逐台实测），最终停在 hostB
        reconnect_hosts = [c.args[0] for c in mock_reconnect.call_args_list]
        assert reconnect_hosts == ["hostA", "hostB"]
        assert len(df) == 1

    def test_empty_quotes_all_candidates_empty_raises(self) -> None:
        """所有候选都返回空时，抛 RuntimeError。"""
        client = TdxClient("bad-host", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)

        with (
            patch.object(client, "_execute", return_value=[]),
            patch.object(client, "_reconnect") as mock_reconnect,
            patch(
                "easy_tdx.client.ping_all",
                return_value=[("hostA", 0.01), ("hostB", 0.02)],
            ),
        ):
            with pytest.raises(RuntimeError, match="无法获取市场统计数据"):
                client.get_market_stat()

        # find_working_host 逐台实测了 hostA、hostB（_reconnect 被各调一次）
        reconnect_hosts = [c.args[0] for c in mock_reconnect.call_args_list]
        assert reconnect_hosts == ["hostA", "hostB"]


# --------------------------------------------------------------------------- #
# 健康分联动：select_best_host / find_working_host 感知健康分
# --------------------------------------------------------------------------- #


class TestHealthAwareFailover:
    """验证故障转移会读取/写入健康分：坏主机被降权后排序靠后。"""

    def test_select_best_host_skips_cooldown_host(self) -> None:
        """冷却中的主机即使延迟最低，也不会被 select_best_host 选中。"""
        from easy_tdx._health import record_failure

        # host-fast 连续失败进入冷却
        for _ in range(3):
            record_failure("host-fast")

        ping_fn = MagicMock(return_value=[("host-fast", 0.01), ("host-slow", 0.10)])
        save_fn = MagicMock()
        result = select_best_host_sync(
            ["host-fast", "host-slow", "cur"], ping_fn, save_fn, 7709, 1.0, "cur"
        )
        # host-fast 在冷却中被剔除，应选 host-slow
        assert result == "host-slow"
        save_fn.assert_called_once_with("host-slow")

    def test_find_working_host_records_failure_on_empty(self) -> None:
        """候选返回空数据时记一次 failure（降权），下次轮询优先级下降。"""
        from easy_tdx._health import get_score

        ranked = [("empty-host", 0.01), ("good-host", 0.02)]
        try_fn = MagicMock(side_effect=[False, True])  # empty 空，good 非空
        save_fn = MagicMock()

        result = find_working_host_sync(ranked, try_fn, save_fn, "cur")
        assert result == "good-host"
        # empty-host 被记一次失败，score < 1.0
        assert get_score("empty-host") < 1.0
        # good-host 被记成功，score = 1.0
        assert get_score("good-host") == 1.0

    def test_find_working_host_records_success_on_hit(self) -> None:
        """命中的主机 score 恢复到 1.0。"""
        from easy_tdx._health import get_score, record_failure

        # 先把 good-host 降权
        record_failure("good-host")
        assert get_score("good-host") < 1.0

        ranked = [("good-host", 0.01)]
        try_fn = MagicMock(return_value=True)
        save_fn = MagicMock()

        find_working_host_sync(ranked, try_fn, save_fn, "cur")
        # 命中后 score 恢复（+0.2，但初始降权后 0.5+0.2=0.7，未到 1.0；
        # 关键是比失败前上升了）
        assert get_score("good-host") > _FAILURE_DECAY


# --------------------------------------------------------------------------- #
# get_index_bars / get_security_bars 空数据故障转移
# （指数/板块指数 880xxx 并非所有服务器都提供，空时逐台实测切 host）
# --------------------------------------------------------------------------- #


class TestBarsEmptyFailover:
    """K 线空数据故障转移——验证 get_index_bars/get_security_bars 空时逐台实测切 host。"""

    def _make_bar(self) -> SecurityBar:
        """构造一根字段合法的日 K，让 get_index_bars 下游处理走通。"""
        return SecurityBar(
            open=10.0,
            close=10.5,
            high=10.8,
            low=9.9,
            vol=1000.0,
            amount=10500.0,
            year=2026,
            month=7,
            day=10,
            hour=15,
            minute=0,
        )

    def test_empty_bars_finds_working_host_and_returns_data(self) -> None:
        """空 bars 时按延迟顺序逐台实测，找到返回数据的 host。"""
        bar = self._make_bar()
        client = TdxClient("bad-host", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)

        # _execute: 首次空（bad-host）→ 验证 hostA 空 → 验证 hostB 非空 → 最终再取一次
        with (
            patch.object(client, "_execute", side_effect=[[], [], [bar], [bar]]) as mock_exec,
            patch.object(client, "_reconnect") as mock_reconnect,
            patch(
                "easy_tdx.client.ping_all",
                return_value=[("hostA", 0.01), ("hostB", 0.02)],
            ),
        ):
            df = client.get_index_bars(Market.SH, "880008", KlineCategory.DAY, 0, 10)

        # _execute 调用序列：1 首次 + 2 次 find_working_host 验证(hostA空、hostB非空) + 1 最终取值
        assert mock_exec.call_count == 4
        # _reconnect 切换到 hostA、hostB（逐台实测），最终停在 hostB
        reconnect_hosts = [c.args[0] for c in mock_reconnect.call_args_list]
        assert reconnect_hosts == ["hostA", "hostB"]
        assert len(df) == 1

    def test_empty_bars_all_candidates_empty_returns_empty_df(self) -> None:
        """所有候选都返回空时，返回空 DataFrame（不抛异常）。"""
        client = TdxClient("bad-host", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)

        with (
            patch.object(client, "_execute", return_value=[]),
            patch.object(client, "_reconnect") as mock_reconnect,
            patch(
                "easy_tdx.client.ping_all",
                return_value=[("hostA", 0.01), ("hostB", 0.02)],
            ),
        ):
            df = client.get_index_bars(Market.SH, "880008", KlineCategory.DAY, 0, 10)

        # find_working_host 逐台实测了 hostA、hostB（_reconnect 被各调一次）
        reconnect_hosts = [c.args[0] for c in mock_reconnect.call_args_list]
        assert reconnect_hosts == ["hostA", "hostB"]
        assert df.empty

    def test_non_empty_bars_does_not_trigger_failover(self) -> None:
        """首次即返回数据时，不触发空数据故障转移。"""
        bar = self._make_bar()
        client = TdxClient("good-host", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)

        with (
            patch.object(client, "_execute", return_value=[bar]) as mock_exec,
            patch.object(client, "_find_host_returning_data") as mock_failover,
        ):
            df = client.get_index_bars(Market.SH, "880008", KlineCategory.DAY, 0, 10)

        assert mock_exec.call_count == 1
        mock_failover.assert_not_called()
        assert len(df) == 1

    def test_failover_disabled_when_auto_reconnect_off(self) -> None:
        """auto_reconnect=False 时空数据不触发故障转移。"""
        client = TdxClient("bad-host", 7709, 1.0, auto_reconnect=False, heartbeat_interval=0)

        with (
            patch.object(client, "_execute", return_value=[]) as mock_exec,
            patch.object(client, "_find_host_returning_data") as mock_failover,
        ):
            df = client.get_index_bars(Market.SH, "880008", KlineCategory.DAY, 0, 10)

        assert mock_exec.call_count == 1
        mock_failover.assert_not_called()
        assert df.empty

    def test_security_bars_also_triggers_failover(self) -> None:
        """get_security_bars（个股 K 线）同样接入空数据故障转移。"""
        bar = self._make_bar()
        client = TdxClient("bad-host", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)

        with (
            patch.object(client, "_execute", side_effect=[[], [], [bar], [bar]]) as mock_exec,
            patch.object(client, "_reconnect"),
            patch(
                "easy_tdx.client.ping_all",
                return_value=[("hostA", 0.01), ("hostB", 0.02)],
            ),
        ):
            df = client.get_security_bars(Market.SH, "600000", KlineCategory.DAY, 0, 10)

        assert mock_exec.call_count == 4
        assert len(df) == 1


# --------------------------------------------------------------------------- #
# get_history_fund_flow 空数据故障转移（Issue #41）
# 部分服务器对常见标的（如 600519）也返回 ret_count 撒谎的空 body，此前直接返回
# 空 DataFrame；v1.20.5 接入与 K 线同源的空数据故障转移，逐台实测找有效 host。
# --------------------------------------------------------------------------- #


class TestFundFlowEmptyFailover:
    """资金流空数据故障转移——验证 get_history_fund_flow 空时逐台实测切 host。"""

    def _make_flow(self) -> HistoricalFundFlow:
        """构造一条字段合法的历史资金流，让 _to_df 下游处理走通。"""
        return HistoricalFundFlow(
            year=2026,
            month=7,
            day=10,
            super_in=1.0,
            super_out=0.0,
            large_in=2.0,
            large_out=0.0,
            medium_in=3.0,
            medium_out=0.0,
            small_in=4.0,
            small_out=0.0,
        )

    def test_empty_fund_flow_finds_working_host_and_returns_data(self) -> None:
        """当前 host 空 → 逐台实测 → hostB 返回数据，停在该 host。"""
        flow = self._make_flow()
        client = TdxClient("bad-host", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)

        # _fetch_fund_flow_records 调用序列：
        #   1. 首次（bad-host）→ 空
        #   2. 验证 hostA → 空
        #   3. 验证 hostB → 非空（命中）
        #   4. 最终再取一次（停在 hostB）→ 非空
        with (
            patch.object(
                client,
                "_fetch_fund_flow_records",
                side_effect=[[], [], [flow], [flow]],
            ) as mock_fetch,
            patch.object(client, "_reconnect") as mock_reconnect,
            patch(
                "easy_tdx.client.ping_all",
                return_value=[("hostA", 0.01), ("hostB", 0.02)],
            ),
        ):
            df = client.get_history_fund_flow(Market.SH, "600519", 0, 10)

        assert mock_fetch.call_count == 4
        # _reconnect 切换到 hostA、hostB（逐台实测），最终停在 hostB
        reconnect_hosts = [c.args[0] for c in mock_reconnect.call_args_list]
        assert reconnect_hosts == ["hostA", "hostB"]
        assert len(df) == 1

    def test_empty_fund_flow_all_candidates_empty_returns_empty_df(self) -> None:
        """所有候选都返回空时，返回空 DataFrame（不抛异常）。

        与 get_index_bars / get_security_bars 同源逻辑：真·无数据时换台仍为空，
        返回空而非 raise。``_reconnect`` 被 mock 不更新 ``self._host``，故不会
        再切回 bad-host（与 K 线测试断言一致）。
        """
        client = TdxClient("bad-host", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)

        with (
            patch.object(client, "_fetch_fund_flow_records", return_value=[]),
            patch.object(client, "_reconnect") as mock_reconnect,
            patch(
                "easy_tdx.client.ping_all",
                return_value=[("hostA", 0.01), ("hostB", 0.02)],
            ),
        ):
            df = client.get_history_fund_flow(Market.SH, "600519", 0, 10)

        # find_working_host 逐台实测了 hostA、hostB（_reconnect 被各调一次）
        reconnect_hosts = [c.args[0] for c in mock_reconnect.call_args_list]
        assert reconnect_hosts == ["hostA", "hostB"]
        assert df.empty

    def test_non_empty_fund_flow_does_not_trigger_failover(self) -> None:
        """首次即返回数据时，不触发空数据故障转移。"""
        flow = self._make_flow()
        client = TdxClient("good-host", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0)

        with (
            patch.object(client, "_fetch_fund_flow_records", return_value=[flow]) as mock_fetch,
            patch.object(client, "_fund_flow_failover") as mock_failover,
        ):
            df = client.get_history_fund_flow(Market.SH, "600519", 0, 10)

        assert mock_fetch.call_count == 1
        mock_failover.assert_not_called()
        assert len(df) == 1

    def test_failover_disabled_when_auto_reconnect_off(self) -> None:
        """auto_reconnect=False 时空数据不触发故障转移。"""
        client = TdxClient("bad-host", 7709, 1.0, auto_reconnect=False, heartbeat_interval=0)

        with (
            patch.object(client, "_fetch_fund_flow_records", return_value=[]) as mock_fetch,
            patch.object(client, "_fund_flow_failover") as mock_failover,
        ):
            df = client.get_history_fund_flow(Market.SH, "600519", 0, 10)

        assert mock_fetch.call_count == 1
        mock_failover.assert_not_called()
        assert df.empty


# --------------------------------------------------------------------------- #
# AsyncTdxClient.get_history_fund_flow 空数据故障转移（Issue #41，async 对称）
# --------------------------------------------------------------------------- #


class TestAsyncFundFlowEmptyFailover:
    """资金流空数据故障转移——async 版与 sync 语义对称。"""

    def _make_flow(self) -> HistoricalFundFlow:
        return HistoricalFundFlow(
            year=2026,
            month=7,
            day=10,
            super_in=1.0,
            super_out=0.0,
            large_in=2.0,
            large_out=0.0,
            medium_in=3.0,
            medium_out=0.0,
            small_in=4.0,
            small_out=0.0,
        )

    def test_async_empty_fund_flow_finds_working_host(self) -> None:
        """当前 host 空 → 逐台实测 → hostB 返回数据。"""
        from easy_tdx.client import AsyncTdxClient

        flow = self._make_flow()

        async def main() -> int:
            client = AsyncTdxClient(
                "bad-host", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0
            )
            with (
                patch.object(
                    client,
                    "_fetch_fund_flow_records",
                    side_effect=[[], [], [flow], [flow]],
                ) as mock_fetch,
                patch.object(client, "_areconnect") as mock_reconnect,
                patch(
                    "easy_tdx.client.ping_all",
                    return_value=[("hostA", 0.01), ("hostB", 0.02)],
                ),
            ):
                df = await client.get_history_fund_flow(Market.SH, "600519", 0, 10)

            assert mock_fetch.call_count == 4
            reconnect_hosts = [c.args[0] for c in mock_reconnect.call_args_list]
            assert reconnect_hosts == ["hostA", "hostB"]
            return len(df)

        assert asyncio.run(main()) == 1

    def test_async_non_empty_fund_flow_does_not_trigger_failover(self) -> None:
        """首次即返回数据时，不触发空数据故障转移。"""
        from easy_tdx.client import AsyncTdxClient

        flow = self._make_flow()

        async def main() -> int:
            client = AsyncTdxClient(
                "good-host", 7709, 1.0, auto_reconnect=True, heartbeat_interval=0
            )
            with (
                patch.object(
                    client, "_fetch_fund_flow_records", return_value=[flow]
                ) as mock_fetch,
                patch.object(client, "_fund_flow_failover") as mock_failover,
            ):
                df = await client.get_history_fund_flow(Market.SH, "600519", 0, 10)

            assert mock_fetch.call_count == 1
            mock_failover.assert_not_called()
            return len(df)

        assert asyncio.run(main()) == 1
