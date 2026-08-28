"""缠论核心计算 单元测试。"""

from __future__ import annotations

from datetime import datetime

from easy_tdx.chanlun.bi import find_bis
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.kline_merge import merge_klines
from easy_tdx.chanlun.types import CLKline, Direction, FXType, Kline
from easy_tdx.chanlun.zs import find_zss

# ── helpers ──────────────────────────────────────────────────────────────


def _k(
    idx: int,
    dt: str,
    o: float,
    c: float,
    h: float,
    l: float,  # noqa: E741
    a: float = 0.0,
) -> Kline:
    """快速构造 Kline。"""
    return Kline(
        index=idx,
        date=datetime.strptime(dt, "%Y-%m-%d"),
        open=o,
        close=c,
        high=h,
        low=l,
        amount=a,
    )


def _ck(
    idx: int,
    dt: str,
    o: float,
    c: float,
    h: float,
    l: float,  # noqa: E741
    merged_count: int = 1,
    direction: str = "",
) -> CLKline:
    """快速构造 CLKline。"""
    return CLKline(
        k_index=idx,
        date=datetime.strptime(dt, "%Y-%m-%d"),
        open=o,
        close=c,
        high=h,
        low=l,
        amount=0.0,
        index=0,  # 由 merge_klines 赋值
        merged_count=merged_count,
        direction=direction,
    )


# ── K 线合并测试 ──────────────────────────────────────────────────────────


class TestMergeKlines:
    """merge_klines 测试。"""

    def test_no_merge_needed(self) -> None:
        """K 线无包含关系，应原样返回。"""
        klines = [
            _k(0, "2025-01-02", 10, 12, 13, 9),
            _k(1, "2025-01-03", 11, 16, 17, 11),  # 高于前一根高点、低于前根低点 → 无包含
            _k(2, "2025-01-06", 13, 11, 18, 12),  # 继续新高 → 无包含
        ]
        result = merge_klines(klines)
        assert len(result) == 3
        # 每个 CLKline 没有合并
        assert all(ck.merged_count == 1 for ck in result)

    def test_upward_include(self) -> None:
        """向上趋势中的包含关系应合并。

        K1: h=15 l=10  (向上)
        K2: h=13 l=11  ← K2 被 K1 包含 (15>13 and 10<11 => 15>=13 and 10<=11)
        合并后取高高：h=15, l=11
        """
        klines = [
            _k(0, "2025-01-02", 10, 14, 15, 10),
            _k(1, "2025-01-03", 11, 13, 13, 11),
        ]
        result = merge_klines(klines)
        assert len(result) == 1
        assert result[0].high == 15.0
        assert result[0].low == 11.0
        assert result[0].merged_count == 2

    def test_downward_include(self) -> None:
        """向下趋势中的包含关系应合并。

        K1: h=10 l=5   (向下)
        K2: h=9  l=6   ← K2 被 K1 包含 (10>=9 and 5<=6)
        合并后取低低：h=9, l=5
        """
        klines = [
            _k(0, "2025-01-02", 12, 8, 10, 5),
            _k(1, "2025-01-03", 8, 7, 9, 6),
        ]
        result = merge_klines(klines)
        assert len(result) == 1
        assert result[0].high == 9.0
        assert result[0].low == 5.0
        assert result[0].merged_count == 2

    def test_three_klines_with_two_merges(self) -> None:
        """连续包含：三根 K 线合并为一根。"""
        klines = [
            _k(0, "2025-01-02", 10, 14, 15, 10),  # 大阳线
            _k(1, "2025-01-03", 11, 13, 14, 11),  # 被包含
            _k(2, "2025-01-06", 12, 14, 14, 12),  # 被包含
        ]
        result = merge_klines(klines)
        assert len(result) == 1
        assert result[0].merged_count == 3
        # 向上合并：取高高 => h=15, l=12
        assert result[0].high == 15.0
        assert result[0].low == 12.0

    def test_empty_input(self) -> None:
        """空输入返回空列表。"""
        assert merge_klines([]) == []

    def test_single_kline(self) -> None:
        """单根 K 线返回单个 CLKline。"""
        klines = [_k(0, "2025-01-02", 10, 12, 13, 9)]
        result = merge_klines(klines)
        assert len(result) == 1
        assert result[0].high == 13.0
        assert result[0].low == 9.0

    def test_mixed_merge_and_non_merge(self) -> None:
        """混合场景：部分合并，部分不合并。"""
        klines = [
            _k(0, "2025-01-02", 10, 14, 15, 10),  # 大阳线
            _k(1, "2025-01-03", 11, 13, 14, 11),  # 被包含，合并
            _k(2, "2025-01-06", 16, 18, 19, 15),  # 新高，不合并
            _k(3, "2025-01-07", 17, 15, 18, 14),  # 阴线，不包含
        ]
        result = merge_klines(klines)
        assert len(result) == 3
        assert result[0].merged_count == 2  # K0+K1 合并
        assert result[1].merged_count == 1  # K2 独立
        assert result[2].merged_count == 1  # K3 独立

    def test_index_assignment(self) -> None:
        """CLKline.index 应从 0 递增。"""
        klines = [
            _k(0, "2025-01-02", 10, 14, 15, 10),
            _k(1, "2025-01-03", 14, 16, 17, 13),
            _k(2, "2025-01-06", 16, 12, 17, 11),
        ]
        result = merge_klines(klines)
        for i, ck in enumerate(result):
            assert ck.index == i

    def test_klines_reference_preserved(self) -> None:
        """CLKline.klines 应包含合并前的原始 K 线。"""
        klines = [
            _k(0, "2025-01-02", 10, 14, 15, 10),
            _k(1, "2025-01-03", 11, 13, 14, 11),  # 被包含
        ]
        result = merge_klines(klines)
        assert len(result[0].klines) == 2


