"""QFQ 本地重算的集成测试（monkeypatch，无 live server）。

验证 ``MacClient.get_stock_kline(adjust=QFQ)`` 在服务端返回负价时：
1. 触发 NONE 重抓 + XDXR 本地重算；
2. 结果全部为正、OHLC 同比缩放；
3. XDXR 取不到时降级返回原始（含负价）数据，不抛异常。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pandas as pd

from easy_tdx.mac.client import MacClient
from easy_tdx.mac.commands.symbol_bar import SymbolBarCmd
from easy_tdx.mac.enums import Adjust, Period
from easy_tdx.mac.models import MacBar


def _bar(dt: str, close: float, fq: Adjust = Adjust.NONE) -> MacBar:
    """构造单根 MacBar，OHLC 全等于 close。"""
    d = datetime.fromisoformat(dt)
    return MacBar(
        datetime=d, open=close, high=close, low=close, close=close, vol=100.0, amount=1000.0
    )


def _none_bars() -> list[MacBar]:
    """干净的 NONE 序列：除权日前 close=10，除权日 close=8（跌去 2 元分红），之后 9。"""
    return [
        _bar("2024-01-01", 10.0),
        _bar("2024-01-02", 10.0),  # cum-div
        _bar("2024-01-03", 8.0),  # ex-date
        _bar("2024-01-04", 9.0),
    ]


def _qfq_broken_bars() -> list[MacBar]:
    """模拟服务端 QFQ 异常：除权日及之前返回负价。"""
    return [
        _bar("2024-01-01", -4.0, Adjust.QFQ),
        _bar("2024-01-02", -4.0, Adjust.QFQ),
        _bar("2024-01-03", 8.0, Adjust.QFQ),
        _bar("2024-01-04", 9.0, Adjust.QFQ),
    ]


def _xdxr_df() -> pd.DataFrame:
    """单条除权除息记录：fenhong=2.0（除权日 2024-01-03）。"""
    return pd.DataFrame(
        [
            {
                "date": "2024-01-03",
                "category": 1,
                "fenhong": 2.0,
                "peigujia": None,
                "songzhuangu": None,
                "peigu": None,
            }
        ]
    )


def _make_client() -> MacClient:
    """构造未连接的 MacClient（仅用于调用 _execute mock 路径）。"""
    client = MacClient.__new__(MacClient)
    client._xdxr_cache = {}
    client._timeout = 10.0
    return client


def test_qfq_negative_triggers_local_recompute():
    """服务端 QFQ 返回负价 → 用 NONE+XDXR 重算，结果全正。"""
    client = _make_client()

    def fake_execute(cmd: SymbolBarCmd) -> list[MacBar]:
        return _qfq_broken_bars() if cmd._fq == Adjust.QFQ else _none_bars()

    with (
        patch.object(client, "_execute", side_effect=fake_execute),
        patch("easy_tdx.client.TdxClient") as MockTdx,
    ):
        # 让 TdxClient 上下文返回手构 XDXR
        mock_inst = MockTdx.from_best_host.return_value.__enter__.return_value
        mock_inst.get_xdxr_info.return_value = _xdxr_df()

        df = client.get_stock_kline(
            market=1,
            code="601088",
            period=Period.DAILY,
            start=0,
            count=4,
            adjust=Adjust.QFQ,
        )

    # 重算后全部为正
    assert (df["close"] > 0).all(), df["close"].tolist()
    # f=(10-2)/10=0.8 → 除权日前两根 *= 0.8 = 8.0；ex-date 及之后不动
    assert df["close"].tolist() == [8.0, 8.0, 8.0, 9.0]
    # OHLC 同比缩放（open 也应被缩放）
    assert df["open"].tolist() == [8.0, 8.0, 8.0, 9.0]


def test_qfq_clean_does_not_trigger_recompute():
    """服务端 QFQ 正常（无负价）→ 不触发重算，原样返回。"""
    client = _make_client()
    clean_qfq = [
        _bar("2024-01-01", 8.0, Adjust.QFQ),
        _bar("2024-01-02", 8.0, Adjust.QFQ),
        _bar("2024-01-03", 8.0, Adjust.QFQ),
        _bar("2024-01-04", 9.0, Adjust.QFQ),
    ]

    with (
        patch.object(client, "_execute", return_value=clean_qfq) as mock_exec,
        patch("easy_tdx.client.TdxClient") as MockTdx,
    ):
        df = client.get_stock_kline(
            market=1,
            code="601088",
            period=Period.DAILY,
            start=0,
            count=4,
            adjust=Adjust.QFQ,
        )
        # QFQ 干净时不应再去拉 XDXR
        MockTdx.from_best_host.assert_not_called()

    assert df["close"].tolist() == [8.0, 8.0, 8.0, 9.0]
    # 只拉了一次（QFQ），没有第二次拉 NONE
    assert mock_exec.call_count == 1


def test_qfq_recompute_xdxr_failure_degrades_gracefully():
    """XDXR 取不到 → 降级返回 NONE 数据（不再含负价），不抛异常。"""
    client = _make_client()

    def fake_execute(cmd: SymbolBarCmd) -> list[MacBar]:
        return _qfq_broken_bars() if cmd._fq == Adjust.QFQ else _none_bars()

    with (
        patch.object(client, "_execute", side_effect=fake_execute),
        patch("easy_tdx.client.TdxClient") as MockTdx,
    ):
        # XDXR 抛异常 → _fetch_xdxr_records 返回 None → 降级
        mock_inst = MockTdx.from_best_host.return_value.__enter__.return_value
        mock_inst.get_xdxr_info.side_effect = RuntimeError("host unreachable")

        df = client.get_stock_kline(
            market=1,
            code="601088",
            period=Period.DAILY,
            start=0,
            count=4,
            adjust=Adjust.QFQ,
        )

    # 降级：返回 NONE 数据（apply_forward_adjust 因 xd=None 原样返回 df）
    # df 是 NONE 重抓结果（全正），但未做前复权
    assert (df["close"] > 0).all()
    assert df["close"].tolist() == [10.0, 10.0, 8.0, 9.0]


def test_none_adjust_skips_recompute():
    """adjust=NONE 时完全跳过 QFQ 重算逻辑。"""
    client = _make_client()
    with (
        patch.object(client, "_execute", return_value=_none_bars()) as mock_exec,
        patch("easy_tdx.client.TdxClient") as MockTdx,
    ):
        df = client.get_stock_kline(
            market=1,
            code="601088",
            period=Period.DAILY,
            start=0,
            count=4,
            adjust=Adjust.NONE,
        )
        MockTdx.from_best_host.assert_not_called()

    assert df["close"].tolist() == [10.0, 10.0, 8.0, 9.0]
    assert mock_exec.call_count == 1
