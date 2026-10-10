"""港股逐笔成交的协议路由辅助。

背景（issue #14）：``MacExClient.goods_transaction`` 原先对所有扩展市场统一复用
A 股 MAC 协议的 ``SymbolTransactionCmd``（0x122F）。但 0x122F 的数据源只覆盖沪深京
A 股 + 部分扩展市场（美股 / 中金所期货恰好接入），**唯独港股未接入**，服务器对港股
market 一律返回 39 字节空响应（count=0）。

港股逐笔成交的正确协议是 ex 扩展行情层：

  - 当日（``query_date is None``）→ ``GetExTransactionDataCmd``（0x23FC）
  - 历史（指定 ``query_date``）→ ``GetExHistoryTransactionDataCmd``（0x2406）

返回的 ``ExTransactionRecord`` 字段（hour/minute/second/price:int/volume/zengcang/
nature）需映射为与 A 股 ``MacTransaction`` 兼容的 schema，并把整数价格换算为港元
浮点（单位 0.001 HKD，与港股分时图 float 价格一致）。

同步 / 异步共用本模块：``execute_fn`` 由调用方注入——同步版传 ``self._execute``，
异步版传 ``self._execute``（协程回调）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import TypeVar

from ..commands.base import BaseCommand
from ..mac.models import MacTransaction
from .commands.get_transaction import GetExHistoryTransactionDataCmd, GetExTransactionDataCmd
from .models import ExTransactionRecord

# 港股股票类市场（走 ex 协议 0x23FC / 0x2406）。
# 不含衍生品（HK_FINANCIAL_FUTURES=23 / HK_FINANCIAL_OPTIONS=24 / HK_STOCK_FUTURES=25 /
# HK_STOCK_OPTIONS=26）：期货 / 期权逐笔语义不同，且 0x122F 对 CFFEX 期货恰好可用，
# 本次不改变其行为以避免回归。
HK_STOCK_MARKETS: frozenset[int] = frozenset(
    {
        27,  # HK_INDEX 香港指数
        31,  # HK_MAIN_BOARD 香港主板
        48,  # HK_GEM 香港创业板
        49,  # HK_FUND 香港基金
        71,  # HK_STOCK_GGT 港股-港股通
        98,  # HK_DARK_POOL 港股暗盘
    }
)

# ex 协议单页最大返回条数（与 GetExTransactionDataCmd 默认 count 一致）。
_HK_TRANSACTION_PAGE_SIZE = 1800

# 港股价格整数单位：1 港元 = 1000，即返回的 price_int / 1000 = 港元。
# 与港股分时图（0x248b）返回的 float 价格对齐验证过（如 431400 → 431.4 HKD）。
_HK_PRICE_DIVISOR = 1000.0

_T = TypeVar("_T")

# 同步执行回调：传入 BaseCommand，返回其 parse_response 结果
SyncExecute = Callable[[BaseCommand[_T]], _T]
# 异步执行回调：传入 BaseCommand，返回可等待的 parse_response 结果
AsyncExecute = Callable[[BaseCommand[_T]], Awaitable[_T]]


def is_hk_stock_market(market: int) -> bool:
    """判断给定市场代码是否属于港股股票类（需走 ex 协议取逐笔成交）。"""
    return market in HK_STOCK_MARKETS


def _to_ymd(query_date: date) -> int:
    """date → YYYYMMDD int（ex 历史命令的日期参数格式）。"""
    return query_date.year * 10000 + query_date.month * 100 + query_date.day


def _build_cmd(
    market: int,
    code: str,
    ymd: int | None,
    offset: int,
    page_size: int,
) -> BaseCommand[list[ExTransactionRecord]]:
    """根据是否有日期构建对应的 ex 协议命令。"""
    if ymd is None:
        return GetExTransactionDataCmd(market, code, offset, page_size)
    return GetExHistoryTransactionDataCmd(market, code, ymd, offset, page_size)


def _map_record(rec: ExTransactionRecord) -> MacTransaction:
    """把 ex 协议的 ExTransactionRecord 映射为与 A 股一致的 MacTransaction。

    - price: 整数 → 港元浮点（÷1000）
    - vol: volume 原样
    - trade_count: ex 协议无此字段，置 0
    - bs_flag: 取 nature（买卖方向标志，语义近似；0=买/1=卖/2=中性 等）
    - time: 由 hour/minute/second 组合
    """
    from datetime import time as time_cls

    return MacTransaction(
        time=time_cls(rec.hour, rec.minute, rec.second),
        price=rec.price / _HK_PRICE_DIVISOR,
        vol=rec.volume,
        trade_count=0,
        bs_flag=rec.nature,
    )


def _fetch_hk_transactions_sync(
    execute_fn: SyncExecute[list[ExTransactionRecord]],
    market: int,
    code: str,
    query_date: date | None,
    start: int,
    count: int,
) -> list[MacTransaction]:
    """同步获取港股逐笔成交（自动分页）。"""
    ymd = _to_ymd(query_date) if query_date is not None else None

    results: list[MacTransaction] = []
    fetched = 0
    offset = start
    while fetched < count:
        page_size = min(count - fetched, _HK_TRANSACTION_PAGE_SIZE)
        cmd = _build_cmd(market, code, ymd, offset, page_size)
        batch = execute_fn(cmd)
        if not batch:
            break
        results.extend(_map_record(r) for r in batch)
        fetched += len(batch)
        offset += len(batch)
        if len(batch) < page_size:
            break
    return results


async def _fetch_hk_transactions_async(
    execute_fn: AsyncExecute[list[ExTransactionRecord]],
    market: int,
    code: str,
    query_date: date | None,
    start: int,
    count: int,
) -> list[MacTransaction]:
    """异步获取港股逐笔成交（自动分页）。"""
    ymd = _to_ymd(query_date) if query_date is not None else None

    results: list[MacTransaction] = []
    fetched = 0
    offset = start
    while fetched < count:
        page_size = min(count - fetched, _HK_TRANSACTION_PAGE_SIZE)
        cmd = _build_cmd(market, code, ymd, offset, page_size)
        batch = await execute_fn(cmd)
        if not batch:
            break
        results.extend(_map_record(r) for r in batch)
        fetched += len(batch)
        offset += len(batch)
        if len(batch) < page_size:
            break
    return results


# 全量翻页的安全上限：50 页 × 1800 = 90000 条，覆盖港股单日成交峰值绰绰有余。
# 超过即停，防止异常数据（如服务器循环返回）导致无限翻页。
_HK_TRANSACTION_MAX_PAGES = 50


def _fetch_all_hk_transactions_sync(
    execute_fn: SyncExecute[list[ExTransactionRecord]],
    market: int,
    code: str,
    query_date: date | None,
    start: int = 0,
) -> list[MacTransaction]:
    """同步获取港股某日**全部**逐笔成交（自动翻页直至末页）。

    0x23FC/0x2406 响应不含 total 字段，只能按页翻到不足一页或空为止。
    返回顺序与协议一致（倒序：start=0 为最新/收盘方向）。
    """
    ymd = _to_ymd(query_date) if query_date is not None else None

    results: list[MacTransaction] = []
    offset = start
    for _ in range(_HK_TRANSACTION_MAX_PAGES):
        cmd = _build_cmd(market, code, ymd, offset, _HK_TRANSACTION_PAGE_SIZE)
        batch = execute_fn(cmd)
        if not batch:
            break
        results.extend(_map_record(r) for r in batch)
        offset += len(batch)
        if len(batch) < _HK_TRANSACTION_PAGE_SIZE:
            break  # 末页
    return results


async def _fetch_all_hk_transactions_async(
    execute_fn: AsyncExecute[list[ExTransactionRecord]],
    market: int,
    code: str,
    query_date: date | None,
    start: int = 0,
) -> list[MacTransaction]:
    """异步获取港股某日**全部**逐笔成交。语义同同步版 :func:`_fetch_all_hk_transactions_sync`。"""
    ymd = _to_ymd(query_date) if query_date is not None else None

    results: list[MacTransaction] = []
    offset = start
    for _ in range(_HK_TRANSACTION_MAX_PAGES):
        cmd = _build_cmd(market, code, ymd, offset, _HK_TRANSACTION_PAGE_SIZE)
        batch = await execute_fn(cmd)
        if not batch:
            break
        results.extend(_map_record(r) for r in batch)
        offset += len(batch)
        if len(batch) < _HK_TRANSACTION_PAGE_SIZE:
            break  # 末页
    return results
