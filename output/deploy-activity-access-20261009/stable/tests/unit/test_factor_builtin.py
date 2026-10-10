"""Test built-in factor computation correctness."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor.base import FACTORY_REGISTRY
from easy_tdx.factor.builtin import get_factor, list_factors


def _make_df(n: int = 120, seed: int = 42) -> pd.DataFrame:
    """生成合成 OHLCV 数据（120 行，满足所有因子最小窗口）。"""
    rng = np.random.default_rng(seed)
    close = 10.0 + np.cumsum(rng.normal(0, 0.3, n))
    close = np.maximum(close, 1.0)
    high = close + rng.uniform(0, 0.3, n)
    low = close - rng.uniform(0, 0.3, n)
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


# ── Auto-registration ──────────────────────────────────────────────


class TestAutoRegistration:
    def test_momentum_factors_registered(self):
        assert "momentum_20d" in FACTORY_REGISTRY
        assert "momentum_60d" in FACTORY_REGISTRY
        assert "reversal_5d" in FACTORY_REGISTRY

    def test_volatility_factors_registered(self):
        assert "volatility_20d" in FACTORY_REGISTRY
        assert "atr_14d" in FACTORY_REGISTRY
        assert "turnover_rate" in FACTORY_REGISTRY

    def test_quality_factors_registered(self):
        assert "sharpe_20d" in FACTORY_REGISTRY
        assert "max_drawdown_20d" in FACTORY_REGISTRY
        assert "win_rate_20d" in FACTORY_REGISTRY

    def test_volume_factors_registered(self):
        assert "obv_trend" in FACTORY_REGISTRY
        assert "vol_surge" in FACTORY_REGISTRY
        assert "amount_ma_ratio" in FACTORY_REGISTRY

    def test_technical_factors_registered(self):
        assert "macd_hist_signal" in FACTORY_REGISTRY
        assert "rsi_14" in FACTORY_REGISTRY
        assert "boll_position" in FACTORY_REGISTRY

    def test_chanlun_factors_registered(self):
        assert "chanlun_bi_dir" in FACTORY_REGISTRY
        assert "chanlun_mmd" in FACTORY_REGISTRY

    def test_value_factors_registered(self):
        assert "pe_ratio" in FACTORY_REGISTRY
        assert "pb_ratio" in FACTORY_REGISTRY

    def test_total_factor_count(self):
        assert len(FACTORY_REGISTRY) >= 19


# ── list_factors / get_factor ───────────────────────────────────────


class TestListAndGetFactors:
    def test_list_factors_returns_all(self):
        factors = list_factors()
        assert len(factors) >= 19
        for f in factors:
            assert "name" in f
            assert "category" in f
            assert "description" in f

    def test_get_factor_existing(self):
        cls = get_factor("momentum_20d")
        assert cls.name == "momentum_20d"

    def test_get_factor_nonexistent(self):
        with pytest.raises(ValueError, match="未知因子"):
            get_factor("nonexistent")


# ── Momentum compute ───────────────────────────────────────────────


class TestMomentumCompute:
    def test_momentum_20d(self):
        f = get_factor("momentum_20d")()
        df = _make_df()
        result = f.compute(df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(df)
        assert not np.isnan(result.iloc[20])

    def test_momentum_60d(self):
        f = get_factor("momentum_60d")()
        df = _make_df()
        result = f.compute(df)
        assert not np.isnan(result.iloc[60])

    def test_reversal_5d_is_negative_return(self):
        f = get_factor("reversal_5d")()
        df = _make_df()
        result = f.compute(df)
        expected = -df["close"].pct_change(5)
        pd.testing.assert_series_equal(result, expected, check_names=False)


# ── Volatility compute ─────────────────────────────────────────────


class TestVolatilityCompute:
    def test_volatility_20d(self):
        f = get_factor("volatility_20d")()
        df = _make_df()
        result = f.compute(df)
        assert result.iloc[20] > 0

    def test_atr_14d(self):
        f = get_factor("atr_14d")()
        df = _make_df()
        result = f.compute(df)
        assert result.iloc[14] > 0

    def test_turnover_rate(self):
        f = get_factor("turnover_rate")()
        df = _make_df()
        result = f.compute(df)
        assert result.iloc[40] > 0


# ── Quality compute ────────────────────────────────────────────────


class TestQualityCompute:
    def test_sharpe_20d(self):
        f = get_factor("sharpe_20d")()
        df = _make_df()
        result = f.compute(df)
        assert len(result) == len(df)

    def test_max_drawdown_20d(self):
        f = get_factor("max_drawdown_20d")()
        df = _make_df()
        result = f.compute(df)
        valid = result.dropna()
        assert (valid <= 0).all()

    def test_win_rate_20d(self):
        f = get_factor("win_rate_20d")()
        df = _make_df()
        result = f.compute(df)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 1).all()


# ── Volume compute ─────────────────────────────────────────────────


class TestVolumeCompute:
    def test_vol_surge(self):
        f = get_factor("vol_surge")()
        df = _make_df()
        result = f.compute(df)
        assert result.iloc[20] > 0

    def test_amount_ma_ratio(self):
        f = get_factor("amount_ma_ratio")()
        df = _make_df()
        result = f.compute(df)
        assert len(result) == len(df)


# ── Technical compute ──────────────────────────────────────────────


class TestTechnicalCompute:
    def test_rsi_14_range(self):
        f = get_factor("rsi_14")()
        df = _make_df()
        result = f.compute(df)
        valid = result.dropna()
        assert (valid >= -1).all()
        assert (valid <= 1).all()

    def test_boll_position_range(self):
        f = get_factor("boll_position")()
        df = _make_df()
        result = f.compute(df)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 1).all()
