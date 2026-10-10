# tests/unit/test_factor_transform.py
"""Test factor preprocessing functions."""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.factor.transform import (
    fill_missing,
    orthogonalize,
    preprocess,
    rank_normalize,
    winsorize,
    zscore,
)


def _make_cross_section(n_dates: int = 20, n_stocks: int = 30, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_dates):
        for s in range(n_stocks):
            rows.append(
                {
                    "date": 20240101 + d,
                    "code": f"{s:06d}",
                    "momentum_20d": rng.normal(0.02, 0.05),
                    "volatility_20d": abs(rng.normal(0.02, 0.01)),
                }
            )
    df = pd.DataFrame(rows)
    df.loc[0, "momentum_20d"] = 10.0
    df.loc[1, "momentum_20d"] = -10.0
    df.loc[2, "momentum_20d"] = np.nan
    return df


class TestWinsorize:
    def test_mad_clips_extremes(self):
        df = _make_cross_section()
        result = winsorize(df, ["momentum_20d"], method="mad", threshold=3.0)
        assert result["momentum_20d"].max() < 10.0
        assert result["momentum_20d"].min() > -10.0

    def test_preserves_shape(self):
        df = _make_cross_section()
        result = winsorize(df, ["momentum_20d"])
        assert len(result) == len(df)
        assert list(result.columns) == list(df.columns)


class TestZscore:
    def test_cross_section_standardization(self):
        df = _make_cross_section()
        result = zscore(df, ["momentum_20d"], cross_section=True)
        for date in result["date"].unique():
            sub = result[result["date"] == date]["momentum_20d"].dropna()
            if len(sub) > 2:
                assert abs(sub.mean()) < 0.5

    def test_preserves_nan(self):
        df = _make_cross_section()
        result = zscore(df, ["momentum_20d"])
        assert result["momentum_20d"].isna().sum() >= 1


class TestRankNormalize:
    def test_output_range(self):
        df = _make_cross_section()
        result = rank_normalize(df, ["momentum_20d"])
        valid = result["momentum_20d"].dropna()
        assert valid.min() >= 0
        assert valid.max() <= 1


class TestFillMissing:
    def test_cross_mean_fills(self):
        df = _make_cross_section()
        na_before = df["momentum_20d"].isna().sum()
        result = fill_missing(df, ["momentum_20d"], method="cross_mean")
        na_after = result["momentum_20d"].isna().sum()
        assert na_after < na_before

    def test_forward_fill(self):
        df = _make_cross_section()
        result = fill_missing(df, ["momentum_20d"], method="forward_fill")
        assert len(result) == len(df)


class TestOrthogonalize:
    def test_residual_differs(self):
        df = _make_cross_section()
        df = zscore(df, ["momentum_20d", "volatility_20d"])
        df = fill_missing(df, ["momentum_20d", "volatility_20d"], method="cross_mean")
        result = orthogonalize(df, target="momentum_20d", by="volatility_20d")
        assert "momentum_20d" in result.columns
        assert not result["momentum_20d"].equals(df["momentum_20d"])


class TestPreprocess:
    def test_default_pipeline(self):
        df = _make_cross_section()
        result = preprocess(df, ["momentum_20d"])
        assert len(result) == len(df)
        assert "momentum_20d" in result.columns
        assert result["momentum_20d"].isna().sum() <= df["momentum_20d"].isna().sum()

    def test_custom_steps(self):
        df = _make_cross_section()
        result = preprocess(df, ["momentum_20d"], steps=["winsorize", "zscore"])
        assert len(result) == len(df)

    def test_preserves_other_columns(self):
        df = _make_cross_section()
        result = preprocess(df, ["momentum_20d"])
        assert "date" in result.columns
        assert "code" in result.columns
        assert "volatility_20d" in result.columns
