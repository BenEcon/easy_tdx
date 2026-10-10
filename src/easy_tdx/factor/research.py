"""Bounded retrospective cross-sectional diagnostics, not executable returns."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from easy_tdx.computation import computation_checkpoint
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.composition import (
    COMPOSITION_VERSION,
    SCORE_NAME,
    compose_scores,
    normalize_composition,
)
from easy_tdx.factor.engine import FactorEngine
from easy_tdx.factor.horizons import HORIZON_VERSION, normalize_horizons
from easy_tdx.factor.report_summary import number, summarize_rows
from easy_tdx.factor.statistics import (
    NUMERIC_POLICY,
    STATISTICS_VERSION,
    coalesced,
    distinct_count,
    indistinguishable,
    mad_zscore,
    mean,
    stable_correlation,
)
from easy_tdx.factor.validation import (
    VALIDATION_VERSION,
    normalize_validation,
    time_validation,
    validation_plan,
)
from easy_tdx.progress import ProgressPublicationError, report_progress


def correlation(x: pd.Series, y: pd.Series, *, rank: bool = False) -> float | None:
    return stable_correlation(x, y, rank=rank)


def prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    time_key = "datetime" if "datetime" in df else "date"
    dates = pd.to_datetime(df[time_key], errors="raise")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    df.index = pd.DatetimeIndex(dates.dt.normalize())
    if df.index.has_duplicates or not df.index.is_monotonic_increasing:
        raise ValueError("日线日期重复或未按时间递增；已停止因子检验")
    close = pd.to_numeric(df["close"], errors="raise")
    if not np.isfinite(close).all() or (close <= 0).any():
        raise ValueError("收盘价缺失、非正或无效；已停止因子检验")
    return df


def cross_section_report(
    data: dict[str, pd.DataFrame],
    factors: list[str],
    horizon: int,
    groups: int,
    preprocess: str = "raw",
    *,
    factor_parameters: dict[str, dict[str, Any]] | None = None,
    validation: dict[str, Any] | None = None,
    horizons: list[int] | None = None,
    composition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """No imputation, no tie splitting, no current membership as historical PIT."""
    # The core is also used by frozen-input replay and local research scripts.
    # Never rely solely on the HTTP schema: a negative horizon would turn a
    # purported forward label into a backward-looking return.
    if type(horizon) is not int or horizon < 1:
        raise ValueError("远期窗口必须为正整数（观测日数）")
    if type(groups) is not int or not 2 <= groups <= len(data):
        raise ValueError("分层数必须为整数，且在 2 与股票池标的数之间")
    if preprocess not in {"raw", "mad_zscore"}:
        raise ValueError("未知预处理方式；仅支持 raw 或 mad_zscore")
    if len(data) < 5 or any(frame.empty for frame in data.values()):
        raise ValueError("至少需要 5 只具有行情的标的")
    requested_horizons = normalize_horizons(horizon, horizons)
    composition = normalize_composition(composition, factors)
    # Validate provided configurations before expensive work, keeping legacy
    # unknown-factor per-result diagnostics when no configuration was supplied.
    if factor_parameters:
        from easy_tdx.factor.configuration import configured_selection

        configured_selection(factors, factor_parameters)
    frames = {symbol: prepare_frame(frame) for symbol, frame in data.items()}
    closes = pd.concat(
        {symbol: frame["close"] for symbol, frame in frames.items()}, axis=1
    ).sort_index()
    dates = closes.index
    if horizons is not None and len(dates) > 800:
        raise ValueError("多远期检验合并观测日超过 800 根上限；未截断日期或股票池")
    validation = normalize_validation(validation)
    plans = {h: validation_plan(dates, h, validation) for h in requested_horizons}
    # A label requires the entire intervening observed window, including endpoints.
    returns_by_horizon = {}
    for h in requested_horizons:
        complete = closes.notna().rolling(h + 1).sum().shift(-h).eq(h + 1)
        returns_by_horizon[h] = (
            (closes.shift(-h) / closes - 1).where(complete).replace([np.inf, -np.inf], np.nan)
        )
    matrices: dict[str, pd.DataFrame] = {}
    raw_matrices: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    reports_by_horizon: dict[int, list[dict[str, Any]]] = {h: [] for h in requested_horizons}
    definitions: dict[str, Any] = {}
    for name in factors:
        computation_checkpoint()
        report_progress("factor_values", 0, len(frames), name[:96])
        try:
            from easy_tdx.factor.configuration import configure_factor

            parameters = (factor_parameters or {}).get(name)
            factor = configure_factor(name, parameters)
            definitions[name] = describe_factor(type(factor), parameters)
            for symbol, frame in frames.items():
                if definitions[name].get("status") == "conditional":
                    from easy_tdx.factor.catalog import availability_reason

                    actual_adjust = frame.attrs.get("snapshot_metadata", {}).get("actual_adjust")
                    adjustment_error = availability_reason(
                        definitions[name], actual_adjust, evaluation=True
                    )
                    if adjustment_error:
                        raise ValueError(f"{symbol} {adjustment_error}")
                for field in factor.inputs:
                    reason = frame.attrs.get("factor_input_errors", {}).get(field)
                    if reason:
                        raise ValueError(f"{symbol} {reason}")
                missing = set(factor.inputs) - set(frame.columns)
                if missing:
                    raise ValueError(f"{symbol} 缺少字段：{', '.join(sorted(missing))}")
            values = FactorEngine().compute_matrix(
                frames,
                factor,
                progress=lambda position, total: report_progress(
                    "factor_values", position, total, name[:96]
                ),
            )
        except ProgressPublicationError:
            raise
        except Exception as exc:
            errors[name] = str(exc)
            continue
        raw_coverage = int(values.notna().sum().sum())
        raw_matrices[name] = values
        raw_counts = values.notna().sum(axis=1)
        preprocessing_constant = {}
        if preprocess == "mad_zscore":
            preprocessing_constant = {date: distinct_count(values.loc[date]) == 1 for date in dates}
            values = values.apply(mad_zscore, axis=1)
        matrices[name] = values
        report_progress("factor_windows", 0, len(requested_horizons), name[:96])
        for position, h in enumerate(requested_horizons, 1):
            rows = daily_report(
                values, returns_by_horizon[h], raw_counts, preprocessing_constant, h, groups
            )
            reports_by_horizon[h].append(
                summarize_rows(name, raw_coverage / max(1, closes.size), rows)
            )
            report_progress("factor_windows", position, len(requested_horizons), name[:96])
    redundancy = []
    if matrices:
        report_progress("redundancy", 0, len(matrices) ** 2)
    for left in matrices:
        for right in matrices:
            observations = [
                correlation(matrices[left].loc[day], matrices[right].loc[day], rank=True)
                for day in dates
            ]
            sample = pd.Series(observations, dtype=float).dropna()
            redundancy.append(
                {
                    "left": left,
                    "right": right,
                    "correlation": number(sample.mean()),
                    "dates": len(sample),
                }
            )
            report_progress("redundancy", len(redundancy), len(matrices) ** 2)
    latest = [
        {
            "code": code,
            "date": dates[-1].strftime("%Y-%m-%d"),
            **{name: number(matrix.loc[dates[-1], code]) for name, matrix in matrices.items()},
        }
        for code in closes.columns
    ]
    fingerprint = hashlib.sha256()
    for code, frame in frames.items():
        fingerprint.update(code.encode())
        fingerprint.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
        fingerprint.update(
            json.dumps(frame.attrs.get("factor_data_contract"), sort_keys=True).encode()
        )
    settings = {
        "factors": factors,
        "horizon": horizon,
        "groups": groups,
        "preprocess": preprocess,
        "factor_parameters": factor_parameters or {},
        "validation": validation,
        "horizons": requested_horizons if horizons is not None else None,
        "composition": composition,
    }
    fingerprint.update(json.dumps(settings, sort_keys=True).encode())
    fingerprint.update(json.dumps(definitions, sort_keys=True).encode())
    fingerprint.update(json.dumps(NUMERIC_POLICY, sort_keys=True).encode())
    if validation is not None:
        fingerprint.update(VALIDATION_VERSION.encode())
    if horizons is not None:
        fingerprint.update(HORIZON_VERSION.encode())
    if composition is not None:
        fingerprint.update(COMPOSITION_VERSION.encode())
    horizon_results = []
    if validation is not None:
        report_progress("time_validation", 0, len(requested_horizons))
    for position, h in enumerate(requested_horizons, 1):
        horizon_results.append(
            {
                "horizon": h,
                "reports": reports_by_horizon[h],
                "validation": time_validation(
                    reports_by_horizon[h], dates, len(frames), h, validation, plans[h]
                )
                if validation is not None
                else None,
            }
        )
        if validation is not None:
            report_progress("time_validation", position, len(requested_horizons))
    primary = next(r for r in horizon_results if r["horizon"] == horizon)
    combination = None
    if composition is not None:
        scores, combination = compose_scores(raw_matrices, closes, composition)
        combined_results = []
        for h in requested_horizons:
            rows = daily_report(
                scores, returns_by_horizon[h], scores.notna().sum(axis=1), {}, h, groups
            )
            reports = [
                summarize_rows(SCORE_NAME, float(scores.notna().sum().sum() / scores.size), rows)
            ]
            combined_results.append(
                {
                    "horizon": h,
                    "reports": reports,
                    "validation": time_validation(
                        reports, dates, len(frames), h, validation, plans[h]
                    )
                    if validation is not None
                    else None,
                }
            )
        combined_primary = next(r for r in combined_results if r["horizon"] == horizon)
        combination.update(
            reports=combined_primary["reports"],
            validation=combined_primary["validation"],
            horizon_comparison={
                "version": HORIZON_VERSION,
                "horizons": requested_horizons,
                "results": combined_results,
                "sample_policy": "each_horizon_own_complete_labels",
            },
        )
    return {
        "version": "factor-cross-section-v1",
        "statistics_version": STATISTICS_VERSION,
        "numeric_policy": dict(NUMERIC_POLICY),
        "settings": settings,
        "factor_definitions": definitions,
        "reports": primary["reports"],
        "validation": primary["validation"],
        "composition": combination,
        "horizon_comparison": {
            "version": HORIZON_VERSION,
            "horizons": requested_horizons,
            "results": horizon_results,
            "sample_policy": "each_horizon_own_complete_labels",
        }
        if horizons is not None
        else None,
        "errors": errors,
        "latest": latest,
        "redundancy": redundancy,
        "input_fingerprint": fingerprint.hexdigest(),
        "start": dates[0].strftime("%Y-%m-%d"),
        "end": dates[-1].strftime("%Y-%m-%d"),
        "date_count": len(dates),
        "assets": len(frames),
        "missing_bars": int(closes.isna().sum().sum()),
        "trade_eligible": False,
        "limitations": [
            "自选样本的回顾性检验，不代表全市场或独立样本外验证；未使用历史成分股。",
            "远期收益是信号日收盘至随后合并观测日收盘的价格变化，不是可成交策略收益；未计成本、涨跌停与停牌。",
            "远期窗口含缺失行情或尚未完成时不参与统计；不填零、不前向补值。",
            "多日收益窗口重叠，信息比率未年化；分层均值不复利为净值。复权数据不保证历史当时可得。",
            "正相关不自动成为买入建议；负相关不自动反转方向。未做行业／市值中性化和多重检验。",
            "数值规则 v2：32 倍 float64 精度的同尺度差异视为并列；因子无固定绝对阈值，"
            "价格比远期收益采用单位算术尺度。近常数不计算相关，标准化不放大其噪声。",
            "分层保留原始收益均值；高低组差在收益算术分辨率内记数值零（不是缺失填零）。容差是明确的工程规则，不是经济显著性或严格误差传播证明。",
        ],
    }


def daily_report(
    values: pd.DataFrame,
    returns: pd.DataFrame,
    raw_counts: pd.Series,
    preprocessing_constant: dict[Any, bool],
    horizon: int,
    groups: int,
) -> list[dict[str, Any]]:
    """Same-date diagnostics, with shared factor values and independent labels."""
    dates = values.index
    rows: list[dict[str, Any]] = []
    for position, date in enumerate(dates):
        computation_checkpoint()
        pair = pd.concat(
            [values.loc[date].rename("factor"), returns.loc[date].rename("return")], axis=1
        ).dropna()
        reason = None
        ic = rank_ic = None
        layer_values: list[float | None] = [None] * groups
        if preprocessing_constant.get(date):
            reason = "原始因子截面为常数或近常数，未标准化放大浮点噪声"
        elif len(pair) < max(5, groups):
            reason = "有效标的不足（含预热、缺失或远期窗口未完成）"
        else:
            ic = stable_correlation(pair["factor"], pair["return"], y_floor=1.0)
            rank_ic = stable_correlation(pair["factor"], pair["return"], rank=True, y_floor=1.0)
            grouping = coalesced(pair["factor"])
            if grouping.nunique() < 2:
                reason = "因子为常数或近常数，相关系数及分层未定义"
            elif grouping.nunique() < groups:
                reason = "因子取值过少，不能完整分层"
            else:
                bins = pd.qcut(
                    grouping.rank(method="average"), groups, labels=False, duplicates="drop"
                )
                if bins.nunique() != groups:
                    reason = "分位边界重复，未强拆相同因子值"
                else:
                    layer_values = [
                        number(mean(pair.loc[bins == q, "return"].to_numpy()))
                        for q in range(groups)
                    ]
            if rank_ic is None and grouping.nunique() >= 2:
                return_reason = "远期收益为常数或近常数，相关系数未定义"
                if all(value is not None for value in layer_values):
                    return_reason += "；分层均值仅作描述"
                reason = f"{reason}；{return_reason}" if reason else return_reason
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "label_end": dates[position + horizon].strftime("%Y-%m-%d")
                if position + horizon < len(dates)
                else None,
                "factor_n": int(raw_counts.loc[date]),
                "n": len(pair),
                "ic": ic,
                "rank_ic": rank_ic,
                "layers": layer_values,
                "layer_spread": None
                if layer_values[0] is None or layer_values[-1] is None
                else 0.0
                if indistinguishable(layer_values[0], layer_values[-1], floor=1.0)
                else layer_values[-1] - layer_values[0],
                "reason": reason,
            }
        )
    return rows
