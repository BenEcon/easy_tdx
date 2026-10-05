"""扩展行情高层 API：ExTdxClient（同步）和 AsyncExTdxClient（asyncio）。"""

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable
from types import TracebackType
from typing import TypeVar

from .._df import _apply_bar_time_align_bars, _category_to_minutes
from .._health import record_failure, record_success
from .._reconnect import (
    _RETRY_DELAYS,
    AsyncHeartbeatMixin,
    select_best_host_async,
    select_best_host_sync,
)
from ..commands.base import BaseCommand
from ..config import get_best_ex_host, get_ex_hosts, save_best_ex_host
from ..exceptions import TdxConnectionError
from .commands.get_history_bars_range import GetExHistoryInstrumentBarsRangeCmd
from .commands.get_instrument_bars import GetExInstrumentBarsCmd
from .commands.get_instrument_count import GetExInstrumentCountCmd
from .commands.get_instrument_info import GetExInstrumentInfoCmd
from .commands.get_instrument_quote import GetExInstrumentQuoteCmd
from .commands.get_instrument_quote_list import GetExInstrumentQuoteListCmd
from .commands.get_markets import GetExMarketsCmd
from .commands.get_minute_time import (
    GetExHistoryMinuteTimeDataCmd,
    GetExMinuteTimeDataCmd,
)
from .commands.get_transaction import (
    GetExHistoryTransactionDataCmd,
    GetExTransactionDataCmd,
)
from .models import (
    ExInstrumentBar,
    ExInstrumentInfo,
    ExInstrumentQuote,
    ExMarketInfo,
    ExMinuteBar,
    ExTransactionRecord,
)
from .transport.async_ import AsyncExTdxConnection
from .transport.sync import ExTdxConnection, ping_ex_all

logger = logging.getLogger(__name__)

_DEFAULT_EX_PORT = 7727
_T = TypeVar("_T")


# ============================================================
# 同步客户端
# ============================================================


