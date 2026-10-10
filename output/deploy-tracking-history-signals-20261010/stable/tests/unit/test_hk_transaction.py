"""港股逐笔成交协议路由的回归测试（issue #14）。

issue #14：``MacExClient.goods_transaction`` 对港股返回空。根因是它对所有扩展市场
复用了 A 股 MAC 协议的 ``SymbolTransactionCmd``（0x122F），而 0x122F 的数据源未接入
港股。修复后港股股票类市场走 ex 扩展行情协议（当日 0x23FC / 历史 0x2406）。

本测试纯离线：

  1. 用录制的真实港股 0x2406 响应 fixture 验证 ``GetExHistoryTransactionDataCmd``
     解析正确（价格字段为整数）。
  2. 验证 ``ExTransactionRecord → MacTransaction`` 字段映射 + 价格 ÷1000 换算。
  3. 验证 ``is_hk_stock_market`` 市场判定边界。
  4. mock ``_execute``，验证 ``MacExClient.goods_transaction`` 对港股（market=31）
     走 ex 协议路径、对其他扩展市场（market=47 期货）仍走 0x122F 路径，避免回归。
"""

from __future__ import annotations

import json
import pathlib
from datetime import date, time

import pytest

from easy_tdx.ex._hk_transaction import (
    HK_STOCK_MARKETS,
    _fetch_hk_transactions_sync,
    _map_record,
    is_hk_stock_market,
)
from easy_tdx.ex.commands.get_transaction import (
    GetExHistoryTransactionDataCmd,
    GetExTransactionDataCmd,
)
from easy_tdx.ex.models import ExTransactionRecord
from easy_tdx.mac.commands.symbol_transaction import SymbolTransactionCmd
from easy_tdx.mac.models import MacTransaction

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"


def load_hex(name: str) -> bytes:
    return bytes.fromhex((FIXTURES / f"{name}.hex").read_text(encoding="utf-8").strip())


def load_json(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. ex 历史 0x2406 协议解析（fixture 来自真实港股 00700 响应）
# ---------------------------------------------------------------------------


def test_parse_ex_history_transaction_hk():
    """港股 0x2406 响应解析：返回非空，price 为整数（单位 0.001 HKD）。"""
    body = load_hex("ex_history_transaction")
    expected = load_json("ex_history_transaction")

    cmd = GetExHistoryTransactionDataCmd(31, "00700", 20260703, 0, 10)
    recs = cmd.parse_response(body)

    assert len(recs) == expected["num_records"]

    # 首条字段
    r0 = recs[0]
    assert r0.hour == expected["first"]["hour"]
    assert r0.minute == expected["first"]["minute"]
    assert r0.second == expected["first"]["second"]
    assert r0.price == expected["first"]["price_int"]  # 整数，未换算
    assert isinstance(r0.price, int)
    assert r0.volume == expected["first"]["vol"]

    # 末条（收盘集合竞价大单）
    rN = recs[-1]
    assert rN.hour == expected["last"]["hour"]
    assert rN.price == expected["last"]["price_int"]
    assert rN.volume == expected["last"]["vol"]


def test_parse_ex_history_transaction_empty():
    """空响应（< 16 字节）应返回空列表，不抛异常。"""
    cmd = GetExHistoryTransactionDataCmd(31, "00700", 20260701, 0, 10)
    assert cmd.parse_response(b"") == []
    assert cmd.parse_response(b"\x00" * 10) == []


# ---------------------------------------------------------------------------
# 2. ExTransactionRecord → MacTransaction 映射 + 价格换算
# ---------------------------------------------------------------------------


def test_map_record_price_conversion():
    """整数价格 431800 → 431.8 港元浮点。"""
    rec = ExTransactionRecord(
        hour=15,
        minute=59,
        second=0,
        price=431800,
        volume=300,
        zengcang=0,
        nature=0,
    )
    mt = _map_record(rec)

    assert isinstance(mt, MacTransaction)
    assert mt.time == time(15, 59, 0)
    assert mt.price == pytest.approx(431.8)
    assert mt.vol == 300
    assert mt.trade_count == 0  # ex 协议无此字段
    assert mt.bs_flag == 0


def test_map_record_nature_to_bs_flag():
    """nature（买卖方向）映射到 bs_flag。"""
    rec = ExTransactionRecord(10, 30, 5, 100000, 1000, 0, nature=1)
    mt = _map_record(rec)
    assert mt.bs_flag == 1
    assert mt.price == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 3. 市场判定边界
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "market,expected",
    [
        (31, True),  # HK_MAIN_BOARD
        (48, True),  # HK_GEM
        (49, True),  # HK_FUND
        (71, True),  # HK_STOCK_GGT
        (98, True),  # HK_DARK_POOL
        (27, True),  # HK_INDEX
        (47, False),  # CFFEX_FUTURES（期货，保持 0x122F）
        (74, False),  # US_STOCK（美股，保持 0x122F）
        (23, False),  # HK_FINANCIAL_FUTURES（衍生品不在本次路由范围）
        (0, False),  # 沪深京 A 股市场代码
        (1, False),
        (2, False),
    ],
)
def test_is_hk_stock_market(market: int, expected: bool):
    assert is_hk_stock_market(market) is expected