# ── 分型识别测试 ──────────────────────────────────────────────────────────


class TestFindFractals:
    """find_fractals 测试。"""

    def test_simple_ding_fx(self) -> None:
        """简单的顶分型：中间高，两边低。"""
        cks = [
            _ck(0, "2025-01-02", 10, 12, 12, 10),
            _ck(1, "2025-01-03", 12, 15, 15, 11),
            _ck(2, "2025-01-06", 14, 11, 14, 10),
        ]
        fxs = find_fractals(cks)
        assert len(fxs) == 1
        assert fxs[0].fx_type == FXType.DING
        assert fxs[0].val == 15.0
        assert fxs[0].k == cks[1]

    def test_simple_di_fx(self) -> None:
        """简单的底分型：中间低，两边高。"""
        cks = [
            _ck(0, "2025-01-02", 15, 12, 16, 12),
            _ck(1, "2025-01-03", 11, 9, 12, 9),
            _ck(2, "2025-01-06", 10, 13, 14, 10),
        ]
        fxs = find_fractals(cks)
        assert len(fxs) == 1
        assert fxs[0].fx_type == FXType.DI
        assert fxs[0].val == 9.0

    def test_no_fractal(self) -> None:
        """单调序列不应有分型。"""
        cks = [
            _ck(0, "2025-01-02", 10, 12, 12, 10),
            _ck(1, "2025-01-03", 12, 14, 14, 12),
            _ck(2, "2025-01-06", 14, 16, 16, 14),
        ]
        fxs = find_fractals(cks)
        assert len(fxs) == 0

    def test_alternating_ding_di(self) -> None:
        """交替的顶底分型。"""
        cks = [
            _ck(0, "2025-01-02", 10, 12, 12, 10),  # 上升
            _ck(1, "2025-01-03", 12, 15, 15, 11),  # 顶 (12<15, 14<15)
            _ck(2, "2025-01-06", 14, 11, 14, 10),  # 下降
            _ck(3, "2025-01-07", 10, 8, 11, 8),  # 底 (10>8, 9>8)
            _ck(4, "2025-01-08", 9, 13, 16, 9),  # 大幅上升
            _ck(5, "2025-01-09", 15, 10, 15, 10),  # 下降 → ck[4] 成为顶
        ]
        fxs = find_fractals(cks)
        assert len(fxs) == 3
        assert fxs[0].fx_type == FXType.DING  # ck[1]
        assert fxs[1].fx_type == FXType.DI  # ck[3]
        assert fxs[2].fx_type == FXType.DING  # ck[4]

    def test_insufficient_klines(self) -> None:
        """少于3根K线不应有分型。"""
        assert find_fractals([]) == []
        assert find_fractals([_ck(0, "2025-01-02", 10, 12, 12, 10)]) == []
        assert (
            find_fractals(
                [
                    _ck(0, "2025-01-02", 10, 12, 12, 10),
                    _ck(1, "2025-01-03", 12, 15, 15, 11),
                ]
            )
            == []
        )

    def test_equal_highs_no_ding(self) -> None:
        """相等高点不应形成顶分型。"""
        cks = [
            _ck(0, "2025-01-02", 10, 12, 15, 10),
            _ck(1, "2025-01-03", 12, 14, 15, 11),
            _ck(2, "2025-01-06", 14, 11, 14, 10),
        ]
        fxs = find_fractals(cks)
        assert len(fxs) == 0

    def test_equal_lows_no_di(self) -> None:
        """相等低点不应形成底分型。"""
        cks = [
            _ck(0, "2025-01-02", 15, 12, 16, 9),
            _ck(1, "2025-01-03", 11, 10, 12, 9),
            _ck(2, "2025-01-06", 10, 13, 14, 10),
        ]
        fxs = find_fractals(cks)
        assert len(fxs) == 0


