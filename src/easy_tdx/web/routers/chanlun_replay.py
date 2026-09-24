"""Deterministic prefix analysis of a supplied, bounded market-data snapshot."""
from datetime import datetime
from typing import Literal

import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from easy_tdx.chanlun import ChanlunAnalyser

router = APIRouter(tags=["chanlun"])


class ReplayBar(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    vol: float = Field(default=0, ge=0)
    amount: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def valid_candle(self):
        if self.datetime.tzinfo is not None:
            raise ValueError("请使用交易所本地时间，不附带时区")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("K 线高低价必须覆盖开盘和收盘价")
        return self


class ReplaySeries(BaseModel):
    code: str = Field(min_length=1, max_length=24)
    bars: list[ReplayBar] = Field(min_length=1, max_length=800)

    @model_validator(mode="after")
    def chronological(self):
        if any(a.datetime >= b.datetime for a, b in zip(self.bars, self.bars[1:])):
            raise ValueError("K 线时间必须严格递增，不可重复")
        return self


class ReplayRequest(ReplaySeries):
    category: Literal["DAY", "WEEK", "MONTH", "YEAR", "MIN_1", "MIN_5",
                      "MIN_15", "MIN_30", "MIN_60"] = "DAY"
    visible_count: int = Field(ge=1, le=800)

    @model_validator(mode="after")
    def valid_snapshot(self):
        if self.visible_count > len(self.bars):
            raise ValueError("回放位置超过快照长度")
        return self


@router.post("/chanlun/replay")
def replay_snapshot(req: ReplayRequest) -> dict:
    # Deliberately slice before all inclusion, structure and MACD calculations.
    frame = pd.DataFrame([bar.model_dump() for bar in req.bars[:req.visible_count]])
    frequency = (req.category.removeprefix("MIN_") + "min"
                 if req.category.startswith("MIN_") else req.category.lower())
    result = ChanlunAnalyser(code=req.code, frequency=frequency).process_klines(frame).to_dict()
    result["replay"] = {
        "visible_count": req.visible_count, "total_count": len(req.bars),
        "as_of": req.bars[req.visible_count - 1].datetime.isoformat(sep=" "),
        "mode": "snapshot_prefix", "historical_data_vintage": False,
    }
    return result


class ComparisonReplayRequest(BaseModel):
    stock: ReplayRequest
    industry: ReplaySeries


@router.post("/chanlun/replay/compare")
def replay_comparison(req: ComparisonReplayRequest) -> dict:
    """Use the stock cutoff's timestamp, never its row count, for the industry."""
    cutoff = req.stock.bars[req.stock.visible_count - 1].datetime
    visible = [bar for bar in req.industry.bars if bar.datetime <= cutoff]
    industry = None
    if visible:
        result = replay_snapshot(ReplayRequest(
            code=req.industry.code, category=req.stock.category,
            bars=req.industry.bars, visible_count=len(visible),
        ))
        industry = {"bars": [bar.model_dump(mode="json") for bar in visible], "result": result}
    return {
        "stock": replay_snapshot(req.stock), "industry": industry,
        "alignment": {
            "as_of": cutoff.isoformat(sep=" "),
            "industry_as_of": visible[-1].datetime.isoformat(sep=" ") if visible else None,
            "status": "unavailable" if not visible else (
                "aligned" if visible[-1].datetime == cutoff else "earlier"),
        },
    }