def test_hk_stock_markets_constant():
    """常量集合稳定，防止误改。"""
    assert HK_STOCK_MARKETS == frozenset({27, 31, 48, 49, 71, 98})


# ---------------------------------------------------------------------------
# 4. MacExClient.goods_transaction 路由（mock _execute，离线）
# ---------------------------------------------------------------------------


def _build_fake_records(n: int) -> list:
    """构造 n 条 ExTransactionRecord。"""
    return [
        ExTransactionRecord(
            hour=15,
            minute=59,
            second=0,
            price=431800 + i,
            volume=100 * (i + 1),
            zengcang=0,
            nature=i % 3,
        )
        for i in range(n)
    ]


def test_goods_transaction_hk_uses_ex_protocol(monkeypatch):
    """港股 market=31 应走 ex 协议（GetExHistoryTransactionDataCmd），不走 0x122F。"""
    from easy_tdx.ex.mac_client import MacExClient

    captured: list = []

    def fake_execute(cmd):
        captured.append(cmd)
        # 返回 3 条假记录
        return _build_fake_records(3)

    client = object.__new__(MacExClient)
    client._execute = fake_execute  # type: ignore[method-assign]

    df = client.goods_transaction(31, "00700", date(2026, 7, 3), count=3)

    # 应捕获到 GetExHistoryTransactionDataCmd（指定日期 → 0x2406）
    assert len(captured) == 1
    assert isinstance(captured[0], GetExHistoryTransactionDataCmd)
    assert not isinstance(captured[0], SymbolTransactionCmd)

    # 返回 DataFrame 应有数据，价格已换算为港元
    assert len(df) == 3
    assert df["price"].iloc[0] == pytest.approx(431.800)
    assert {"time", "price", "vol", "trade_count", "bs_flag"}.issubset(df.columns)


def test_goods_transaction_hk_today_uses_0x23fc(monkeypatch):
    """港股 query_date=None 应走当日命令 GetExTransactionDataCmd（0x23FC）。"""
    from easy_tdx.ex.mac_client import MacExClient

    captured: list = []

    def fake_execute(cmd):
        captured.append(cmd)
        return _build_fake_records(2)

    client = object.__new__(MacExClient)
    client._execute = fake_execute  # type: ignore[method-assign]

    df = client.goods_transaction(31, "00700", count=2)  # query_date=None

    assert len(captured) == 1
    assert isinstance(captured[0], GetExTransactionDataCmd)
    assert len(df) == 2


def test_goods_transaction_non_hk_keeps_0x122f():
    """非港股市场（如 CFFEX 期货 market=47）仍走 MAC 0x122F，不回归。"""
    from easy_tdx.ex.mac_client import MacExClient

    captured: list = []

    def fake_execute(cmd):
        captured.append(cmd)
        # 0x122F 返回 MacTransaction 列表
        return [
            MacTransaction(time=time(14, 56, 35), price=3850.0, vol=1, trade_count=1, bs_flag=0)
        ]

    client = object.__new__(MacExClient)
    client._execute = fake_execute  # type: ignore[method-assign]

    df = client.goods_transaction(47, "IFL0", count=1)

    assert len(captured) == 1
    assert isinstance(captured[0], SymbolTransactionCmd)
    assert len(df) == 1
    assert df["price"].iloc[0] == pytest.approx(3850.0)


def test_fetch_hk_transactions_pagination():
    """count 超过单页（1800）应自动分页。"""
    page_calls: list[tuple[int, int]] = []

    def fake_execute(cmd):
        # 记录 (offset, count)
        page_calls.append((cmd.start, cmd.count))
        # 第一页返回满页，第二页返回部分（触发停止）
        if cmd.start == 0:
            return _build_fake_records(cmd.count)
        return _build_fake_records(500)  # 不足一页

    # 请求 2000 条，单页 1800 → 第一页 1800 + 第二页 200，第二页只返回 500>200 条会停止
    # 但 fake 第二页返回 500 条 > 请求的 200，按分页逻辑应取 500 但 fetched 已达 2300>2000
    # 实际：page1 size=1800 返回1800, page2 size=min(2000-1800,1800)=200 返回500
    # len(batch)=500 >= page_size=200 → 不触发 < 停止，但 fetched=2300 >= count=2000 退出
    result = _fetch_hk_transactions_sync(fake_execute, 31, "00700", None, 0, 2000)

    assert len(page_calls) == 2
    assert page_calls[0] == (0, 1800)
    assert page_calls[1] == (1800, 200)
    # 第一页 1800 + 第二页实际 500 条（fake 返回），但请求只需 2000，第二页 batch=500
    # 结果 = 1800 + 500 = 2300（fake 多返回了；真实服务器不会超过 page_size）
    assert len(result) == 2300


def test_fetch_hk_transactions_stops_on_empty():
    """空响应应立即停止，不无限循环。"""
    call_count = 0

    def fake_execute(cmd):
        nonlocal call_count
        call_count += 1
        return []

    result = _fetch_hk_transactions_sync(fake_execute, 31, "00700", None, 0, 2000)

    assert call_count == 1  # 第一页空就停
    assert result == []