# ── 笔计算测试 ────────────────────────────────────────────────────────────


class TestFindBis:
    """find_bis 测试。"""

    def test_simple_up_down_bi(self) -> None:
        """一组顶底分型应产生两笔（向上 + 向下）。"""
        cks = [
            _ck(0, "2025-01-02", 10, 12, 12, 10),
            _ck(1, "2025-01-03", 12, 15, 15, 11),
            _ck(2, "2025-01-06", 14, 11, 14, 10),
            _ck(3, "2025-01-07", 10, 8, 11, 8),
            _ck(4, "2025-01-08", 9, 13, 16, 9),
            _ck(5, "2025-01-09", 15, 10, 15, 10),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs)
        # ding(1) → di(3) 向下笔, di(3) → ding(4) 向上笔
        assert len(bis) >= 2
        assert bis[0].direction == Direction.DOWN  # 顶→底
        assert bis[1].direction == Direction.UP  # 底→顶

    def test_new_bi_rule_needs_gap(self) -> None:
        """新笔规则：分型之间至少1根独立K线。

        如果两个分型相邻（中间无独立K线），不构成笔。
        """
        # 只有3根K线，产生1个分型，不足以成笔
        cks = [
            _ck(0, "2025-01-02", 10, 12, 12, 10),
            _ck(1, "2025-01-03", 12, 15, 15, 11),
            _ck(2, "2025-01-06", 14, 11, 14, 10),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs)
        assert len(bis) == 0  # 1个分型无法成笔

    def test_ding_di_must_alternate(self) -> None:
        """笔的起止分型必须顶底交替：顶→底 或 底→顶。"""
        cks = [
            _ck(0, "2025-01-02", 10, 8, 11, 8),
            _ck(1, "2025-01-03", 9, 15, 16, 9),
            _ck(2, "2025-01-06", 14, 11, 14, 10),
            _ck(3, "2025-01-07", 10, 7, 11, 7),
            _ck(4, "2025-01-08", 8, 13, 14, 8),
            _ck(5, "2025-01-09", 13, 10, 14, 10),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs)
        for bi in bis:
            if bi.direction == Direction.UP:
                assert bi.start.fx_type == FXType.DI
                assert bi.end.fx_type == FXType.DING
            else:
                assert bi.start.fx_type == FXType.DING
                assert bi.end.fx_type == FXType.DI

    def test_empty_fractals(self) -> None:
        """空分型列表应返回空笔列表。"""
        assert find_bis([]) == []

    def test_bi_high_low(self) -> None:
        """笔的 high/low 应正确反映区间最高最低价。"""
        cks = [
            _ck(0, "2025-01-02", 10, 8, 11, 8),
            _ck(1, "2025-01-03", 9, 15, 16, 9),
            _ck(2, "2025-01-06", 14, 11, 14, 10),
            _ck(3, "2025-01-07", 10, 7, 11, 7),
            _ck(4, "2025-01-08", 8, 13, 14, 8),
            _ck(5, "2025-01-09", 13, 10, 13, 10),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs)
        if len(bis) > 0:
            # 第一笔：顶→底（向下），high=16, low=7
            assert bis[0].high == 16.0
            assert bis[0].low == 7.0

    def test_full_pipeline_merge_to_bi(self) -> None:
        """完整管道测试：原始K线 → 合并 → 分型 → 笔。"""
        klines = [
            _k(0, "2025-01-02", 10, 8, 11, 8),
            _k(1, "2025-01-03", 8, 12, 13, 7),
            _k(2, "2025-01-06", 12, 16, 17, 11),
            _k(3, "2025-01-07", 16, 14, 18, 13),
            _k(4, "2025-01-08", 14, 10, 15, 9),
            _k(5, "2025-01-09", 10, 6, 11, 5),
            _k(6, "2025-01-10", 7, 12, 13, 6),
            _k(7, "2025-01-13", 12, 9, 14, 8),
        ]
        merged = merge_klines(klines)
        fxs = find_fractals(merged)
        bis = find_bis(fxs)
        assert len(bis) >= 1

    def test_fractal_trap_regression(self) -> None:
        """回归测试：密集交替分型不应卡死笔算法。

        场景：持续下跌走势中，分型在相邻 CKline 位置交替出现（mid_gap=1），
        导致每个异类型分型与前一个同类型分型共享 2 根 CKline（gap=0）。

        修复前：贪心算法用更极端的同类型分型替换 start_fx，
        推进 right_kline_index，使后续所有异类型分型 gap 永远为 0，卡死算法。
        修复后：存在 pending 异类型分型时不替换 start_fx，保留较早位置使 gap 自然递增。
        """
        # 下跌锯齿形：分型在连续 CKline 位置交替（ding/di mid_gap=1）
        # 每个 di 比前一个低，每个 ding 也比前一个低 → 持续下跌
        cks = [
            _ck(0, "2025-01-02", 145, 145, 150, 140),
            _ck(1, "2025-01-03", 130, 130, 135, 125),  # di
            _ck(2, "2025-01-06", 140, 140, 145, 135),  # ding
            _ck(3, "2025-01-07", 125, 125, 130, 120),  # di
            _ck(4, "2025-01-08", 133, 133, 138, 128),  # ding
            _ck(5, "2025-01-09", 120, 120, 125, 115),  # di
            _ck(6, "2025-01-10", 127, 127, 132, 122),  # ding
            _ck(7, "2025-01-13", 113, 113, 118, 108),  # di
            _ck(8, "2025-01-14", 121, 121, 126, 116),  # ding
            _ck(9, "2025-01-15", 107, 107, 112, 102),  # di (overlap ends)
            _ck(10, "2025-01-16", 103, 103, 108, 98),
            _ck(11, "2025-01-17", 113, 113, 118, 108),  # ding
            _ck(12, "2025-01-20", 101, 101, 106, 96),
        ]

        fxs = find_fractals(cks)
        assert len(fxs) >= 6, f"应产生至少6个分型，实际 {len(fxs)}"

        bis = find_bis(fxs)

        # 关键断言：密集交替分型不应导致算法卡死
        assert len(bis) >= 2, (
            f"密集交替分型场景应产出至少2笔，实际只有 {len(bis)} 笔。"
            f"分型数: {len(fxs)}，可能触发了分型陷阱 bug。"
        )

        # 验证方向交替
        for i in range(1, len(bis)):
            assert bis[i].direction != bis[i - 1].direction, (
                f"笔 {i - 1} 和笔 {i} 方向相同 ({bis[i].direction.value})，笔的方向应该交替。"
            )


