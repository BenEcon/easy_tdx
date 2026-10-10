"""权重优化器。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt
import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Callable


class WeightOptimizer(ABC):
    """权重优化器基类。"""

    @abstractmethod
    def optimize(
        self,
        factor_scores: pd.DataFrame,
        n_stocks: int = 50,
        **kwargs: object,
    ) -> dict[str, float]:
        """返回 {code: weight}，权重和为 1.0。"""
        ...


_OPTIMIZER_REGISTRY: dict[str, type[WeightOptimizer]] = {}


def register_optimizer(name: str) -> Callable[[type[WeightOptimizer]], type[WeightOptimizer]]:
    """注册优化器。"""

    def wrapper(cls: type[WeightOptimizer]) -> type[WeightOptimizer]:
        _OPTIMIZER_REGISTRY[name] = cls
        return cls

    return wrapper


def get_optimizer(name: str) -> WeightOptimizer:
    """按名称获取优化器实例。"""
    if name not in _OPTIMIZER_REGISTRY:
        raise ValueError(f"未知优化器: {name!r}。可用: {sorted(_OPTIMIZER_REGISTRY.keys())}")
    return _OPTIMIZER_REGISTRY[name]()


def _apply_weight_floor(weights: npt.NDArray[np.float64], floor: float) -> npt.NDArray[np.float64]:
    """对权重向量施加下限 floor，保证每只标的都有实质权重，和仍为 1.0。

    把低于 floor 的权重抬到 floor，需补偿的总量按比例从高于 floor 的权重
    中扣除（迭代直至稳定）。若所有权重都需抬到 floor（floor 过大）则回退
    为等权，避免负值。

    Args:
        weights: 原始权重（和为 1.0）。
        floor: 单标的权重下限。

    Returns:
        调整后权重（和为 1.0，每项 ≥ floor，除非 floor*N > 1 时等权）。
    """
    n = len(weights)
    if n == 0 or floor <= 0:
        return weights
    # floor 过大（floor*N > 1）无法满足，直接等权。
    if floor * n >= 1.0:
        return np.full(n, 1.0 / n)

    w = weights.astype(np.float64).copy()
    for _ in range(n + 1):  # 最多迭代 N 次即收敛
        below = w < floor
        if not below.any():
            break
        deficit = np.sum(np.where(below, floor - w, 0.0))
        w = np.where(below, floor, w)
        # 从未触底的部分按比例扣除缺口
        above = w > floor
        surplus = w[above].sum()
        if surplus <= 0:
            break
        w[above] -= deficit * (w[above] / surplus)
    # 兜底归一（消除浮点累积误差）
    total = w.sum()
    if total > 0:
        w = w / total
    return w


@register_optimizer("equal")
class EqualWeightOptimizer(WeightOptimizer):
    """等权 — 取 top-N 等权分配。"""

    def optimize(
        self,
        factor_scores: pd.DataFrame,
        n_stocks: int = 50,
        **kwargs: object,
    ) -> dict[str, float]:
        if factor_scores.empty or "score" not in factor_scores.columns:
            return {}
        top = factor_scores.nlargest(n_stocks, "score")
        if len(top) == 0:
            return {}
        w = 1.0 / len(top)
        return {row["code"]: w for _, row in top.iterrows()}


@register_optimizer("factor_weighted")
class FactorWeightedOptimizer(WeightOptimizer):
    """因子加权 — 按因子得分加权。

    对 top-N 的因子得分做线性归一化后施加权重下限（floor），避免在 N
    较小（如 n_stocks=2）且得分接近时，"减最小值" 把低分标的权重压到
    接近 0、实际等于单股满仓（见 issue #25）。floor 保证每只入选标的都
    拿到至少 ``1/(N*10)`` 的权重，剩余按得分比例分配，权重和仍为 1.0。
    """

    def optimize(
        self,
        factor_scores: pd.DataFrame,
        n_stocks: int = 50,
        **kwargs: object,
    ) -> dict[str, float]:
        top = factor_scores.nlargest(n_stocks, "score")
        if len(top) == 0:
            return {}
        scores: npt.NDArray[np.float64] = top["score"].to_numpy(dtype=np.float64)
        if len(scores) > 10:
            q95 = np.percentile(scores, 95)
            q05 = np.percentile(scores, 5)
            scores = np.clip(scores, q05, q95)
        scores = scores - scores.min() + 1e-8
        total = scores.sum()
        if total == 0:
            w = 1.0 / len(top)
            return {row["code"]: w for _, row in top.iterrows()}
        weights = scores / total

        # 权重下限：每只入选标的至少 1/(N*10)，防止线性归一化在小 N +
        # 得分接近时把低分权重压到 ~0（n_stocks 被实际忽略）。
        n = len(top)
        floor = 1.0 / (n * 10)
        weights = _apply_weight_floor(weights, floor)
        return {row["code"]: float(weights[i]) for i, (_, row) in enumerate(top.iterrows())}


@register_optimizer("risk_parity")
class RiskParityOptimizer(WeightOptimizer):
    """风险平价 — 每只股票贡献相等风险。"""

    def optimize(
        self,
        factor_scores: pd.DataFrame,
        n_stocks: int = 50,
        **kwargs: object,
    ) -> dict[str, float]:
        top = factor_scores.nlargest(n_stocks, "score")
        if len(top) == 0:
            return {}
        if "volatility" in top.columns:
            vol: npt.NDArray[np.float64] = top["volatility"].to_numpy(dtype=np.float64)
        else:
            scores: npt.NDArray[np.float64] = top["score"].abs().to_numpy(dtype=np.float64)
            vol = (1.0 / (scores + 1e-8)).astype(np.float64)
        vol = np.maximum(vol, 1e-8)
        inv_vol = 1.0 / vol
        total = inv_vol.sum()
        weights = inv_vol / total
        return {row["code"]: float(weights[i]) for i, (_, row) in enumerate(top.iterrows())}


@register_optimizer("mean_variance")
class MeanVarianceOptimizer(WeightOptimizer):
    """均值方差优化 — Markowitz 模型（可选 scipy）。"""

    def optimize(
        self,
        factor_scores: pd.DataFrame,
        n_stocks: int = 50,
        **kwargs: object,
    ) -> dict[str, float]:
        try:
            from scipy.optimize import minimize  # noqa: F401

            return self._optimize_with_scipy(factor_scores, n_stocks)

        except ImportError:
            fallback = EqualWeightOptimizer()
            return fallback.optimize(factor_scores, n_stocks)

    def _optimize_with_scipy(
        self,
        factor_scores: pd.DataFrame,
        n_stocks: int,
    ) -> dict[str, float]:
        from scipy.optimize import minimize as _minimize

        top = factor_scores.nlargest(n_stocks, "score")
        if len(top) == 0:
            return {}
        n = len(top)
        scores = top["score"].to_numpy(dtype=np.float64)
        variances = 1.0 / (np.abs(scores) + 1e-8) ** 2
        cov = np.diag(variances)

        def objective(w: npt.NDArray[np.float64]) -> float:
            return float(w @ cov @ w)

        constraints = {"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}
        bounds = [(0.0, 0.1)] * n
        x0 = np.ones(n) / n
        result = _minimize(objective, x0, method="SLSQP", bounds=bounds, constraints=constraints)
        weights = result.x if result.success else np.ones(n) / n
        return {row["code"]: float(weights[i]) for i, (_, row) in enumerate(top.iterrows())}
