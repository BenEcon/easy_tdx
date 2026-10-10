# src/easy_tdx/factor/transform.py
"""因子预处理 — 纯函数管道。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def winsorize(
    factor_data: pd.DataFrame,
    columns: str | list[str],
    method: str = "mad",
    threshold: float = 3.0,
) -> pd.DataFrame:
    """截面去极值。"""
    if isinstance(columns, str):
        columns = [columns]
    result = factor_data.copy()

    for col in columns:
        if col not in result.columns:
            continue

        def _clip_group(group: pd.Series) -> pd.Series:
            valid = group.dropna()
            if len(valid) < 3:
                return group
            if method == "mad":
                median = valid.median()
                mad = (valid - median).abs().median() * 1.4826
                lower = median - threshold * mad
                upper = median + threshold * mad
            elif method == "sigma":
                mean = valid.mean()
                std = valid.std()
                lower = mean - threshold * std
                upper = mean + threshold * std
            elif method == "percentile":
                lower = valid.quantile(0.025)
                upper = valid.quantile(0.975)
            else:
                raise ValueError(f"未知去极值方法: {method!r}")
            return group.clip(lower, upper)

        if "date" in result.columns:
            result[col] = result.groupby("date")[col].transform(_clip_group)
        else:
            result[col] = _clip_group(result[col])

    return result


def zscore(
    factor_data: pd.DataFrame,
    columns: str | list[str],
    cross_section: bool = True,
) -> pd.DataFrame:
    """标准化。"""
    if isinstance(columns, str):
        columns = [columns]
    result = factor_data.copy()

    for col in columns:
        if col not in result.columns:
            continue

        def _zscore_group(group: pd.Series) -> pd.Series:
            std = group.std()
            if std == 0 or pd.isna(std):
                return group * 0
            return (group - group.mean()) / std

        if cross_section and "date" in result.columns:
            result[col] = result.groupby("date")[col].transform(_zscore_group)
        else:
            result[col] = _zscore_group(result[col])

    return result


def rank_normalize(
    factor_data: pd.DataFrame,
    columns: str | list[str],
) -> pd.DataFrame:
    """排名归一化 [0, 1]。"""
    if isinstance(columns, str):
        columns = [columns]
    result = factor_data.copy()

    for col in columns:
        if col not in result.columns:
            continue

        def _rank_group(group: pd.Series) -> pd.Series:
            return group.rank(pct=True)

        if "date" in result.columns:
            result[col] = result.groupby("date")[col].transform(_rank_group)
        else:
            result[col] = _rank_group(result[col])

    return result


def fill_missing(
    factor_data: pd.DataFrame,
    columns: str | list[str],
    method: str = "cross_mean",
) -> pd.DataFrame:
    """缺失值填充。"""
    if isinstance(columns, str):
        columns = [columns]
    result = factor_data.copy()

    for col in columns:
        if col not in result.columns:
            continue
        if method == "cross_mean":
            if "date" in result.columns:

                def _fill_mean(group: pd.Series) -> pd.Series:
                    return group.fillna(group.mean())

                result[col] = result.groupby("date")[col].transform(_fill_mean)
            else:
                result[col] = result[col].fillna(result[col].mean())
        elif method == "forward_fill":
            if "code" in result.columns:
                result[col] = result.groupby("code")[col].ffill()
            else:
                result[col] = result[col].ffill()
        else:
            raise ValueError(f"未知填充方法: {method!r}")

    return result


def orthogonalize(
    factor_data: pd.DataFrame,
    target: str,
    by: str | list[str],
) -> pd.DataFrame:
    """因子正交化。"""
    if isinstance(by, str):
        by = [by]
    result = factor_data.copy()

    if target not in result.columns:
        return result
    for b in by:
        if b not in result.columns:
            return result

    y = result[target].to_numpy(dtype=np.float64)
    X_cols = [result[b].to_numpy(dtype=np.float64) for b in by]
    X = np.column_stack([np.ones(len(y))] + X_cols)

    mask = ~np.isnan(y)
    for xc in X_cols:
        mask &= ~np.isnan(xc)

    if mask.sum() < len(by) + 2:
        return result

    coef, _, _, _ = np.linalg.lstsq(X[mask], y[mask], rcond=None)
    predicted = X @ coef
    residual = y - predicted
    residual[~mask] = np.nan
    result[target] = residual

    return result


def preprocess(
    factor_data: pd.DataFrame,
    columns: list[str],
    steps: list[str] | None = None,
) -> pd.DataFrame:
    """一键预处理管道。"""
    if steps is None:
        steps = ["winsorize", "zscore", "fill_missing"]

    result = factor_data.copy()
    for step in steps:
        if step == "winsorize":
            result = winsorize(result, columns)
        elif step == "zscore":
            result = zscore(result, columns)
        elif step == "rank_normalize":
            result = rank_normalize(result, columns)
        elif step == "fill_missing":
            result = fill_missing(result, columns)
        else:
            raise ValueError(f"未知预处理步骤: {step!r}")

    return result
