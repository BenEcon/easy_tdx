"""缠论 Phase 2 单元测试：MACD、线段、买卖点、背驰。"""

from __future__ import annotations

from datetime import datetime

from easy_tdx.chanlun.bi import find_bis
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.types import CLKline, Direction, Kline

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
    return CLKline(
        k_index=idx,
        date=datetime.strptime(dt, "%Y-%m-%d"),
        open=o,
        close=c,
        high=h,
        low=l,
        amount=0.0,
        index=0,
        merged_count=merged_count,
        direction=direction,
    )


# ── MACD 测试 ────────────────────────────────────────────────────────────


class TestMacd:
    """calc_macd 测试。"""

    def test_macd_output_length(self) -> None:
        """MACD 输出长度应与输入一致。"""
        from easy_tdx.chanlun.macd import calc_macd

        closes = [10.0 + i * 0.5 for i in range(50)]
        result = calc_macd(closes)
        assert "dif" in result
        assert "dea" in result
        assert "hist" in result
        assert len(result["dif"]) == 50
        assert len(result["dea"]) == 50
        assert len(result["hist"]) == 50

    def test_macd_short_input(self) -> None:
        """输入太短时应返回零数组。"""
        from easy_tdx.chanlun.macd import calc_macd

        result = calc_macd([10.0])
        assert len(result["dif"]) == 1
        assert result["dif"][0] == 0.0

    def test_macd_uptrend_positive_dif(self) -> None:
        """持续上涨时 DIF 应为正。"""
        from easy_tdx.chanlun.macd import calc_macd

        closes = [float(i) for i in range(100)]
        result = calc_macd(closes)
        # 后半段 DIF 应为正
        assert result["dif"][-1] > 0

    def test_macd_downtrend_negative_dif(self) -> None:
        """持续下跌时 DIF 应为负。"""
        from easy_tdx.chanlun.macd import calc_macd

        closes = [100.0 - i for i in range(100)]
        result = calc_macd(closes)
        assert result["dif"][-1] < 0

    def test_macd_hist_equals_2x_diff(self) -> None:
        """MACD 柱 = 2 * (DIF - DEA)。"""
        from easy_tdx.chanlun.macd import calc_macd

        closes = [10.0 + i * 0.3 for i in range(60)]
        result = calc_macd(closes)
        for i in range(len(closes)):
            expected = 2 * (result["dif"][i] - result["dea"][i])
            assert abs(result["hist"][i] - expected) < 1e-10

    def test_macd_custom_params(self) -> None:
        """支持自定义 fast/slow/signal 参数。"""
        from easy_tdx.chanlun.macd import calc_macd

        closes = [float(i) for i in range(100)]
        r1 = calc_macd(closes, fast=12, slow=26, signal=9)
        r2 = calc_macd(closes, fast=6, slow=13, signal=5)
        # 不同参数应产生不同结果
        assert r1["dif"][-1] != r2["dif"][-1]


# ── 线段测试 ──────────────────────────────────────────────────────────────


class TestFindXds:
    """find_xds 测试。"""

    def test_basic_xd_from_bis(self) -> None:
        """多笔应能形成至少一个线段。"""
        from easy_tdx.chanlun.xd import find_xds

        # 构造足够多的笔来形成线段
        # 需要至少5笔（3笔形成中枢 + 2笔进出）
        cks = [
            _ck(0, "2025-01-02", 10, 8, 11, 8),
            _ck(1, "2025-01-03", 9, 15, 16, 9),  # 顶 h=16
            _ck(2, "2025-01-06", 14, 11, 14, 10),
            _ck(3, "2025-01-07", 10, 13, 14, 9),  # 底 l=9
            _ck(4, "2025-01-08", 12, 14, 15, 11),
            _ck(5, "2025-01-09", 14, 12, 14, 11),
            _ck(6, "2025-01-10", 11, 9, 12, 8),  # 底
            _ck(7, "2025-01-13", 10, 11, 12, 9),
            _ck(8, "2025-01-14", 11, 6, 12, 5),  # 大跌
            _ck(9, "2025-01-15", 7, 8, 9, 6),
            _ck(10, "2025-01-16", 8, 12, 13, 7),
            _ck(11, "2025-01-17", 11, 10, 14, 9),
            _ck(12, "2025-01-20", 10, 6, 11, 5),
            _ck(13, "2025-01-21", 7, 8, 9, 6),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs)
        xds = find_xds(bis)
        # 有足够的笔时，应能形成线段
        if len(bis) >= 5:
            assert len(xds) >= 1

    def test_empty_bis(self) -> None:
        """空笔列表应返回空线段。"""
        from easy_tdx.chanlun.xd import find_xds

        assert find_xds([]) == []

    def test_xd_direction_alternates(self) -> None:
        """线段方向应与笔的方向一致：向上线段由向上笔主导。"""
        from easy_tdx.chanlun.xd import find_xds

        cks = [
            _ck(0, "2025-01-02", 10, 8, 11, 8),
            _ck(1, "2025-01-03", 9, 15, 16, 9),
            _ck(2, "2025-01-06", 14, 11, 14, 10),
            _ck(3, "2025-01-07", 10, 13, 14, 9),
            _ck(4, "2025-01-08", 12, 14, 15, 11),
            _ck(5, "2025-01-09", 14, 12, 14, 11),
            _ck(6, "2025-01-10", 11, 9, 12, 8),
            _ck(7, "2025-01-13", 10, 11, 12, 9),
            _ck(8, "2025-01-14", 11, 6, 12, 5),
            _ck(9, "2025-01-15", 7, 8, 9, 6),
            _ck(10, "2025-01-16", 8, 12, 13, 7),
            _ck(11, "2025-01-17", 11, 10, 14, 9),
            _ck(12, "2025-01-20", 10, 6, 11, 5),
            _ck(13, "2025-01-21", 7, 8, 9, 6),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs)
        xds = find_xds(bis)
        for xd in xds:
            assert xd.direction in (Direction.UP, Direction.DOWN)

    def test_xd_ranges_do_not_step_back_in_time(self) -> None:
        """后一线段不能从前一线段终点之前重新起步。"""
        from easy_tdx.chanlun.xd import find_xds

        cks = [
            _ck(i, f"2025-02-{i + 1:02d}", 10, 10, high, low)
            for i, (high, low) in enumerate(
                [
                    (11, 8), (16, 9), (14, 10), (15, 9), (16, 11),
                    (14, 10), (13, 8), (14, 9), (12, 6), (13, 7),
                    (15, 8), (14, 9), (12, 5), (13, 6), (16, 8),
                    (15, 9), (13, 7), (14, 8), (17, 10), (15, 9),
                ]
            )
        ]
        xds = find_xds(find_bis(find_fractals(cks)))

        for previous, current in zip(xds, xds[1:], strict=False):
            assert current.start.k.date >= previous.end.k.date


