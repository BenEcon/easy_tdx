"""Chronological diagnostics with frozen parameters, not an estimator training API."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from easy_tdx.computation import computation_checkpoint
from easy_tdx.factor.report_summary import summarize_rows

VALIDATION_VERSION = "factor-time-validation-v1"
PURGE_REASON = "远期标签超出本区间，已剔除；不使用下一区间收益"


class HoldoutConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["holdout"]
    train_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    validation_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def boundaries(self) -> HoldoutConfig:
        if date.fromisoformat(self.train_end) >= date.fromisoformat(self.validation_end):
            raise ValueError("训练截止日必须早于验证截止日")
        return self


class WalkForwardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["walk_forward"]
    training: Literal["expanding", "rolling"]
    train_bars: int = Field(ge=20, le=700, strict=True)
    validation_bars: int = Field(ge=10, le=300, strict=True)
    test_bars: int = Field(ge=10, le=300, strict=True)


ValidationConfig = Annotated[HoldoutConfig | WalkForwardConfig, Field(discriminator="mode")]


def normalize_validation(value: dict[str, Any] | None) -> dict[str, Any] | None:
    return (
        TypeAdapter(ValidationConfig).validate_python(value).model_dump()
        if value is not None
        else None
    )


def validation_plan(
    dates: pd.DatetimeIndex,
    horizon: int,
    config: dict[str, Any] | None,
) -> list[list[tuple[str, int, int]]]:
    """Half-open positional segments on the explicit union observation calendar."""
    if config is None:
        return []
    n = len(dates)
    if n > 800:
        raise ValueError(f"合并观测日 {n} 个，超过时间检验 800 根上限；未截断或缩小股票池")
    if config["mode"] == "holdout":
        i = int(dates.searchsorted(pd.Timestamp(config["train_end"]), side="right"))
        j = int(dates.searchsorted(pd.Timestamp(config["validation_end"]), side="right"))
        if min(i, j - i, n - j) <= horizon:
            raise ValueError("训练、验证、测试区间均须长于远期窗口；请按实际行情日期调整分界")
        return [[("train", 0, i), ("validation", i, j), ("test", j, n)]]
    train, valid, test = (config[k] for k in ("train_bars", "validation_bars", "test_bars"))
    if min(train, valid, test) <= horizon:
        raise ValueError("滚动各区间根数均须长于远期窗口")
    if n < train + valid + test:
        raise ValueError(
            f"滚动检验至少需要 {train + valid + test} 个观测日，实际仅 {n} 个；未缩短配置"
        )
    folds = []
    for end_train in range(train, n - valid, test):
        start = end_train - train if config["training"] == "rolling" else 0
        folds.append(
            [
                ("train", start, end_train),
                ("validation", end_train, end_train + valid),
                ("test", end_train + valid, min(end_train + valid + test, n)),
            ]
        )
    return folds


def time_validation(
    reports: list[dict[str, Any]],
    dates: pd.DatetimeIndex,
    assets: int,
    horizon: int,
    config: dict[str, Any],
    plan: list[list[tuple[str, int, int]]],
) -> dict[str, Any]:
    test_rows: dict[str, list[dict[str, Any]]] = {r["name"]: [] for r in reports}
    folds = []
    for fold_id, segments in enumerate(plan, 1):
        computation_checkpoint()
        phases = []
        for phase, begin, end in segments:
            summaries = []
            for report in reports:
                rows = []
                for position in range(begin, end):
                    row = dict(report["daily"][position])
                    row["fold"] = fold_id
                    if position + horizon >= end:
                        row.update(
                            n=0,
                            ic=None,
                            rank_ic=None,
                            layers=[None] * len(row["layers"]),
                            layer_spread=None,
                            reason=PURGE_REASON,
                        )
                    rows.append(row)
                coverage = sum(row["factor_n"] for row in rows) / (assets * len(rows))
                summary = summarize_rows(report["name"], coverage, rows)
                summaries.append({k: v for k, v in summary.items() if k != "daily"})
                if phase == "test":
                    test_rows[report["name"]].extend(rows)
            phases.append(
                {
                    "phase": phase,
                    "start": dates[begin].strftime("%Y-%m-%d"),
                    "end": dates[end - 1].strftime("%Y-%m-%d"),
                    "date_count": end - begin,
                    "purged_dates": min(horizon, end - begin),
                    "label_eligible_dates": max(0, end - begin - horizon),
                    "partial": phase == "test"
                    and config["mode"] == "walk_forward"
                    and end - begin < config["test_bars"],
                    "reports": summaries,
                }
            )
        folds.append({"id": fold_id, "phases": phases})
    return {
        "version": VALIDATION_VERSION,
        "config": config,
        "folds": folds,
        "test_reports": [
            summarize_rows(name, sum(r["factor_n"] for r in rows) / (assets * len(rows)), rows)
            for name, rows in test_rows.items()
        ],
        "policy": {
            "fitting": "none_fixed_requested_parameters",
            "preprocessing": "same_date_cross_section_only",
            "labels": "signal_and_forward_endpoint_in_same_phase",
            "features": "past_input_allowed_for_warmup_no_future",
            "test_windows": "non_overlapping_step_equals_test_bars_include_partial_tail",
            "aggregation": "pooled_daily_test_observations_not_mean_of_fold_ics",
        },
        "limitations": [
            "本功能按时间隔离固定参数因子，不训练模型、不自动调参、择优或反转因子。训练区间仅供研究选择参数。",
            "训练／验证／测试分别剔除跨边界的远期标签；同一区间内多日收益仍可能重叠。滚动测试不重叠，末尾不足一窗仍展示并标记。",
            "因子预热可使用区间之前的行情；去极值和标准化只使用当日截面，不拟合全时期参数。"
            "当前股票池和复权快照仍非历史 PIT。",
            "反复查看测试结果再修改参数会污染样本外评估；没有独立预注册或封存机制，不声称独立盲测。分层收益不是可交易净值。",
        ],
    }
