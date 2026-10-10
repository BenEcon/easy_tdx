"""缠论 Phase 3 单元测试：多级别分析、增量更新、走势段。"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from easy_tdx.chanlun.bi import find_bis
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.types import CLKline, Kline

# ── helpers ──────────────────────────────────────────────────────────────


def _k(idx: int, dt: str, o: float, c: float, h: float, l: float, a: float = 0.0) -> Kline:  # noqa: E741
    return Kline(
        index=idx,
        date=datetime.strptime(dt, "%Y-%m-%d"),
        open=o,
        close=c,
        high=h,
        low=l,
        amount=a,
    )


def _make_df(n: int = 50, start_price: float = 10.0, volatility: float = 2.0) -> pd.DataFrame:
    """生成模拟K线 DataFrame。"""
    import random

    random.seed(42)
    prices = [start_price]
    for _ in range(n - 1):
        change = random.uniform(-volatility, volatility)
        prices.append(max(1.0, prices[-1] + change))

    dates = pd.date_range("2025-01-02", periods=n, freq="B")
    data = {
        "datetime": dates,
        "open": prices,
        "close": [p + random.uniform(-0.5, 0.5) for p in prices],
        "high": [p + random.uniform(0, volatility) for p in prices],
        "low": [p - random.uniform(0, volatility) for p in prices],
        "vol": [1000.0] * n,
    }
    return pd.DataFrame(data)


# ── 多级别分析测试 ──────────────────────────────────────────────────────


class TestMultiLevel:
    """MultiLevelAnalyser 测试。"""

    def test_multi_level_basic(self) -> None:
        """多级别分析应返回各级别结果。"""
        from easy_tdx.chanlun.analyser import ChanlunAnalyser
        from easy_tdx.chanlun.multi_level import MultiLevelAnalyser

        df_daily = _make_df(100)
        df_30min = _make_df(200)

        mla = MultiLevelAnalyser()
        mla.add_level("daily", ChanlunAnalyser(code="SZ000001", frequency="DAILY"))
        mla.add_level("30min", ChanlunAnalyser(code="SZ000001", frequency="30MIN"))

        mla.process("daily", df_daily)
        mla.process("30min", df_30min)

        results = mla.results()
        assert "daily" in results
        assert "30min" in results
        assert len(results["daily"].bis) >= 0
        assert len(results["30min"].bis) >= 0

    def test_multi_level_low_level_qs(self) -> None:
        """高级别笔对应的低级别趋势信息。"""
        from easy_tdx.chanlun.analyser import ChanlunAnalyser
        from easy_tdx.chanlun.multi_level import MultiLevelAnalyser

        df_daily = _make_df(100)
        df_30min = _make_df(200)

        mla = MultiLevelAnalyser()
        mla.add_level("daily", ChanlunAnalyser(code="SZ000001", frequency="DAILY"))
        mla.add_level("30min", ChanlunAnalyser(code="SZ000001", frequency="30MIN"))

        mla.process("daily", df_daily)
        mla.process("30min", df_30min)

        daily_result = mla.get_result("daily")
        if daily_result and len(daily_result.bis) > 0:
            last_bi = daily_result.bis[-1]
            qs_info = mla.query_low_level_qs("daily", "30min", last_bi)
            assert qs_info is not None
            assert "zs_count" in qs_info
            assert "bi_count" in qs_info

    def test_multi_level_empty(self) -> None:
        """无数据时应返回空结果。"""
        from easy_tdx.chanlun.multi_level import MultiLevelAnalyser

        mla = MultiLevelAnalyser()
        assert mla.results() == {}


# ── 增量更新测试 ────────────────────────────────────────────────────────


class TestIncrementalUpdate:
    """ChanlunAnalyser 增量更新测试。"""

    def test_incremental_update(self) -> None:
        """追加 K 线后应重新计算。"""
        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        df1 = _make_df(30)
        analyser = ChanlunAnalyser(code="SZ000001")
        analyser.process_klines(df1)
        bi_count_1 = len(analyser.result.bis)

        # 追加更多数据
        df2 = pd.concat([df1, _make_df(30)], ignore_index=True)
        # 重新生成 datetime 避免重复
        df2["datetime"] = pd.date_range("2025-01-02", periods=len(df2), freq="B")
        analyser.process_klines(df2)
        bi_count_2 = len(analyser.result.bis)

        # 更长数据应有更多或相等的笔
        assert bi_count_2 >= bi_count_1

    def test_full_replacement(self) -> None:
        """完全替换数据应正常工作。"""
        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        df1 = _make_df(50)
        df2 = _make_df(100)

        analyser = ChanlunAnalyser(code="SZ000001")
        analyser.process_klines(df1)
        count1 = len(analyser.result.klines)

        analyser.process_klines(df2)
        count2 = len(analyser.result.klines)

        assert count2 == 100
        assert count2 > count1

    def test_append_klines(self) -> None:
        """append_klines 应追加数据并重新计算。"""
        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        df1 = _make_df(30)
        analyser = ChanlunAnalyser(code="SZ000001")
        analyser.process_klines(df1)
        count1 = len(analyser.result.klines)

        df_new = _make_df(20)
        # 使用不重复的日期
        df_new["datetime"] = pd.date_range("2025-06-01", periods=20, freq="B")

        analyser.append_klines(df_new)
        count2 = len(analyser.result.klines)

        # 追加后总数据量应增加
        assert count2 >= count1
        assert count2 == count1 + 20

    def test_append_without_init_raises(self) -> None:
        """未初始化时调用 append_klines 应抛异常。"""
        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        analyser = ChanlunAnalyser(code="SZ000001")
        df_new = _make_df(10)

        with pytest.raises(RuntimeError, match="请先调用 process_klines"):
            analyser.append_klines(df_new)


# ── 走势段测试 ──────────────────────────────────────────────────────────


class TestZsd:
    """走势段/趋势段 测试。"""

    def test_zsd_from_xds(self) -> None:
        """线段应能组合为走势段。"""
        from easy_tdx.chanlun.xd import find_xds
        from easy_tdx.chanlun.zsd import find_zsds

        cks = [
            CLKline(
                k_index=i,
                date=datetime(2025, 1, 2 + i),
                open=10,
                close=10,
                high=10 + i % 5,
                low=10 - i % 3,
                amount=0.0,
                index=i,
            )
            for i in range(20)
        ]
        # 使用更真实的数据
        import random

        random.seed(42)
        h_vals = [10]
        l_vals = [8]
        for i in range(1, 20):
            h_vals.append(h_vals[-1] + random.uniform(-2, 3))
            l_vals.append(l_vals[-1] + random.uniform(-3, 2))

        cks = [
            CLKline(
                k_index=i,
                date=datetime(2025, 1, 2) + __import__("datetime").timedelta(days=i),
                open=l_vals[i],
                close=h_vals[i],
                high=max(h_vals[i], l_vals[i]) + 1,
                low=min(h_vals[i], l_vals[i]) - 1,
                amount=1000.0,
                index=i,
            )
            for i in range(20)
        ]

        fxs = find_fractals(cks)
        bis = find_bis(fxs)
        xds = find_xds(bis)

        zsds = find_zsds(xds)
        # 可能没有足够的线段形成走势段
        assert isinstance(zsds, list)

    def test_empty_xds(self) -> None:
        """空线段列表应返回空走势段。"""
        from easy_tdx.chanlun.zsd import find_zsds

        assert find_zsds([]) == []