# ── 中枢计算测试 ──────────────────────────────────────────────────────────


class TestFindZss:
    """find_zss 测试。"""

    def test_three_overlapping_bis_form_zs(self) -> None:
        """三笔重叠形成中枢。"""
        cks = [
            _ck(0, "2025-01-02", 10, 8, 11, 8),
            _ck(1, "2025-01-03", 9, 15, 16, 9),
            _ck(2, "2025-01-06", 14, 11, 14, 10),
            _ck(3, "2025-01-07", 10, 12, 13, 9),
            _ck(4, "2025-01-08", 12, 14, 15, 11),
            _ck(5, "2025-01-09", 14, 12, 14, 11),
            _ck(6, "2025-01-10", 11, 9, 12, 9),
            _ck(7, "2025-01-13", 10, 11, 12, 10),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs)
        zss = find_zss(bis)
        assert len(zss) >= 1
        zs = zss[0]
        assert zs.zg > zs.zd
        assert zs.gg >= zs.zg
        assert zs.dd <= zs.zd

    def test_no_overlap_no_zs(self) -> None:
        """笔之间无重叠不应形成中枢。"""
        cks = [
            _ck(0, "2025-01-02", 10, 8, 11, 8),
            _ck(1, "2025-01-03", 9, 15, 16, 9),
            _ck(2, "2025-01-06", 14, 16, 18, 15),
            _ck(3, "2025-01-07", 16, 20, 22, 16),
            _ck(4, "2025-01-08", 20, 25, 26, 20),
            _ck(5, "2025-01-09", 25, 22, 26, 22),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs)
        zss = find_zss(bis)
        assert len(zss) == 0

    def test_empty_bis_no_zs(self) -> None:
        """空笔列表不应有中枢。"""
        assert find_zss([]) == []

    def test_zs_overlap_properties(self) -> None:
        """中枢应有正确的重叠区间属性。"""
        cks = [
            _ck(0, "2025-01-02", 10, 12, 13, 10),
            _ck(1, "2025-01-03", 12, 15, 16, 11),
            _ck(2, "2025-01-06", 14, 11, 14, 10),
            _ck(3, "2025-01-07", 10, 13, 14, 9),
            _ck(4, "2025-01-08", 12, 14, 15, 11),
            _ck(5, "2025-01-09", 14, 12, 14, 11),
            _ck(6, "2025-01-10", 11, 9, 12, 8),
            _ck(7, "2025-01-13", 10, 11, 12, 9),
            _ck(8, "2025-01-14", 11, 6, 12, 5),
            _ck(9, "2025-01-15", 7, 8, 9, 6),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs)
        zss = find_zss(bis)
        if len(zss) > 0:
            zs = zss[0]
            # 中枢基本属性
            assert zs.zg > zs.zd
            assert zs.gg >= zs.zg
            assert zs.dd <= zs.zd
            assert zs.line_count >= 3


