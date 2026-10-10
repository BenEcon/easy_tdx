"""Explicit, fixed-weight same-date ranks; never fitted or a trading portfolio."""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from easy_tdx.factor.statistics import coalesced
from easy_tdx.progress import report_progress

COMPOSITION_VERSION = "factor-composition-rank-v1"
SCORE_NAME = "composite_score"


class Component(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-zA-Z0-9_]{1,100}$")
    weight: float = Field(strict=True, ge=0.01, le=100, allow_inf_nan=False)
    direction: Literal[1, -1]

    @field_validator("direction", mode="before")
    @classmethod
    def strict_direction(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("组合方向必须显式为 1 或 -1")
        return value


class CompositionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["rank_centered"]
    components: list[Component] = Field(min_length=2, max_length=4)


def normalize_composition(value: Any, factors: list[str]) -> dict[str, Any] | None:
    if value is None:
        return None
    config = CompositionConfig.model_validate(value).model_dump()
    names = [c["name"] for c in config["components"]]
    if len(set(names)) != len(names) or set(names) != set(factors):
        raise ValueError("组合必须为全部已选因子各配置一次权重与方向；不得遗漏、重复或增加因子")
    # Keep the selected order stable in evidence and UI, not incoming dict order.
    config["components"] = sorted(config["components"], key=lambda c: factors.index(c["name"]))
    return config


def compose_scores(
    matrices: dict[str, pd.DataFrame], template: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Complete intersection, >=5 assets; missing components never renormalized."""
    components = config["components"]
    total = math.fsum(c["weight"] for c in components)
    effective = [{**c, "normalized_weight": c["weight"] / total} for c in components]
    scores = pd.DataFrame(np.nan, index=template.index, columns=template.columns)
    unavailable = [c["name"] for c in components if c["name"] not in matrices]
    reason = "组成因子未能计算：" + "、".join(unavailable) if unavailable else None
    coverage = []
    latest = []
    report_progress("factor_composition", 0, len(template))
    for position, date in enumerate(template.index, 1):
        raw = pd.DataFrame(
            {
                c["name"]: matrices[c["name"]].loc[date]
                if c["name"] in matrices
                else pd.Series(np.nan, index=template.columns)
                for c in components
            }
        )
        complete = raw.notna().all(axis=1)
        n = int(complete.sum())
        day_reason = reason or ("完整组成因子的标的不足 5 只" if n < 5 else None)
        ranks = pd.DataFrame(np.nan, index=template.columns, columns=raw.columns)
        constant = []
        if n >= 5 and not reason:
            for c in components:
                values = coalesced(raw.loc[complete, c["name"]])
                if values.nunique() == 1:
                    constant.append(c["name"])
                ranks.loc[complete, c["name"]] = (
                    2 * (values.rank(method="average") - 1) / (n - 1) - 1
                )
            scores.loc[date, complete] = sum(
                ranks.loc[complete, c["name"]] * c["direction"] * c["normalized_weight"]
                for c in effective
            )
        coverage.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "complete_assets": n,
                "scored_assets": int(scores.loc[date].notna().sum()),
                "constant_components": constant,
                "reason": day_reason,
            }
        )
        if position == len(template):
            for symbol in template.columns:
                values = []
                for c in effective:
                    rv, rank = raw.loc[symbol, c["name"]], ranks.loc[symbol, c["name"]]
                    values.append(
                        {
                            "name": c["name"],
                            "raw": float(rv) if pd.notna(rv) else None,
                            "rank": float(rank) if pd.notna(rank) else None,
                            "contribution": (
                                0.0
                                if rank == 0
                                else float(rank * c["direction"] * c["normalized_weight"])
                            )
                            if pd.notna(rank)
                            else None,
                        }
                    )
                score = scores.loc[date, symbol]
                latest.append(
                    {
                        "code": symbol,
                        "score": float(score) if pd.notna(score) else None,
                        "components": values,
                        "reason": day_reason
                        or ("本标的组成因子缺失" if not complete.loc[symbol] else None),
                    }
                )
        report_progress("factor_composition", position, len(template))
    return scores, {
        "version": COMPOSITION_VERSION,
        "config": config,
        "effective_components": effective,
        "score_name": SCORE_NAME,
        "symbols": list(template.columns),
        "scores": [
            {
                "date": d.strftime("%Y-%m-%d"),
                "values": [float(v) if pd.notna(v) else None for v in scores.loc[d]],
            }
            for d in template.index
        ],
        "coverage": coverage,
        "latest": latest,
        "error": reason,
        "trade_eligible": False,
        "policy": {
            "pool": "same_date_complete_intersection",
            "minimum_assets": 5,
            "missing": "no_imputation_no_weight_renormalization",
            "fit": "fixed_user_weights_no_return_fitting",
        },
        "limitations": [
            "各因子在同日、全部组成因子齐全的标的交集内取平均并列排名，线性映射至 [-1,1]。",
            "正方向保留排名，负方向反向；权重除以总和。方向和权重由用户指定，不按收益自动拟合。",
            "不足 5 只不评分，缺失标的保留为空；常数组成因子得 0，仍保留原权重，不重新分配。",
            "组合使用原始因子排名，不套用单因子预处理选项；没有行业／市值中性化。",
            "这是固定配置研究评分与回顾性检验，不是交易持仓权重或可交易净值。",
        ],
    }