class ExTdxClient:
    """同步扩展行情客户端（期货、港股、外股等，端口 7727）。

    使用示例::

        with ExTdxClient("61.152.107.141") as c:
            markets = c.get_markets()
            quote = c.get_instrument_quote(47, "IFL0")
    """

    def __init__(
        self,
        host: str | None = None,
        port: int = _DEFAULT_EX_PORT,
        timeout: float = 15.0,
        auto_reconnect: bool = True,
    ) -> None:
        self._host = host if host is not None else get_best_ex_host()
        self._port = port
        self._timeout = timeout
        self._auto_reconnect = auto_reconnect
        self._conn = ExTdxConnection(self._host, port, timeout)

    @classmethod
    def from_best_host(
        cls,
        hosts: list[str] | None = None,
        port: int = _DEFAULT_EX_PORT,
        timeout: float = 15.0,
        ping_timeout: float = 5.0,
        auto_reconnect: bool = True,
    ) -> "ExTdxClient":
        """测量所有扩展行情服务器延迟，选最低延迟建立连接。自动保存最佳主机。"""
        if hosts is None:
            hosts = get_ex_hosts()
        ranked = ping_ex_all(hosts, port, ping_timeout)
        best = ranked[0][0] if ranked else hosts[0]
        save_best_ex_host(best)
        return cls(best, port, timeout, auto_reconnect)

    @staticmethod
    def ping_all(
        hosts: list[str] | None = None,
        port: int = _DEFAULT_EX_PORT,
        timeout: float = 5.0,
    ) -> list[tuple[str, float]]:
        return ping_ex_all(hosts, port, timeout)

    # ------------------------------------------------------------------ #
    # 连接管理
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        self._conn.connect()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ExTdxClient":
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def _reconnect(self, host: str | None = None) -> None:
        """关闭当前连接并重建（默认连 self._host；传入 host 则切换主机）。

        扩展行情无心跳，重建仅 close → new ExTdxConnection → connect。
        供 ``_execute`` 同主机重试与跨主机故障转移复用。
        """
        target = host if host is not None else self._host
        if host is not None:
            self._host = host
        self._conn.close()
        self._conn = ExTdxConnection(target, self._port, self._timeout)
        self._conn.connect()

    def _execute(self, cmd: "BaseCommand[_T]") -> _T:
        """执行命令；断线时指数退避重试，同主机耗尽则跨主机故障转移。

        两阶段韧性与 A 股/MAC 统一（审计 #2）：先同主机重试 4 次，再跨主机
        故障转移（测速切到另一台扩展行情服务器）。

        健康分联动与 A 股 client 一致（成功记 success、连接失败记 failure）。
        """
        try:
            result = self._conn.execute(cmd)
        except TdxConnectionError:
            if not self._auto_reconnect:
                raise
            record_failure(self._host)
            last_exc: TdxConnectionError | None = None
            for delay in _RETRY_DELAYS:
                time.sleep(delay)
                self._reconnect()
                try:
                    result = self._conn.execute(cmd)
                    record_success(self._host)
                    return result
                except TdxConnectionError as e:
                    last_exc = e
                    record_failure(self._host)
            # 第二阶段：跨主机故障转移
            new_host = select_best_host_sync(
                get_ex_hosts(),
                ping_ex_all,
                save_best_ex_host,
                self._port,
                5.0,
                self._host,
            )
            if new_host is not None:
                self._reconnect(new_host)
                try:
                    result = self._conn.execute(cmd)
                    record_success(self._host)
                    return result
                except TdxConnectionError as e:
                    last_exc = e
                    record_failure(self._host)
            raise last_exc  # type: ignore[misc]
        else:
            record_success(self._host)
            return result

    # ------------------------------------------------------------------ #
    # 市场信息
    # ------------------------------------------------------------------ #

    def get_markets(self) -> list[ExMarketInfo]:
        """获取扩展行情支持的市场列表。"""
        return self._execute(GetExMarketsCmd())

    def get_instrument_count(self) -> int:
        """获取扩展行情商品总数。"""
        return self._execute(GetExInstrumentCountCmd())

    def get_instrument_info(self, start: int, count: int = 100) -> list[ExInstrumentInfo]:
        """获取商品信息列表（分页）。"""
        return self._execute(GetExInstrumentInfoCmd(start, count))

    # ------------------------------------------------------------------ #
    # 行情
    # ------------------------------------------------------------------ #

    def get_instrument_quote(self, market: int, code: str) -> ExInstrumentQuote | None:
        """获取单个商品五档实时行情。"""
        return self._execute(GetExInstrumentQuoteCmd(market, code))

    def get_instrument_quote_list(
        self,
        market: int,
        category: int,
        start: int = 0,
        count: int = 80,
    ) -> list[OrderedDict[str, object]]:
        """按类别获取商品行情列表。"""
        return self._execute(GetExInstrumentQuoteListCmd(market, category, start, count))

    # ------------------------------------------------------------------ #
    # K线
    # ------------------------------------------------------------------ #

    def get_instrument_bars(
        self,
        category: int,
        market: int,
        code: str,
        start: int = 0,
        count: int = 700,
        *,
        bar_time: str = "start",
    ) -> list[ExInstrumentBar]:
        """获取K线数据。

        Args:
            bar_time: 时间戳语义。 ``"start"``（默认）= bar 开始时间（通达信原始）；
                ``"end"`` = bar 右端点（与 Tushare/同花顺对齐）。仅分钟级周期生效。
        """
        bars = self._execute(GetExInstrumentBarsCmd(category, market, code, start, count))
        delta = _category_to_minutes(category)
        return _apply_bar_time_align_bars(
            bars, is_intraday=delta is not None, delta_minutes=delta, bar_time=bar_time
        )

    def get_history_instrument_bars_range(
        self,
        market: int,
        code: str,
        start_date: int,
        end_date: int,
        *,
        bar_time: str = "start",
    ) -> list[ExInstrumentBar]:
        """按日期范围获取历史K线。

        Note:
            ``bar_time="end"`` 需要知道每根 bar 的周期时长，但本接口按日期范围查询、
            不携带周期信息，无法推断。传入 ``"end"`` 时发出 warning 并原样返回（通达信
            原始开始时间）。如需对齐 Tushare，请改用 :meth:`get_instrument_bars`。
        """
        bars = self._execute(GetExHistoryInstrumentBarsRangeCmd(market, code, start_date, end_date))
        if bar_time == "end":
            logger.warning(
                "get_history_instrument_bars_range 不支持 bar_time='end'（缺少周期信息），"
                "原样返回通达信开始时间。"
            )
        return bars

    # ------------------------------------------------------------------ #
    # 分时
    # ------------------------------------------------------------------ #

    def get_minute_time_data(self, market: int, code: str) -> list[ExMinuteBar]:
        """获取当日分时行情数据。"""
        return self._execute(GetExMinuteTimeDataCmd(market, code))

    def get_history_minute_time_data(
        self,
        market: int,
        code: str,
        date: int,
    ) -> list[ExMinuteBar]:
        """获取历史某日分时行情数据（date: YYYYMMDD）。"""
        return self._execute(GetExHistoryMinuteTimeDataCmd(market, code, date))

    # ------------------------------------------------------------------ #
    # 成交
    # ------------------------------------------------------------------ #

    def get_transaction_data(
        self,
        market: int,
        code: str,
        start: int = 0,
        count: int = 1800,
    ) -> list[ExTransactionRecord]:
        """获取当日分笔成交数据。"""
        return self._execute(GetExTransactionDataCmd(market, code, start, count))

    def get_history_transaction_data(
        self,
        market: int,
        code: str,
        date: int,
        start: int = 0,
        count: int = 1800,
    ) -> list[ExTransactionRecord]:
        """获取历史某日分笔成交数据（date: YYYYMMDD）。"""
        return self._execute(GetExHistoryTransactionDataCmd(market, code, date, start, count))