# ── Analyser 集成测试 ────────────────────────────────────────────────────


class TestChanlunAnalyser:
    """ChanlunAnalyser 完整管道测试。"""

    def test_analyse_with_dataframe(self) -> None:
        """使用模拟 DataFrame 测试完整管道。"""
        import pandas as pd

        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        dates = pd.date_range("2025-01-02", periods=20, freq="B")
        data = {
            "datetime": dates,
            "open": [10, 8, 12, 16, 14, 10, 7, 12, 14, 12, 10, 6, 7, 12, 9, 10, 14, 12, 8, 9],
            "close": [8, 12, 16, 14, 10, 7, 12, 14, 12, 10, 6, 7, 12, 9, 10, 14, 12, 8, 9, 11],
            "high": [11, 13, 17, 18, 15, 11, 13, 15, 14, 13, 11, 8, 13, 12, 11, 15, 14, 13, 9, 12],
            "low": [7, 7, 11, 13, 9, 5, 6, 11, 11, 9, 5, 5, 6, 8, 8, 9, 11, 7, 7, 9],
            "vol": [1000] * 20,
        }
        df = pd.DataFrame(data)

        analyser = ChanlunAnalyser(code="SZ000001", frequency="DAILY")
        result = analyser.process_klines(df)

        assert result.code == "SZ000001"
        assert result.frequency == "DAILY"
        assert len(result.klines) == 20
        assert len(result.cklines) > 0
        assert len(result.cklines) <= 20
        assert len(result.fractals) >= 0
        assert len(result.bis) >= 0

    def test_empty_dataframe(self) -> None:
        """空 DataFrame 应返回空结果。"""
        import pandas as pd

        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        df = pd.DataFrame(columns=["datetime", "open", "close", "high", "low", "vol"])
        analyser = ChanlunAnalyser(code="SZ000001")
        result = analyser.process_klines(df)
        assert len(result.klines) == 0
        assert len(result.bis) == 0

    def test_result_to_dict(self) -> None:
        """结果应可序列化为字典。"""
        import pandas as pd

        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        dates = pd.date_range("2025-01-02", periods=10, freq="B")
        data = {
            "datetime": dates,
            "open": [10, 8, 12, 16, 14, 10, 7, 12, 14, 12],
            "close": [8, 12, 16, 14, 10, 7, 12, 14, 12, 10],
            "high": [11, 13, 17, 18, 15, 11, 13, 15, 14, 13],
            "low": [7, 7, 11, 13, 9, 5, 6, 11, 11, 9],
            "vol": [1000] * 10,
        }
        df = pd.DataFrame(data)
        analyser = ChanlunAnalyser(code="SZ000001")
        result = analyser.process_klines(df)
        d = result.to_dict()

        assert "code" in d
        assert "bi_count" in d
        assert "zs_count" in d
        assert "bis" in d
        assert "zss" in d

        # 可视化字段：中枢/买卖点/背驰应携带对应 K 线日期（若该样本产出了它们）
        import re

        date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")

        for zs in d["zss"]:
            assert "start_date" in zs
            assert "end_date" in zs
            if zs["start_date"] is not None:
                assert date_re.match(zs["start_date"])
            if zs["end_date"] is not None:
                assert date_re.match(zs["end_date"])

        for mmd in d["mmds"]:
            assert "date" in mmd
            if mmd["date"] is not None:
                assert date_re.match(mmd["date"])

        for bc in d["bcs"]:
            assert "curr_date" in bc
            assert "prev_date" in bc
            if bc["curr_date"] is not None:
                assert date_re.match(bc["curr_date"])
            if bc["prev_date"] is not None:
                assert date_re.match(bc["prev_date"])

    def test_result_visual_endpoint_uses_raw_extreme_date(self) -> None:
        """合并 K 线的端点日期必须吸附到极值实际所在的原始 K 线。"""
        from easy_tdx.chanlun.analyser import ChanlunResult
        from easy_tdx.chanlun.types import BI, FX

        bottom_sources = [
            _k(0, "2025-01-02", 10, 9, 11, 8),
            _k(1, "2025-01-03", 9, 10, 10.5, 8.5),
        ]
        bottom = CLKline(
            k_index=1,
            date=bottom_sources[-1].date,
            open=9,
            close=10,
            high=11,
            low=8,
            amount=0,
            klines=bottom_sources,
        )
        top_sources = [
            _k(2, "2025-01-06", 14, 15, 16, 13),
            _k(3, "2025-01-07", 15, 14, 15.5, 13.5),
        ]
        top = CLKline(
            k_index=3,
            date=top_sources[-1].date,
            open=15,
            close=14,
            high=16,
            low=13.5,
            amount=0,
            klines=top_sources,
        )
        start = FX(FXType.DI, bottom, [bottom, bottom, bottom], 8)
        end = FX(FXType.DING, top, [top, top, top], 16)
        bi = BI(start=start, end=end, direction=Direction.UP, high=16, low=8)

        payload = ChanlunResult(frequency="DAILY", bis=[bi]).to_dict()["bis"][0]

        assert payload["start_date"] == "2025-01-02"
        assert payload["end_date"] == "2025-01-06"
        assert payload["start_value"] == 8
        assert payload["end_value"] == 16

    def test_result_to_dict_with_visual_dates(self) -> None:
        """可视化字段：足够数据下 zss/mmds/bcs 应携带合法 K 线日期。

        用一段振荡+趋势的数据，确保能确定性产出中枢/买卖点/背驰，
        从而真正覆盖 to_dict() 的日期输出分支。
        """
        import math
        import re

        import pandas as pd

        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        dates = pd.date_range("2025-01-02", periods=40, freq="B")
        highs = [15 + 5 * math.sin(i / 2) + i * 0.2 for i in range(40)]
        lows = [highs[i] - 4 for i in range(40)]
        df = pd.DataFrame(
            {
                "datetime": dates,
                "open": [h - 2 for h in highs],
                "close": [h - 1 for h in highs],
                "high": highs,
                "low": lows,
                "vol": [1000] * 40,
            }
        )
        analyser = ChanlunAnalyser(code="SZ000001")
        d = analyser.process_klines(df).to_dict()

        date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")

        # 中枢必须有起止日期
        assert len(d["zss"]) > 0
        for zs in d["zss"]:
            assert zs["start_date"] is not None
            assert zs["end_date"] is not None
            assert date_re.match(zs["start_date"])
            assert date_re.match(zs["end_date"])

        # 买卖点必须有触发日期
        assert len(d["mmds"]) > 0
        for mmd in d["mmds"]:
            assert mmd["date"] is not None
            assert date_re.match(mmd["date"])

        # 背驰必须有当前笔 + 对照笔日期
        assert len(d["bcs"]) > 0
        for bc in d["bcs"]:
            assert bc["curr_date"] is not None
            assert bc["prev_date"] is not None
            assert date_re.match(bc["curr_date"])
            assert date_re.match(bc["prev_date"])

    def test_result_to_dict_minute_frequency_includes_time(self) -> None:
        """分钟级别 frequency 下，日期字段应输出完整时分 YYYY-MM-DD HH:MM。

        对应网友反馈：分钟/低级别也需要时分用于分时可视化。
        覆盖 CLI 原始值（5MIN/30MIN）与 Web 映射值（5min/30min）两种大小写。
        """
        import math
        import re

        import pandas as pd

        from easy_tdx.chanlun.analyser import ChanlunAnalyser

        dates = pd.date_range("2025-01-02 09:30", periods=60, freq="5min")
        highs = [15 + 5 * math.sin(i / 2) + i * 0.01 for i in range(60)]
        lows = [highs[i] - 1.5 for i in range(60)]
        df = pd.DataFrame(
            {
                "datetime": dates,
                "open": [h - 0.5 for h in highs],
                "close": [h - 0.2 for h in highs],
                "high": highs,
                "low": lows,
                "vol": [1000] * 60,
            }
        )
        datetime_re = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

        # CLI 原始值（大写 5MIN）与 Web 映射值（小写 5min）应行为一致
        for freq in ("5MIN", "5min"):
            d = ChanlunAnalyser(code="SZ000001", frequency=freq).process_klines(df).to_dict()

            # bis 日期应带时分
            assert len(d["bis"]) > 0
            for bi in d["bis"]:
                assert datetime_re.match(bi["start_date"])
                assert datetime_re.match(bi["end_date"])

            # zss/mmds/bcs 若产出，同样应带时分（有就检查）
            for zs in d["zss"]:
                if zs["start_date"] is not None:
                    assert datetime_re.match(zs["start_date"])
                if zs["end_date"] is not None:
                    assert datetime_re.match(zs["end_date"])
            for mmd in d["mmds"]:
                if mmd["date"] is not None:
                    assert datetime_re.match(mmd["date"])
            for bc in d["bcs"]:
                if bc["curr_date"] is not None:
                    assert datetime_re.match(bc["curr_date"])
                if bc["prev_date"] is not None:
                    assert datetime_re.match(bc["prev_date"])

    def test_print_table_with_dates(self) -> None:
        """CLI table 模式应正确消费 zss/mmds/bcs 的日期字段。

        用能确定性产出中枢/买卖点/背驰的数据，调 _print_table 确保不抛异常、
        且输出中包含新增的日期标记（→ 表示日期区间）。
        """
        import contextlib
        import io
        import math

        import pandas as pd

        from easy_tdx.chanlun.analyser import ChanlunAnalyser
        from easy_tdx.cli.cmd_chanlun import _print_table

        dates = pd.date_range("2025-01-02", periods=40, freq="B")
        highs = [15 + 5 * math.sin(i / 2) + i * 0.2 for i in range(40)]
        lows = [highs[i] - 4 for i in range(40)]
        df = pd.DataFrame(
            {
                "datetime": dates,
                "open": [h - 2 for h in highs],
                "close": [h - 1 for h in highs],
                "high": highs,
                "low": lows,
                "vol": [1000] * 40,
            }
        )
        d = ChanlunAnalyser(code="SZ000001", frequency="DAILY").process_klines(df).to_dict()

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _print_table(d)
        out = buf.getvalue()

        # 中枢/买卖点/背驰都应出现，且中枢行应含日期区间箭头
        assert "── 中枢 ──" in out
        assert "── 买卖点 ──" in out
        assert "── 背驰 ──" in out
        # 中枢行格式：[idx] <start> → <end> zg=...
        assert "→" in out