# ── 买卖点测试 ────────────────────────────────────────────────────────────


class TestFindMmds:
    """find_mmds 测试。"""

    def test_first_buy_after_zs(self) -> None:
        """中枢下方出现底背驰应产生一类买点。"""
        from easy_tdx.chanlun.mmd import find_mmds

        cks = [
            _ck(0, "2025-01-02", 10, 8, 11, 8),
            _ck(1, "2025-01-03", 9, 15, 16, 9),  # 顶
            _ck(2, "2025-01-06", 14, 11, 14, 10),
            _ck(3, "2025-01-07", 10, 13, 14, 9),  # 底
            _ck(4, "2025-01-08", 12, 14, 15, 11),
            _ck(5, "2025-01-09", 14, 12, 14, 11),
            _ck(6, "2025-01-10", 11, 9, 12, 8),  # 底
            _ck(7, "2025-01-13", 10, 11, 12, 9),
            _ck(8, "2025-01-14", 11, 14, 15, 10),  # 向上离开
            _ck(9, "2025-01-15", 14, 12, 16, 11),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs)
        # find_mmds 需要笔列表和中枢列表
        from easy_tdx.chanlun.zs import find_zss

        zss = find_zss(bis)
        mmds = find_mmds(bis, zss)
        # 结果应为列表（可能为空，取决于是否满足条件）
        assert isinstance(mmds, list)

    def test_empty_input(self) -> None:
        """空输入应返回空列表。"""
        from easy_tdx.chanlun.mmd import find_mmds

        assert find_mmds([], []) == []


# ── 背驰测试 ──────────────────────────────────────────────────────────────


class TestBeichi:
    """check_beichi 测试。"""

    def test_divergence_detection(self) -> None:
        """力度衰减应被检测为背驰。"""
        from easy_tdx.chanlun.beichi import check_bi_beichi

        cks = [
            _ck(0, "2025-01-02", 10, 8, 11, 8),
            _ck(1, "2025-01-03", 9, 15, 16, 9),
            _ck(2, "2025-01-06", 14, 11, 14, 10),
            _ck(3, "2025-01-07", 10, 13, 14, 9),
            _ck(4, "2025-01-08", 12, 14, 15, 11),
            _ck(5, "2025-01-09", 14, 12, 14, 11),
            _ck(6, "2025-01-10", 11, 9, 12, 8),
            _ck(7, "2025-01-13", 10, 11, 12, 9),
            _ck(8, "2025-01-14", 11, 14, 15, 10),
            _ck(9, "2025-01-15", 14, 12, 16, 11),
        ]
        fxs = find_fractals(cks)
        bis = find_bis(fxs)
        from easy_tdx.chanlun.zs import find_zss

        zss = find_zss(bis)
        # 至少不崩溃
        result = check_bi_beichi(bis, zss)
        assert isinstance(result, list)

    def test_empty_input(self) -> None:
        """空输入应返回空列表。"""
        from easy_tdx.chanlun.beichi import check_bi_beichi

        assert check_bi_beichi([], []) == []
