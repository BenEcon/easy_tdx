"""滑点模型单元测试。"""

from __future__ import annotations

import pytest

from easy_tdx.backtest.slippage import (
    FixedSlippage,
    PercentSlippage,
    SlippageModel,
    SquareRootSlippage,
    VolumeSlippage,
)


class TestSlippageBase:
    """基类验证。"""

    def test_cannot_instantiate_abc(self) -> None:
        """不能直接实例化 ABC。"""
        with pytest.raises(TypeError):
            SlippageModel()  # type: ignore[abstract]

    def test_subclass_must_implement_compute(self) -> None:
        """子类必须实现 compute。"""

        class BadModel(SlippageModel):
            pass

        with pytest.raises(TypeError):
            BadModel()  # type: ignore[abstract]


class TestFixedSlippage:
    """固定每股滑点。"""

    def test_zero_per_share(self) -> None:
        """per_share=0 时无滑点。"""
        model = FixedSlippage(per_share=0.0)
        cost = model.compute(price=10.0, size=100, volume=10000, volatility=0.3, direction="BUY")
        assert cost == 0.0

    def test_basic(self) -> None:
        """基本计算：100 股 × 0.01 元/股 = 1.0。"""
        model = FixedSlippage(per_share=0.01)
        cost = model.compute(price=10.0, size=100, volume=10000, volatility=0.3, direction="BUY")
        assert cost == pytest.approx(1.0)

    def test_large_size(self) -> None:
        """大单。"""
        model = FixedSlippage(per_share=0.05)
        cost = model.compute(
            price=50.0, size=10000, volume=500000, volatility=0.2, direction="SELL"
        )
        assert cost == pytest.approx(500.0)

    def test_direction_irrelevant(self) -> None:
        """方向不影响固定滑点。"""
        model = FixedSlippage(per_share=0.01)
        buy_cost = model.compute(
            price=10.0, size=100, volume=10000, volatility=0.3, direction="BUY"
        )
        sell_cost = model.compute(
            price=10.0, size=100, volume=10000, volatility=0.3, direction="SELL"
        )
        assert buy_cost == sell_cost


class TestPercentSlippage:
    """按成交金额百分比滑点。"""

    def test_zero_rate(self) -> None:
        """rate=0 时无滑点。"""
        model = PercentSlippage(rate=0.0)
        cost = model.compute(price=10.0, size=100, volume=10000, volatility=0.3, direction="BUY")
        assert cost == 0.0

    def test_basic(self) -> None:
        """10元 × 100股 × 0.001 = 1.0。"""
        model = PercentSlippage(rate=0.001)
        cost = model.compute(price=10.0, size=100, volume=10000, volatility=0.3, direction="BUY")
        assert cost == pytest.approx(1.0)

    def test_high_price(self) -> None:
        """高价股。"""
        model = PercentSlippage(rate=0.002)
        cost = model.compute(price=100.0, size=500, volume=20000, volatility=0.25, direction="BUY")
        # 100 × 500 × 0.002 = 100.0
        assert cost == pytest.approx(100.0)


class TestSquareRootSlippage:
    """方根市场冲击模型。"""

    def test_zero_size(self) -> None:
        """size=0 时无冲击。"""
        model = SquareRootSlippage(impact_coeff=0.1)
        cost = model.compute(price=10.0, size=0, volume=10000, volatility=0.3, direction="BUY")
        assert cost == 0.0

    def test_small_participation_rate(self) -> None:
        """低参与率（小单），冲击成本低。"""
        model = SquareRootSlippage(impact_coeff=0.1)
        # size=100, volume=1000000, participation_rate=0.0001
        cost = model.compute(
            price=10.0, size=100, volume=1_000_000, volatility=0.3, direction="BUY"
        )
        # σ=0.3, √(0.0001)=0.01, impact = 0.3 × 0.01 × 10 × 100 × 0.1 = 0.3
        assert cost == pytest.approx(0.3)

    def test_high_participation_rate(self) -> None:
        """高参与率（大单），冲击成本高。"""
        model = SquareRootSlippage(impact_coeff=0.1)
        cost = model.compute(
            price=10.0, size=100_000, volume=200_000, volatility=0.3, direction="BUY"
        )
        small_cost = model.compute(
            price=10.0, size=100, volume=1_000_000, volatility=0.3, direction="BUY"
        )
        assert cost > small_cost * 10

    def test_zero_volume_fallback(self) -> None:
        """volume=0 时退化为 PercentSlippage(rate=0.001)。"""
        model = SquareRootSlippage(impact_coeff=0.1)
        cost = model.compute(price=10.0, size=100, volume=0, volatility=0.3, direction="BUY")
        assert cost == pytest.approx(1.0)

    def test_zero_volatility_fallback(self) -> None:
        """volatility=0 时退化为 PercentSlippage(rate=0.001)。"""
        model = SquareRootSlippage(impact_coeff=0.1)
        cost = model.compute(price=10.0, size=100, volume=10000, volatility=0.0, direction="BUY")
        assert cost == pytest.approx(1.0)


class TestVolumeSlippage:
    """成交量比例滑点。"""

    def test_zero_size(self) -> None:
        model = VolumeSlippage(base_bps=10.0)
        cost = model.compute(price=10.0, size=0, volume=10000, volatility=0.3, direction="BUY")
        assert cost == 0.0

    def test_basic(self) -> None:
        model = VolumeSlippage(base_bps=10.0)
        cost = model.compute(price=10.0, size=100, volume=10000, volatility=0.3, direction="BUY")
        assert cost == pytest.approx(0.01)

    def test_high_participation(self) -> None:
        model = VolumeSlippage(base_bps=10.0)
        cost_high = model.compute(
            price=10.0, size=5000, volume=10000, volatility=0.3, direction="BUY"
        )
        cost_low = model.compute(
            price=10.0, size=100, volume=10000, volatility=0.3, direction="BUY"
        )
        assert cost_high > cost_low

    def test_zero_volume_fallback(self) -> None:
        model = VolumeSlippage(base_bps=10.0)
        cost = model.compute(price=10.0, size=100, volume=0, volatility=0.3, direction="BUY")
        assert cost == pytest.approx(1.0)