# ============================================================
# 异步客户端
# ============================================================


class AsyncExTdxClient(AsyncHeartbeatMixin):
    """异步扩展行情客户端（asyncio，端口 7727）。

    使用示例::

        async with AsyncExTdxClient("61.152.107.141") as c:
            markets = await c.get_markets()
    """

    def __init__(
        self,
        host: str | None = None,
        port: int = _DEFAULT_EX_PORT,
        timeout: float = 15.0,
        auto_reconnect: bool = True,
        heartbeat_interval: float = 60.0,
    ) -> None:
        self._host = host if host is not None else get_best_ex_host()
        self._port = port
        self._timeout = timeout
        self._auto_reconnect = auto_reconnect
        self._heartbeat_interval = heartbeat_interval
        self._conn = AsyncExTdxConnection(self._host, port, timeout)
        self._execute_lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task[None] | None = None

    @classmethod
    def from_best_host(
        cls,
        hosts: list[str] | None = None,
        port: int = _DEFAULT_EX_PORT,
        timeout: float = 15.0,
        ping_timeout: float = 5.0,
        auto_reconnect: bool = True,
        heartbeat_interval: float = 60.0,
    ) -> "AsyncExTdxClient":
        if hosts is None:
            hosts = get_ex_hosts()
        ranked = ping_ex_all(hosts, port, ping_timeout)
        best = ranked[0][0] if ranked else hosts[0]
        save_best_ex_host(best)
        return cls(best, port, timeout, auto_reconnect, heartbeat_interval)

    @staticmethod
    def ping_all(
        hosts: list[str] | None = None,
        port: int = _DEFAULT_EX_PORT,
        timeout: float = 5.0,
    ) -> list[tuple[str, float]]:
        return ping_ex_all(hosts, port, timeout)

    # ------------------------------------------------------------------ #
    # 连接管理
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        await self._conn.connect()
        self._start_heartbeat()

    async def close(self) -> None:
        await self._stop_heartbeat()
        await self._conn.close()

    async def __aenter__(self) -> "AsyncExTdxClient":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    def _heartbeat_cmd(self) -> Awaitable[object]:
        """心跳使用的轻量请求（get_instrument_count，复用 _execute 重连）。"""
        return self.get_instrument_count()

    async def _areconnect(self, host: str | None = None) -> None:
        """关闭当前连接并重建（默认连 self._host；传入 host 则切换主机）。

        供 ``_execute`` 同主机重试与跨主机故障转移复用。
        """
        target = host if host is not None else self._host
        if host is not None:
            self._host = host
        await self._stop_heartbeat()
        await self._conn.close()
        self._conn = AsyncExTdxConnection(target, self._port, self._timeout)
        await self._conn.connect()
        self._start_heartbeat()

    async def _execute(self, cmd: "BaseCommand[_T]") -> _T:
        """执行命令；断线时指数退避重试，同主机耗尽则跨主机故障转移。

        健康分联动与 sync 版对称。
        """
        async with self._execute_lock:
            try:
                result = await self._conn.execute(cmd)
            except TdxConnectionError:
                if not self._auto_reconnect:
                    raise
                record_failure(self._host)
                last_exc: TdxConnectionError | None = None
                for delay in _RETRY_DELAYS:
                    await asyncio.sleep(delay)
                    await self._areconnect()
                    try:
                        result = await self._conn.execute(cmd)
                        record_success(self._host)
                        return result
                    except TdxConnectionError as e:
                        last_exc = e
                        record_failure(self._host)
                # 第二阶段：跨主机故障转移
                new_host = await select_best_host_async(
                    get_ex_hosts(),
                    ping_ex_all,
                    save_best_ex_host,
                    self._port,
                    5.0,
                    self._host,
                )
                if new_host is not None:
                    await self._areconnect(new_host)
                    try:
                        result = await self._conn.execute(cmd)
                        record_success(self._host)
                        return result
                    except TdxConnectionError as e:
                        last_exc = e
                        record_failure(self._host)
                raise last_exc  # type: ignore[misc]
            else:
                record_success(self._host)
                return result

    # ------------------------------------------------------------------ #
    # 市场信息
    # ------------------------------------------------------------------ #

    async def get_markets(self) -> list[ExMarketInfo]:
        return await self._execute(GetExMarketsCmd())

    async def get_instrument_count(self) -> int:
        return await self._execute(GetExInstrumentCountCmd())

    async def get_instrument_info(
        self,
        start: int,
        count: int = 100,
    ) -> list[ExInstrumentInfo]:
        return await self._execute(GetExInstrumentInfoCmd(start, count))

    # ------------------------------------------------------------------ #
    # 行情
    # ------------------------------------------------------------------ #

    async def get_instrument_quote(
        self,
        market: int,
        code: str,
    ) -> ExInstrumentQuote | None:
        return await self._execute(GetExInstrumentQuoteCmd(market, code))

    async def get_instrument_quote_list(
        self,
        market: int,
        category: int,
        start: int = 0,
        count: int = 80,
    ) -> list[OrderedDict[str, object]]:
        return await self._execute(GetExInstrumentQuoteListCmd(market, category, start, count))

    # ------------------------------------------------------------------ #
    # K线
    # ------------------------------------------------------------------ #

    async def get_instrument_bars(
        self,
        category: int,
        market: int,
        code: str,
        start: int = 0,
        count: int = 700,
        *,
        bar_time: str = "start",
    ) -> list[ExInstrumentBar]:
        """获取K线数据。``bar_time`` 见同步版 :meth:`get_instrument_bars`。"""
        bars = await self._execute(GetExInstrumentBarsCmd(category, market, code, start, count))
        delta = _category_to_minutes(category)
        return _apply_bar_time_align_bars(
            bars, is_intraday=delta is not None, delta_minutes=delta, bar_time=bar_time
        )

    async def get_history_instrument_bars_range(
        self,
        market: int,
        code: str,
        start_date: int,
        end_date: int,
        *,
        bar_time: str = "start",
    ) -> list[ExInstrumentBar]:
        """按日期范围获取历史K线。``bar_time`` 见同步版（不支持 ``"end"``）。"""
        bars = await self._execute(
            GetExHistoryInstrumentBarsRangeCmd(market, code, start_date, end_date)
        )
        if bar_time == "end":
            logger.warning(
                "get_history_instrument_bars_range 不支持 bar_time='end'（缺少周期信息），"
                "原样返回通达信开始时间。"
            )
        return bars

    # ------------------------------------------------------------------ #
    # 分时
    # ------------------------------------------------------------------ #

    async def get_minute_time_data(self, market: int, code: str) -> list[ExMinuteBar]:
        return await self._execute(GetExMinuteTimeDataCmd(market, code))

    async def get_history_minute_time_data(
        self,
        market: int,
        code: str,
        date: int,
    ) -> list[ExMinuteBar]:
        return await self._execute(GetExHistoryMinuteTimeDataCmd(market, code, date))

    # ------------------------------------------------------------------ #
    # 成交
    # ------------------------------------------------------------------ #

    async def get_transaction_data(
        self,
        market: int,
        code: str,
        start: int = 0,
        count: int = 1800,
    ) -> list[ExTransactionRecord]:
        return await self._execute(GetExTransactionDataCmd(market, code, start, count))

    async def get_history_transaction_data(
        self,
        market: int,
        code: str,
        date: int,
        start: int = 0,
        count: int = 1800,
    ) -> list[ExTransactionRecord]:
        return await self._execute(GetExHistoryTransactionDataCmd(market, code, date, start, count))
