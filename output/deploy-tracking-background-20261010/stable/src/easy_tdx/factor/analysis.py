# src/easy_tdx/factor/analysis.py
"""因子有效性分析引擎。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class FactorReport:
    """单因子分析报告。"""

    name: str
    ic_mean: float
    ic_std: float
    ir: float
    ic_positive_rate: float
    quantile_returns: dict[str, float]
    top_minus_bottom: float
    turnover_rate: float
    autocorr: float
    ic_series: pd.Series


class FactorAnalyzer:
    """因子有效性分析引擎。"""

    def __init__(
        self,
        factor_data: pd.DataFrame,
        return_data: pd.DataFrame,
        factor_col: str = "momentum_20d",
        return_col: str = "forward_5d",
        n_quantiles: int = 5,
    ) -> None:
        self._factor_col = factor_col
        self._return_col = return_col
        self._n_quantiles = n_quantiles
        self._merged = factor_data.merge(
            return_data[["date", "code", return_col]],
            on=["date", "code"],
            how="inner",
        )

    def compute_ic(self, method: str = "spearman") -> pd.Series:
        """逐截面计算 Rank IC。"""
        dates = sorted(self._merged["date"].unique())
        ic_values: list[float] = []
        for date in dates:
            sub = self._merged[self._merged["date"] == date]
            valid = sub[[self._factor_col, self._return_col]].dropna()
            if len(valid) < 5:
                ic_values.append(np.nan)
                continue
            if method == "spearman":
                try:
                    import scipy  # noqa: F401  # pandas spearman lazy import
                except ImportError as e:
                    raise ImportError(
                        "Rank IC (spearman) 需要 scipy，请执行 `pip install easy-tdx[science]`"
                    ) from e
                corr = valid[self._factor_col].corr(valid[self._return_col], method="spearman")
            else:
                corr = valid[self._factor_col].corr(valid[self._return_col], method="pearson")
            ic_values.append(corr)
        return pd.Series(ic_values, index=dates, name="IC")

    def compute_quantile_returns(self) -> pd.DataFrame:
        """分层收益分析。"""
        dates = sorted(self._merged["date"].unique())
        q_names = [f"q{i + 1}" for i in range(self._n_quantiles)]
        rows: list[list[float]] = []
        for date in dates:
            sub = self._merged[self._merged["date"] == date]
            valid = sub[[self._factor_col, self._return_col]].dropna()
            if len(valid) < self._n_quantiles:
                rows.append([np.nan] * self._n_quantiles)
                continue
            valid = valid.copy()
            valid["_q"] = pd.qcut(
                valid[self._factor_col],
                self._n_quantiles,
                labels=False,
                duplicates="drop",
            )
            means = valid.groupby("_q")[self._return_col].mean()
            rows.append([float(means.get(q, np.nan)) for q in range(self._n_quantiles)])
        return pd.DataFrame(rows, index=dates, columns=q_names)

    def compute_turnover(self) -> float:
        """因子换手率。"""
        dates = sorted(self._merged["date"].unique())
        if len(dates) < 2:
            return 0.0
        n_top = max(self._n_quantiles, 5)
        overlaps: list[float] = []
        prev_top: set[str] = set()
        for date in dates:
            sub = self._merged[self._merged["date"] == date]
            valid = sub[[self._factor_col, "code"]].dropna()
            if len(valid) < n_top:
                continue
            top = set(valid.nlargest(n_top, self._factor_col)["code"].tolist())
            if prev_top:
                overlaps.append(len(top & prev_top) / len(top | prev_top))
            prev_top = top
        if not overlaps:
            return 0.0
        return 1.0 - float(np.mean(overlaps))

    def compute_decay(self, max_lag: int = 10) -> pd.DataFrame:
        """因子衰减分析。"""
        ic_series = self.compute_ic()
        autocorr_values: list[float] = []
        for lag in range(1, max_lag + 1):
            if lag < len(ic_series):
                ac = ic_series.autocorr(lag=lag)
                autocorr_values.append(ac if not np.isnan(ac) else 0.0)
            else:
                autocorr_values.append(0.0)
        return pd.DataFrame({"lag": range(1, max_lag + 1), "autocorr": autocorr_values})

    def full_report(self) -> FactorReport:
        """一键生成完整分析报告。"""
        ic_series = self.compute_ic()
        qr = self.compute_quantile_returns()

        ic_mean = float(ic_series.mean()) if len(ic_series) > 0 else 0.0
        ic_std = float(ic_series.std()) if len(ic_series) > 1 else 0.0
        ir = ic_mean / ic_std if ic_std > 0 else 0.0
        ic_positive_rate = float((ic_series > 0).mean()) if len(ic_series) > 0 else 0.0

        quantile_means = qr.mean()
        quantile_returns = {
            f"q{i + 1}": float(quantile_means.iloc[i]) for i in range(len(quantile_means))
        }
        top_minus_bottom = quantile_returns.get("q5", 0.0) - quantile_returns.get("q1", 0.0)

        turnover = self.compute_turnover()
        autocorr = float(ic_series.autocorr(lag=1)) if len(ic_series) > 1 else 0.0

        return FactorReport(
            name=self._factor_col,
            ic_mean=ic_mean,
            ic_std=ic_std,
            ir=ir,
            ic_positive_rate=ic_positive_rate,
            quantile_returns=quantile_returns,
            top_minus_bottom=top_minus_bottom,
            turnover_rate=turnover,
            autocorr=autocorr if not np.isnan(autocorr) else 0.0,
            ic_series=ic_series,
        )
