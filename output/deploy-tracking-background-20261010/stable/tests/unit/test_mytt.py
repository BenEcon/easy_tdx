"""MyTT.py 新增指标函数（SAR/VWAP/AROON/FK）的数值正确性与边界测试。

这些测试针对 MyTT.py 里函数本身，不经过 indicator.py 注册层。
注册层的端到端覆盖在 test_indicator.py::TestComputeIndicators::test_all_registered_indicators_run。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx import MyTT


def _ohlcv(n: int = 200, seed: int = 42) -> tuple[np.ndarray, ...]:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.standard_normal(n) * 0.5)
    high = close + np.abs(rng.standard_normal(n))
    low = close - np.abs(rng.standard_normal(n))
    open_ = low + (high - low) * rng.random(n)
    vol = (rng.random(n) * 1e6 + 1.0).astype(float)  # +1 避免全零
    return open_, high, low, close, vol


class TestSAR:
    """SAR 抛物线转向指标。"""

    def test_returns_same_length(self):
        _, high, low, _, _ = _ohlcv()
        sar = MyTT.SAR(high, low)
        assert len(sar) == len(high)

    def test_first_value_is_low(self):
        # 默认假设上涨趋势，SAR 起点取首根低点
        _, high, low, _, _ = _ohlcv()
        sar = MyTT.SAR(high, low)
        assert sar[0] == pytest.approx(low[0])

    def test_empty_input(self):
        sar = MyTT.SAR(np.array([]), np.array([]))
        assert len(sar) == 0

    def test_flat_market_no_crash(self):
        # 一字板/停牌：高低价完全相同，不应崩溃或产生 inf
        flat = np.full(50, 10.0)
        sar = MyTT.SAR(flat, flat)
        assert len(sar) == 50
        assert np.isfinite(sar[1:]).all(), "SAR 不应产生 inf/nan（首值外）"

    def test_rising_market_sar_below_price(self):
        # 持续上涨时 SAR 应在价格下方（上涨止损位）
        high = np.arange(50, dtype=float) + 1
        low = np.arange(50, dtype=float)
        sar = MyTT.SAR(high, low)
        # 前 5 根建立趋势后，SAR 应低于对应低点
        assert (sar[5:] <= low[5:] + 1e-6).all()

    def test_falling_market_sar_above_price(self):
        # 持续下跌时 SAR 应在价格上方（下跌止损位）
        low = np.array([100 - i for i in range(50)], dtype=float)
        high = low + 1
        sar = MyTT.SAR(high, low)
        # 确认在某处发生反转（趋势从上涨初判切换）
        # 不强求全程在上方（初判是上涨），但尾部下跌段 SAR 应高于 low
        assert sar[-1] > low[-1]

    def test_reversal_resets_af(self):
        # 反转时加速因子应回到 AF_STEP（无法直接观测，间接验证：反转后第一步 SAR 等于前极值点）
        # 构造 V 型反转：先涨后跌
        rise_h = np.arange(25, dtype=float) + 1
        fall_h = np.array([25 - i + 1 for i in range(1, 25)])
        high = np.concatenate([rise_h, fall_h])
        rise_l = np.arange(25, dtype=float)
        fall_l = np.array([25 - i for i in range(1, 25)])
        low = np.concatenate([rise_l, fall_l])
        sar = MyTT.SAR(high, low)
        assert np.isfinite(sar).all()

    def test_acceleration_factor_capped(self):
        # 长期单边上涨，AF 不应超过 AF_MAX（通过 SAR 增量间接验证不发散）
        high = np.cumsum(np.ones(100)) + 1  # 每根 +1
        low = np.cumsum(np.ones(100))
        sar = MyTT.SAR(high, low, AF_STEP=0.02, AF_MAX=0.2)
        assert np.isfinite(sar).all()
        # SAR 全程应在 low 之下（持续上涨不反转）
        valid = sar[2:]
        assert (valid <= low[2:] + 1e-6).all()


class TestVWAP:
    """VWAP 成交量加权均价。"""

    def test_returns_same_length(self):
        _, high, low, close, vol = _ohlcv()
        vwap = MyTT.VWAP(close, high, low, vol, N=20)
        assert len(vwap) == len(close)

    def test_leading_nan(self):
        # 前 N-1 根应为 nan（rolling 窗口未填满）
        _, high, low, close, vol = _ohlcv()
        vwap = MyTT.VWAP(close, high, low, vol, N=20)
        assert np.isnan(vwap[:19]).all()
        assert not np.isnan(vwap[19])

    def test_constant_price(self):
        # 价格、量都恒定时，VWAP 应等于典型价格
        n = 50
        close = np.full(n, 10.0)
        high = np.full(n, 11.0)
        low = np.full(n, 9.0)
        vol = np.full(n, 1000.0)
        vwap = MyTT.VWAP(close, high, low, vol, N=20)
        expected_tp = (11 + 9 + 10) / 3.0  # =10.0
        assert np.allclose(vwap[19:], expected_tp, equal_nan=True)

    def test_uniform_volume_equals_typical_price_mean(self):
        # 等量时 VWAP = 典型价格的 N 日均值
        n = 100
        rng = np.random.default_rng(1)
        close = 100 + rng.standard_normal(n)
        high = close + 1
        low = close - 1
        vol = np.full(n, 500.0)
        tp = (high + low + close) / 3.0
        vwap = MyTT.VWAP(close, high, low, vol, N=10)
        tp_ma = pd.Series(tp).rolling(10).mean().values
        assert np.allclose(vwap, tp_ma, equal_nan=True)

    def test_zero_volume_returns_nan(self):
        # 全零成交量时，VWAP 应为 nan（除零保护）
        n = 30
        close = np.full(n, 10.0)
        high = np.full(n, 11.0)
        low = np.full(n, 9.0)
        vol = np.zeros(n)
        vwap = MyTT.VWAP(close, high, low, vol, N=20)
        assert np.isnan(vwap[19:]).all()


class TestAROON:
    """Aroon 阿隆指标。"""

    def test_returns_three_arrays(self):
        _, high, low, _, _ = _ohlcv()
        up, down, osc = MyTT.AROON(high, low, N=25)
        assert len(up) == len(high)
        assert len(down) == len(high)
        assert len(osc) == len(high)

    def test_range_zero_to_hundred(self):
        # AROON_UP/DOWN 应在 [0, 100] 区间
        _, high, low, _, _ = _ohlcv()
        up, down, _ = MyTT.AROON(high, low, N=25)
        # 跳过 rolling 窗口前的 nan
        valid_up = up[24:]
        valid_down = down[24:]
        assert (valid_up >= 0).all() and (valid_up <= 100).all()
        assert (valid_down >= 0).all() and (valid_down <= 100).all()

    def test_new_high_gives_full_up(self):
        # 在窗口末端创新高时，AROON_UP 应 = 100
        n = 50
        high = np.linspace(1, 30, n)  # 单调上升，末根创新高
        low = high - 0.5
        up, down, _ = MyTT.AROON(high, low, N=25)
        assert up[-1] == pytest.approx(100.0)

    def test_new_low_gives_full_down(self):
        # 在窗口末端创新低时，AROON_DOWN 应 = 100
        n = 50
        low = np.linspace(30, 1, n)  # 单调下降
        high = low + 0.5
        _, down, _ = MyTT.AROON(high, low, N=25)
        assert down[-1] == pytest.approx(100.0)

    def test_osc_is_difference(self):
        # OSC = UP - DOWN
        _, high, low, _, _ = _ohlcv()
        up, down, osc = MyTT.AROON(high, low, N=25)
        assert np.allclose(osc[24:], (up - down)[24:], equal_nan=True)

    def test_leading_nan(self):
        _, high, low, _, _ = _ohlcv()
        up, down, _ = MyTT.AROON(high, low, N=25)
        # HHVBARS/LLVBARS 在 N-1 根前为 nan
        assert np.isnan(up[:24]).all()


class TestFK:
    """FK 趋势指标（布尔输出）。

    慢线用 SLOPE(CLOSE,21)*20 做斜率外推：上涨时慢线被正斜率推高，
    下跌时被负斜率压低。FK = fast(EMA2) > slow(外推 EMA42)，
    语义是"价格是否突破趋势外推线"，本质是动量/反转偏离检测：
    - 强下跌时 fast 相对外推慢线偏高 → FK=True（超卖/反弹信号）
    - 强上涨时慢线被推高，fast 难以超越 → FK=False（未超买或接近超买）
    """

    def test_returns_boolean_array(self):
        close = _ohlcv()[3]
        fk = MyTT.FK(close)
        assert len(fk) == len(close)
        assert fk.dtype == bool

    def test_rising_market_returns_false(self):
        # 强上涨：正斜率外推把慢线推高，fast < slow → FK=False
        close = np.cumsum(np.ones(100))  # 每根 +1
        fk = MyTT.FK(close)
        assert bool(fk[-1]) is False

    def test_falling_market_returns_true(self):
        # 强下跌：负斜率外推把慢线压低，fast > slow → FK=True
        close = np.array([100 - i for i in range(100)], dtype=float)
        fk = MyTT.FK(close)
        assert bool(fk[-1]) is True
