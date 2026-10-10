"""单元测试：参数网格寻优器."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.optimizer import (
    GridPointResult,
    OptimizeResult,
    ParamGridOptimizer,
)


def _make_df(n: int = 150, seed: int = 42) -> pd.DataFrame:
    """生成带趋势的合成 OHLCV（确保均线策略能产生交易）。"""
    rng = np.random.default_rng(seed)
    close = 10.0 + np.cumsum(rng.normal(0, 0.3, n) + 0.05)
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=n, freq="B"),
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "vol": rng.integers(1000, 10000, n).astype(float),
            "amount": close * 5000,
        }
    )


class TestParamGridOptimizer:
    """寻优器核心逻辑."""

    def test_grid_enumeration(self) -> None:
        """网格点数应等于笛卡尔积大小。"""
        opt = ParamGridOptimizer(
            strategy_name="ma_cross",
            param_grid={"fast": [5, 10], "slow": [15, 20, 30]},
            df=_make_df(),
        )
        result = opt.run()
        assert len(result.results) == 6  # 2 × 3

    def test_results_sorted_by_return_descending(self) -> None:
        """结果应按 total_return 降序排列。"""
        opt = ParamGridOptimizer(
            strategy_name="ma_cross",
            param_grid={"fast": [5, 10, 20], "slow": [15, 20, 30]},
            df=_make_df(),
        )
        result = opt.run()
        returns = [r.total_return for r in result.results]
        assert returns == sorted(returns, reverse=True)

    def test_best_is_first_result(self) -> None:
        """best 应是 results[0]。"""
        opt = ParamGridOptimizer(
            strategy_name="ma_cross",
            param_grid={"fast": [5, 10], "slow": [20, 30]},
            df=_make_df(),
        )
        result = opt.run()
        assert result.best is not None
        assert result.best.params == result.results[0].params
        assert result.best.total_return == result.results[0].total_return

    def test_heatmap_2_params(self) -> None:
        """2 参数应生成热力图矩阵。"""
        opt = ParamGridOptimizer(
            strategy_name="ma_cross",
            param_grid={"fast": [5, 10, 20], "slow": [15, 20, 30]},
            df=_make_df(),
        )
        result = opt.run()
        assert result.heatmap is not None
        assert result.heatmap["x_name"] == "fast"
        assert result.heatmap["y_name"] == "slow"
        assert len(result.heatmap["x"]) == 3
        assert len(result.heatmap["y"]) == 3
        # 3×3=9 中 fast=20×slow=15（倒挂）与 20×20（相等）被语义约束跳过（issue #39）
        assert len(result.heatmap["data"]) == 7

    def test_no_heatmap_for_single_param(self) -> None:
        """1 参数时 heatmap 应为 None。"""
        opt = ParamGridOptimizer(
            strategy_name="rsi_reversal",
            param_grid={"n": [7, 14, 21]},
            df=_make_df(),
        )
        result = opt.run()
        assert result.heatmap is None
        assert len(result.results) == 3

    def test_inverted_combos_skipped(self) -> None:
        """网格含倒挂组合（fast≥slow）时应全部跳过，best 不可能是倒挂（issue #39）。"""
        opt = ParamGridOptimizer(
            strategy_name="ma_cross",
            param_grid={"fast": [5, 20, 30], "slow": [10, 20]},
            df=_make_df(),
        )
        result = opt.run()
        # 6 组合中仅 (5,10) 与 (5,20) 语义有效
        assert len(result.results) == 2
        assert all(r.params["fast"] < r.params["slow"] for r in result.results)
        assert result.best is not None
        assert result.best.params["fast"] < result.best.params["slow"]

    def test_grid_size_limit_exceeded(self) -> None:
        """超过 MAX_GRID_POINTS 应抛 ValueError。"""
        big_grid = {f"p{i}": list(range(5)) for i in range(6)}  # 5^6 = 15625
        with pytest.raises(ValueError, match="超过上限"):
            ParamGridOptimizer(
                strategy_name="ma_cross",
                param_grid=big_grid,
                df=_make_df(),
            )

    def test_empty_value_list_rejected(self) -> None:
        """空取值列表应抛 ValueError。"""
        with pytest.raises(ValueError, match="空取值列表"):
            ParamGridOptimizer(
                strategy_name="ma_cross",
                param_grid={"fast": [], "slow": [20]},
                df=_make_df(),
            )

    def test_to_dict_serializable(self) -> None:
        """to_dict 应返回 JSON 兼容结构。"""
        opt = ParamGridOptimizer(
            strategy_name="ma_cross",
            param_grid={"fast": [5, 10], "slow": [20, 30]},
            df=_make_df(),
        )
        result = opt.run()
        d = result.to_dict()

        assert d["strategy"] == "ma_cross"
        assert d["param_names"] == ["fast", "slow"]
        assert len(d["results"]) == 4
        assert d["best"] is not None
        assert "params" in d["best"]
        assert "total_return" in d["best"]

    def test_to_dict_cleans_nan(self) -> None:
        """NaN 指标应被清洗为 None（JSON 兼容）。"""
        # 构造含 NaN 的结果（无交易的参数组合 sharpe 可能 NaN）
        result = OptimizeResult(
            strategy="test",
            param_names=["n"],
            results=[
                GridPointResult(params={"n": 1}, total_return=float("nan"), sharpe=float("inf")),
            ],
        )
        d = result.to_dict()
        assert d["results"][0]["total_return"] is None
        assert d["results"][0]["sharpe"] is None

    def test_unknown_strategy_raises(self) -> None:
        """未知策略应在 run() 时抛 KeyError。"""
        opt = ParamGridOptimizer(
            strategy_name="nope",
            param_grid={"x": [1]},
            df=_make_df(),
        )
        with pytest.raises(KeyError):
            opt.run()
