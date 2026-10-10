"""Recompute saved chart indicator instances without network/default substitution."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    model_validator,
)

from easy_tdx.indicator import compute_indicators, list_indicators


class SavedAverage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: StrictInt = Field(ge=1, le=8000)
    enabled: StrictBool


class SavedIndicator(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(min_length=1, max_length=30)
    params: dict[str, StrictInt | StrictFloat]

    @model_validator(mode="after")
    def complete_parameters(self) -> SavedIndicator:
        specs = {str(row["name"]).lower(): row for row in list_indicators()}
        if self.type in {"none", "volume"}:
            expected: dict[str, Any] = {}
        elif self.type in specs:
            defaults = specs[self.type]["default_params"]
            if not isinstance(defaults, dict):
                raise ValueError("当前指标注册信息无效")
            expected = defaults
        else:
            raise ValueError("原档指标不受当前版本支持，不静默替换")
        if self.params.keys() != expected.keys():
            raise ValueError("原档指标参数不完整或包含未知参数，不补用默认值")
        for key, value in self.params.items():
            if not np.isfinite(value) or value <= 0:
                raise ValueError("指标参数必须为有限正数")
            if self.type == "sar":
                if value > 1:
                    raise ValueError("SAR 加速参数不得超过 1")
            elif self.type == "boll" and key == "P":
                if value > 100:
                    raise ValueError("布林带倍数不得超过 100")
            elif value > 8000 or int(value) != value:
                raise ValueError("指标周期必须是 1—8000 的整数")
            else:
                self.params[key] = int(value)
        if self.type == "sar" and self.params["AF_STEP"] > self.params["AF_MAX"]:
            raise ValueError("SAR 步长不得大于上限")
        if self.type == "macd" and self.params["SHORT"] >= self.params["LONG"]:
            raise ValueError("MACD 短周期必须小于长周期")
        return self


class SavedChartIndicators(BaseModel):
    model_config = ConfigDict(extra="forbid")
    averages: list[SavedAverage] = Field(max_length=30)
    indicators: list[SavedIndicator] = Field(max_length=8)

    @model_validator(mode="after")
    def distinct_averages(self) -> SavedChartIndicators:
        if len({row.period for row in self.averages}) != len(self.averages):
            raise ValueError("均线周期重复")
        return self


def recompute_chart_indicators(
    bars: list[dict[str, Any]], settings: SavedChartIndicators
) -> dict[str, Any]:
    frame = pd.DataFrame(bars).drop(columns=["datetime", "date"], errors="ignore")
    close = [float(row["close"]) for row in bars]
    volume = [float(row["vol"]) for row in bars]
    averages = [
        {
            **ma.model_dump(),
            "values": [
                None if i + 1 < ma.period else sum(close[i + 1 - ma.period : i + 1]) / ma.period
                for i in range(len(close))
            ],
        }
        for ma in settings.averages
    ]
    indicators = []
    for item in settings.indicators:
        if item.type == "none":
            rows: list[dict[str, Any]] = [{} for _ in bars]
        elif item.type == "volume":
            rows = [{"VOL": value} for value in volume]
            for period in (5, 10):
                total = 0.0
                for i, value in enumerate(volume):
                    total += value
                    if i >= period:
                        total -= volume[i - period]
                    rows[i][f"MAVOL{period}"] = total / period if i >= period - 1 else None
        else:
            values = compute_indicators(
                frame,
                [item.type],
                {item.type.upper(): item.params},
                keep_ohlcv=False,
            )
            # FK is explicitly a boolean signal in the engine, plotted as 0/1.
            if item.type == "fk":
                values["FK"] = values["FK"].astype(int)
            values = values.replace([np.inf, -np.inf], np.nan)
            rows = values.astype(object).where(pd.notna(values), None).to_dict(orient="records")
        indicators.append({**item.model_dump(), "rows": rows})
    return {"averages": averages, "indicators": indicators}