# ---------------------------------------------------------------------------
# 5. AsyncMacExClient.goods_transaction 异步路由（mock _execute，离线）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_goods_transaction_hk_uses_ex_protocol():
    """异步版港股 market=31 也应走 ex 协议（GetExHistoryTransactionDataCmd）。"""
    from easy_tdx.ex.mac_client import AsyncMacExClient

    captured: list = []

    async def fake_execute(cmd):
        captured.append(cmd)
        return _build_fake_records(3)

    client = object.__new__(AsyncMacExClient)
    client._execute = fake_execute  # type: ignore[method-assign]

    df = await client.goods_transaction(31, "00700", date(2026, 7, 3), count=3)

    assert len(captured) == 1
    assert isinstance(captured[0], GetExHistoryTransactionDataCmd)
    assert not isinstance(captured[0], SymbolTransactionCmd)
    assert len(df) == 3
    assert df["price"].iloc[0] == pytest.approx(431.800)


@pytest.mark.asyncio
async def test_async_goods_transaction_non_hk_keeps_0x122f():
    """异步版非港股市场（期货 market=47）仍走 MAC 0x122F。"""
    from easy_tdx.ex.mac_client import AsyncMacExClient

    captured: list = []

    async def fake_execute(cmd):
        captured.append(cmd)
        return [
            MacTransaction(time=time(14, 56, 35), price=3850.0, vol=1, trade_count=1, bs_flag=0)
        ]

    client = object.__new__(AsyncMacExClient)
    client._execute = fake_execute  # type: ignore[method-assign]

    df = await client.goods_transaction(47, "IFL0", count=1)

    assert len(captured) == 1
    assert isinstance(captured[0], SymbolTransactionCmd)
    assert len(df) == 1
    assert df["price"].iloc[0] == pytest.approx(3850.0)


# ---------------------------------------------------------------------------
# 6. goods_transaction_all 全量取数（mock _execute，离线）
# ---------------------------------------------------------------------------


def test_goods_transaction_all_paginates_until_short_page():
    """全量取数：翻页直到某页返回不足 page_size（末页）即停。"""
    from easy_tdx.ex.mac_client import MacExClient

    page_calls: list[int] = []  # 记录每页的 start

    def fake_execute(cmd):
        page_calls.append(cmd.start)
        # 前 3 页满页（1800），第 4 页返回 500（末页）
        if cmd.start < 1800 * 3:
            return _build_fake_records(cmd.count)
        return _build_fake_records(500)

    client = object.__new__(MacExClient)
    client._execute = fake_execute  # type: ignore[method-assign]

    df = client.goods_transaction_all(31, "00700", date(2026, 7, 3))

    assert len(page_calls) == 4  # 3 满页 + 1 末页
    assert page_calls == [0, 1800, 3600, 5400]
    assert len(df) == 1800 * 3 + 500


def test_goods_transaction_all_stops_on_empty():
    """全量取数：第一页空（休市日/无数据）应立即返回空。"""
    from easy_tdx.ex.mac_client import MacExClient

    call_count = 0

    def fake_execute(cmd):
        nonlocal call_count
        call_count += 1
        return []

    client = object.__new__(MacExClient)
    client._execute = fake_execute  # type: ignore[method-assign]

    df = client.goods_transaction_all(31, "00700", date(2026, 7, 1))

    assert call_count == 1
    assert len(df) == 0


def test_goods_transaction_all_rejects_non_hk_market():
    """全量取数仅限港股股票类市场；其他市场应报 ValueError。"""
    from easy_tdx.ex.mac_client import MacExClient

    client = object.__new__(MacExClient)
    client._execute = lambda cmd: []  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="港股股票类市场"):
        client.goods_transaction_all(47, "IFL0")  # CFFEX 期货


@pytest.mark.asyncio
async def test_async_goods_transaction_all_paginates():
    """异步全量取数也按页翻到末页停止。"""
    from easy_tdx.ex.mac_client import AsyncMacExClient

    page_calls: list[int] = []

    async def fake_execute(cmd):
        page_calls.append(cmd.start)
        # 前 1 页满页，第 2 页返回 100（末页）
        if cmd.start == 0:
            return _build_fake_records(cmd.count)
        return _build_fake_records(100)

    client = object.__new__(AsyncMacExClient)
    client._execute = fake_execute  # type: ignore[method-assign]

    df = await client.goods_transaction_all(31, "00700", date(2026, 7, 3))

    assert page_calls == [0, 1800]
    assert len(df) == 1800 + 100


@pytest.mark.asyncio
async def test_async_goods_transaction_all_rejects_non_hk():
    """异步全量取数：非港股市场报 ValueError。"""
    from easy_tdx.ex.mac_client import AsyncMacExClient

    client = object.__new__(AsyncMacExClient)

    async def fake_execute(cmd):
        return []

    client._execute = fake_execute  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="港股股票类市场"):
        await client.goods_transaction_all(74, "AAPL")  # 美股
