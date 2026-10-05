"""简化风险模型。"""

from __future__ import annotations

import numpy as np
import pandas as pd


class RiskModel:
    """简化风险模型 — A 股够用。"""

    def estimate_covariance(
        self,
        returns: pd.DataFrame,
        method: str = "shrinkage",
        shrinkage_intensity: float = 0.5,
        window: int = 60,
    ) -> pd.DataFrame:
        """协方差矩阵估计。"""
        if len(returns) < 2:
            codes = returns.columns.tolist() if len(returns.columns) > 0 else []
            return pd.DataFrame(np.eye(len(codes)), index=codes, columns=codes)
        if len(returns) > window:
            returns = returns.iloc[-window:]
        sample_cov = returns.cov()
        if method == "shrinkage":
            target = pd.DataFrame(
                np.diag(np.diag(sample_cov.to_numpy())),
                index=sample_cov.index,
                columns=sample_cov.columns,
            )
            return (1 - shrinkage_intensity) * sample_cov + shrinkage_intensity * target
        return sample_cov

    def portfolio_risk(
        self,
        weights: dict[str, float],
        cov_matrix: pd.DataFrame,
    ) -> dict[str, float]:
        """组合风险指标。"""
        codes = [c for c in weights if c in cov_matrix.columns]
        if not codes:
            return {"total_volatility": 0.0, "max_risk_contribution": 0.0, "n_positions": 0}
        w = np.array([weights[c] for c in codes])
        cov_sub = cov_matrix.loc[codes, codes].to_numpy()
        var = float(w @ cov_sub @ w)
        total_vol = np.sqrt(max(0, var)) * np.sqrt(252)
        marginal = cov_sub @ w
        risk_contrib = np.abs(w * marginal)
        total_rc = risk_contrib.sum()
        max_rc = float(risk_contrib.max() / total_rc) if total_rc > 0 else 0.0
        return {
            "total_volatility": total_vol,
            "max_risk_contribution": max_rc,
            "n_positions": len(codes),
        }
