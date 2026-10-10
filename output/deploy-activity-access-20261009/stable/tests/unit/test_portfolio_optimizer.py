"""Test portfolio optimizers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.portfolio.optimizer import (
    EqualWeightOptimizer,
    FactorWeightedOptimizer,
    RiskParityOptimizer,
    get_optimizer,
)


def _make_scores(n: int = 20, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "code": [f"{i:06d}" for i in range(n)],
            "score": rng.normal(0.02, 0.05, n),
        }
    )


class TestEqualWeight:
    def test_weights_sum_to_one(self):
        w = EqualWeightOptimizer().optimize(_make_scores(), n_stocks=10)
        assert abs(sum(w.values()) - 1.0) < 1e-8

    def test_n_stocks_selected(self):
        w = EqualWeightOptimizer().optimize(_make_scores(), n_stocks=5)
        assert len(w) == 5

    def test_all_equal(self):
        w = EqualWeightOptimizer().optimize(_make_scores(), n_stocks=10)
        vals = list(w.values())
        assert all(abs(v - vals[0]) < 1e-8 for v in vals)

    def test_empty_input(self):
        w = EqualWeightOptimizer().optimize(pd.DataFrame(columns=["code", "score"]), n_stocks=5)
        assert len(w) == 0


class TestFactorWeighted:
    def test_weights_sum_to_one(self):
        w = FactorWeightedOptimizer().optimize(_make_scores(), n_stocks=10)
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_higher_score_higher_weight(self):
        scores = pd.DataFrame({"code": ["A", "B", "C"], "score": [3.0, 2.0, 1.0]})
        w = FactorWeightedOptimizer().optimize(scores, n_stocks=3)
        assert w["A"] > w["C"]

    def test_no_weight_collapse_small_n(self):
        """issue #25: n_stocks=2 且得分接近时，权重不应坍缩到接近 0。

        修复前 scores=[0.5, 0.34] 经"减最小值"后权重变成 ~1.0 / ~6e-8，
        等于单股满仓、n_stocks=2 被忽略。修复后每只标的都有实质权重。
        """
        scores = pd.DataFrame({"code": ["A", "B"], "score": [0.50, 0.34]})
        w = FactorWeightedOptimizer().optimize(scores, n_stocks=2)
        assert len(w) == 2
        assert abs(sum(w.values()) - 1.0) < 1e-6
        # 两只都应有实质权重（≥ 0.05），低分股不再被压到 ~0
        assert min(w.values()) >= 0.05
        # 高分股权重仍更高
        assert w["A"] > w["B"]


class TestRiskParity:
    def test_weights_sum_to_one(self):
        w = RiskParityOptimizer().optimize(_make_scores(), n_stocks=10)
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_with_volatility_column(self):
        scores = pd.DataFrame(
            {
                "code": ["A", "B", "C"],
                "score": [1.0, 1.0, 1.0],
                "volatility": [0.1, 0.2, 0.4],
            }
        )
        w = RiskParityOptimizer().optimize(scores, n_stocks=3)
        assert w["A"] > w["C"]


class TestRegistry:
    def test_get_optimizer(self):
        assert isinstance(get_optimizer("equal"), EqualWeightOptimizer)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="未知优化器"):
            get_optimizer("nonexistent")
