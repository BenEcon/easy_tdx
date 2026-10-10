# tests/unit/test_factor_analysis.py
"""Test FactorAnalyzer and FactorReport."""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.factor.analysis import FactorAnalyzer, FactorReport


def _make_factor_and_return(
    n_dates: int = 50,
    n_stocks: int = 20,
    seed: int = 42,
    ic: float = 0.05,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    rows_f, rows_r = [], []
    for d in range(n_dates):
        factor_vals = rng.normal(0, 1, n_stocks)
        noise = rng.normal(0, 1, n_stocks)
        returns = ic * factor_vals + (1 - ic) * noise
        for s in range(n_stocks):
            rows_f.append({"date": 20240101 + d, "code": f"{s:06d}", "test_factor": factor_vals[s]})
            rows_r.append({"date": 20240101 + d, "code": f"{s:06d}", "forward_5d": returns[s]})
    return pd.DataFrame(rows_f), pd.DataFrame(rows_r)


class TestFactorReport:
    def test_report_fields(self):
        report = FactorReport(
            name="test",
            ic_mean=0.05,
            ic_std=0.1,
            ir=0.5,
            ic_positive_rate=0.6,
            quantile_returns={"q1": -0.01, "q2": 0.0, "q3": 0.01, "q4": 0.02, "q5": 0.03},
            top_minus_bottom=0.04,
            turnover_rate=0.3,
            autocorr=0.8,
            ic_series=pd.Series([0.1, 0.05, -0.02]),
        )
        assert report.name == "test"
        assert report.ir == 0.5


class TestFactorAnalyzerIC:
    def test_compute_ic_returns_series(self):
        fd, rd = _make_factor_and_return(ic=0.1)
        analyzer = FactorAnalyzer(fd, rd, factor_col="test_factor", return_col="forward_5d")
        ic_series = analyzer.compute_ic()
        assert isinstance(ic_series, pd.Series)
        assert len(ic_series) == 50

    def test_positive_ic_detected(self):
        fd, rd = _make_factor_and_return(ic=0.3)
        analyzer = FactorAnalyzer(fd, rd, factor_col="test_factor", return_col="forward_5d")
        ic_series = analyzer.compute_ic()
        assert ic_series.mean() > 0.05

    def test_zero_ic_detected(self):
        fd, rd = _make_factor_and_return(ic=0.0)
        analyzer = FactorAnalyzer(fd, rd, factor_col="test_factor", return_col="forward_5d")
        ic_series = analyzer.compute_ic()
        assert abs(ic_series.mean()) < 0.15


class TestFactorAnalyzerQuantile:
    def test_quantile_returns(self):
        fd, rd = _make_factor_and_return(ic=0.1)
        analyzer = FactorAnalyzer(fd, rd, factor_col="test_factor", return_col="forward_5d")
        qr = analyzer.compute_quantile_returns()
        assert isinstance(qr, pd.DataFrame)
        assert len(qr.columns) == 5

    def test_monotonic_with_positive_ic(self):
        fd, rd = _make_factor_and_return(ic=0.3)
        analyzer = FactorAnalyzer(fd, rd, factor_col="test_factor", return_col="forward_5d")
        qr = analyzer.compute_quantile_returns()
        means = qr.mean()
        assert means.iloc[-1] > means.iloc[0]


class TestFactorAnalyzerReport:
    def test_full_report(self):
        fd, rd = _make_factor_and_return(ic=0.1)
        analyzer = FactorAnalyzer(fd, rd, factor_col="test_factor", return_col="forward_5d")
        report = analyzer.full_report()
        assert isinstance(report, FactorReport)
        assert report.name == "test_factor"
        assert isinstance(report.ic_mean, float)
        assert len(report.quantile_returns) == 5
        assert "q1" in report.quantile_returns

    def test_report_ic_positive_rate(self):
        fd, rd = _make_factor_and_return(ic=0.3)
        analyzer = FactorAnalyzer(fd, rd, factor_col="test_factor", return_col="forward_5d")
        report = analyzer.full_report()
        assert report.ic_positive_rate > 0.5


class TestFactorAnalyzerDecay:
    def test_decay_returns_dataframe(self):
        fd, rd = _make_factor_and_return(ic=0.1)
        analyzer = FactorAnalyzer(fd, rd, factor_col="test_factor", return_col="forward_5d")
        decay = analyzer.compute_decay(max_lag=5)
        assert isinstance(decay, pd.DataFrame)
        assert len(decay) == 5


class TestFactorAnalyzerTurnover:
    def test_turnover_in_range(self):
        fd, rd = _make_factor_and_return(ic=0.1)
        analyzer = FactorAnalyzer(fd, rd, factor_col="test_factor", return_col="forward_5d")
        to = analyzer.compute_turnover()
        assert 0 <= to <= 1
