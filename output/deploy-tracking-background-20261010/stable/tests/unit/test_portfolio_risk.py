"""Test RiskModel."""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.portfolio.risk import RiskModel


def _make_returns(n_dates: int = 100, n_stocks: int = 5, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    codes = [f"{i:06d}" for i in range(n_stocks)]
    return pd.DataFrame(rng.normal(0.001, 0.02, (n_dates, n_stocks)), columns=codes)


class TestCovarianceEstimation:
    def test_shape(self):
        cov = RiskModel().estimate_covariance(_make_returns())
        assert cov.shape == (5, 5)

    def test_symmetric(self):
        cov = RiskModel().estimate_covariance(_make_returns())
        assert np.allclose(cov.to_numpy(), cov.to_numpy().T)

    def test_shrinkage_reduces_offdiag(self):
        rm = RiskModel()
        ret = _make_returns()
        shrunk = rm.estimate_covariance(ret, method="shrinkage")
        sample = rm.estimate_covariance(ret, method="sample")
        off_shrunk = shrunk.values[~np.eye(5, dtype=bool)]
        off_sample = sample.values[~np.eye(5, dtype=bool)]
        assert np.abs(off_shrunk).mean() <= np.abs(off_sample).mean()


class TestPortfolioRisk:
    def test_total_volatility(self):
        cov = RiskModel().estimate_covariance(_make_returns())
        risk = RiskModel().portfolio_risk({"000000": 0.5, "000001": 0.5}, cov)
        assert risk["total_volatility"] > 0
        assert risk["n_positions"] == 2

    def test_empty_weights(self):
        risk = RiskModel().portfolio_risk({}, pd.DataFrame())
        assert risk["total_volatility"] == 0.0
