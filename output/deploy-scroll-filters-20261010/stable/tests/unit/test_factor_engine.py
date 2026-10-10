# tests/unit/test_factor_engine.py
"""Test FactorEngine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor.base import Factor
from easy_tdx.factor.engine import FactorEngine


def _make_df(n: int = 60, seed: int = 42) -> pd.DataFrame:
    """生成合成 OHLCV 数据。"""
    rng = np.random.default_rng(seed)
    close = 10.0 + np.cumsum(rng.normal(0, 0.5, n))
    close = np.maximum(close, 1.0)
    high = close + rng.uniform(0, 0.5, n)
    low = close - rng.uniform(0, 0.5, n)
    low = np.maximum(low, 0.1)
    open_ = low + rng.uniform(0, high - low, n)
    vol = rng.integers(100_000, 10_000_000, n).astype(float)
    amount = close * vol

    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "vol": vol,
            "amount": amount,
        }
    )


class _SimpleMomentum(Factor):
    name = "simple_momentum"
    category = "momentum"
    description = "5 日动量"
    inputs = ("close",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].pct_change(5)


class _SimpleVolatility(Factor):
    name = "simple_volatility"
    category = "volatility"
    description = "5 日波动率"
    inputs = ("close",)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        ret = df["close"].pct_change()
        return ret.rolling(5).std()


class TestComputeSingle:
    def test_single_factor(self):
        engine = FactorEngine()
        df = _make_df()
        result = engine.compute_single(df, [_SimpleMomentum()])
        assert "simple_momentum" in result.columns
        assert len(result) == len(df)

    def test_multiple_factors(self):
        engine = FactorEngine()
        df = _make_df()
        result = engine.compute_single(df, [_SimpleMomentum(), _SimpleVolatility()])
        assert "simple_momentum" in result.columns
        assert "simple_volatility" in result.columns
        assert len(result) == len(df)

    def test_preserves_original_columns(self):
        engine = FactorEngine()
        df = _make_df()
        result = engine.compute_single(df, [_SimpleMomentum()])
        assert "close" in result.columns
        assert "datetime" in result.columns

    def test_unknown_factor_name_raises(self):
        engine = FactorEngine()
        df = _make_df()
        with pytest.raises(ValueError, match="未知因子"):
            engine.compute_single(df, ["nonexistent_factor_xyz"])

    def test_empty_factors_list(self):
        engine = FactorEngine()
        df = _make_df()
        result = engine.compute_single(df, [])
        assert len(result) == len(df)


class TestComputeCrossSection:
    def test_cross_section_basic(self):
        engine = FactorEngine()
        data = {
            "000001": _make_df(60, seed=1),
            "000002": _make_df(60, seed=2),
            "600036": _make_df(60, seed=3),
        }
        result = engine.compute_cross_section(data, [_SimpleMomentum()])
        assert isinstance(result, pd.DataFrame)
        assert "date" in result.columns
        assert "code" in result.columns
        assert "simple_momentum" in result.columns
        assert len(result) == 180  # 60 days × 3 stocks

    def test_cross_section_latest_date(self):
        engine = FactorEngine()
        data = {
            "000001": _make_df(60, seed=1),
            "000002": _make_df(60, seed=2),
        }
        result = engine.compute_cross_section(data, [_SimpleMomentum()], date=None)
        assert len(result) == 2

    def test_cross_section_specific_date(self):
        engine = FactorEngine()
        df = _make_df(60, seed=1)
        data = {"000001": df}
        target_date = int(df["datetime"].iloc[-5].strftime("%Y%m%d"))
        result = engine.compute_cross_section(data, [_SimpleMomentum()], date=target_date)
        assert len(result) == 1
        assert result.iloc[0]["date"] == target_date

    def test_cross_section_empty_data(self):
        engine = FactorEngine()
        result = engine.compute_cross_section({}, [_SimpleMomentum()])
        assert len(result) == 0


class TestComputeForwardReturns:
    def test_forward_returns_basic(self):
        engine = FactorEngine()
        data = {
            "000001": _make_df(60, seed=1),
            "000002": _make_df(60, seed=2),
        }
        result = engine.compute_forward_returns(data, period=5)
        assert "date" in result.columns
        assert "code" in result.columns
        assert "forward_5d" in result.columns
        code_000001 = result[result["code"] == "000001"]
        assert np.isnan(code_000001["forward_5d"].iloc[-1])

    def test_forward_returns_period(self):
        engine = FactorEngine()
        data = {"000001": _make_df(60, seed=1)}
        result = engine.compute_forward_returns(data, period=10)
        assert "forward_10d" in result.columns

    def test_forward_returns_empty(self):
        engine = FactorEngine()
        result = engine.compute_forward_returns({}, period=5)
        assert len(result) == 0


class TestFactorEngineWithBuiltins:
    """FactorEngine 与内置因子的集成测试。"""

    def test_compute_single_with_builtin(self):
        engine = FactorEngine()
        df = _make_df(120)
        result = engine.compute_single(df, ["momentum_20d", "volatility_20d", "rsi_14"])
        assert "momentum_20d" in result.columns
        assert "volatility_20d" in result.columns
        assert "rsi_14" in result.columns
        assert not result["momentum_20d"].iloc[20:25].isna().all()

    def test_cross_section_with_builtins(self):
        engine = FactorEngine()
        data = {
            "000001": _make_df(120, seed=1),
            "000002": _make_df(120, seed=2),
        }
        result = engine.compute_cross_section(data, ["momentum_20d", "sharpe_20d"])
        assert "momentum_20d" in result.columns
        assert "sharpe_20d" in result.columns
        assert len(result) == 240

    def test_forward_returns_with_data(self):
        engine = FactorEngine()
        data = {
            "000001": _make_df(120, seed=1),
        }
        result = engine.compute_forward_returns(data, period=5)
        assert "forward_5d" in result.columns
        assert len(result) == 120
        assert not np.isnan(result["forward_5d"].iloc[50])
        assert np.isnan(result["forward_5d"].iloc[-1])

    def test_all_builtin_factors_compute(self):
        """验证所有内置因子都能无报错地计算。"""
        engine = FactorEngine()
        df = _make_df(200)

        from easy_tdx.factor.builtin import list_factors

        for f_info in list_factors():
            name = f_info["name"]
            result = engine.compute_single(df, [name])
            assert name in result.columns, f"因子 {name} 计算失败"
