"""Common-cutoff multi-frequency observations on supplied frozen snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from easy_tdx.chanlun.observations import observe
from easy_tdx.chanlun.research_context import RULE_VERSION
from easy_tdx.web.bar_snapshot import period_end
from easy_tdx.web.resource_admission import BoundedComputeRoute
from easy_tdx.web.routers.chanlun_replay import ReplaySeries

router = APIRouter(tags=["chanlun"], route_class=BoundedComputeRoute)


class StudySeries(ReplaySeries):
    category: Literal[
        "MIN_1", "MIN_5", "MIN_15", "MIN_30", "MIN_60", "MIN_120", "DAY", "WEEK", "MONTH"
    ]
    bar_time: Literal["start", "end"] = "start"


class StudyRequest(BaseModel):
    as_of: datetime
    series: list[StudySeries] = Field(min_length=1, max_length=9)
    volume_multiple: float = Field(default=2, ge=1, le=10)
    squeeze_quantile: float = Field(default=0.2, gt=0, lt=1)
    ma_periods: list[int] = Field(
        default_factory=lambda: [5, 10, 20, 30, 60, 120, 250], min_length=1, max_length=12
    )
    window_bars: int = Field(default=20, ge=3, le=800)
    window_start: datetime | None = None
    window_end: datetime | None = None

    @model_validator(mode="after")
    def valid_snapshot(self) -> StudyRequest:
        if self.as_of.tzinfo is not None:
            raise ValueError("共同截止时刻使用交易所本地时间")
        if len({s.code for s in self.series}) != 1 or len({s.category for s in self.series}) != len(
            self.series
        ):
            raise ValueError("多周期须为同一标的，周期不可重复")
        if any(p < 1 or p > 800 for p in self.ma_periods):
            raise ValueError("均线参数须为 1 至 800 根")
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("指定区间必须同时提供起止时间")
        if self.window_start is not None and self.window_end is not None:
            if self.window_start.tzinfo or self.window_end.tzinfo:
                raise ValueError("研究区间使用交易所本地时间")
            if not self.window_start <= self.window_end <= self.as_of:
                raise ValueError("研究起止时间须有序，且不得超过共同截止")
        return self


@router.post("/chanlun/observations")
def observations(req: StudyRequest) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    frames: dict[str, pd.DataFrame] = {}
    cutoff = req.window_end or req.as_of
    for source in req.series:
        # Never use the final OHLC of a higher-period candle spanning the cutoff.
        eligible = []
        for bar in source.bars:
            if (
                not bar.is_closed
                or period_end(bar.datetime, source.category, source.bar_time) > cutoff
            ):
                break
            eligible.append(bar)
        if not eligible:
            rows.append(
                {
                    "category": source.category,
                    "error": "共同截止时刻前无完整 K 线；未使用跨越截止点的整根行情",
                }
            )
            continue
        frame = pd.DataFrame([bar.model_dump() for bar in eligible])
        row = observe(
            frame,
            source.category,
            volume_multiple=req.volume_multiple,
            squeeze_quantile=req.squeeze_quantile,
            ma_periods=req.ma_periods,
            window_bars=req.window_bars,
            window_start=req.window_start,
        )
        row["excluded_bars"] = len(source.bars) - len(eligible)
        row["last_closed_at"] = period_end(
            eligible[-1].datetime, source.category, source.bar_time
        ).isoformat(sep=" ")
        row["bar_time"] = source.bar_time
        for point in row.get("buy_sell_points", []):
            point["known_at"] = period_end(
                datetime.fromisoformat(point["confirmed_date"]), source.category, source.bar_time
            ).isoformat(sep=" ")
        for event in row.get("events", []):
            event["known_at"] = period_end(
                datetime.fromisoformat(event["date"]), source.category, source.bar_time
            ).isoformat(sep=" ")
        direction_state = row.get("direction_observation", {})
        if direction_state.get("known_date"):
            direction_state["known_date"] = period_end(
                datetime.fromisoformat(direction_state["known_date"]),
                source.category,
                source.bar_time,
            ).isoformat(sep=" ")
        for event in direction_state.get("history", []):
            # A prefix change is only observable at its last candle's close.
            # Preserve chart anchors separately; never move the price extremum.
            event["bar_date"] = event["date"]
            event["date"] = period_end(
                datetime.fromisoformat(event["bar_date"]), source.category, source.bar_time
            ).isoformat(sep=" ")
            if event.get("known_date"):
                event["known_bar_date"] = event["known_date"]
                event["known_date"] = period_end(
                    datetime.fromisoformat(event["known_bar_date"]),
                    source.category,
                    source.bar_time,
                ).isoformat(sep=" ")
        frames[source.category] = frame
        rows.append(row)
    conflicts = []
    rank = {
        "MIN_1": 1,
        "MIN_5": 5,
        "MIN_15": 15,
        "MIN_30": 30,
        "MIN_60": 60,
        "MIN_120": 120,
        "DAY": 240,
        "WEEK": 1200,
        "MONTH": 4800,
    }
    ordered = sorted((r for r in rows if "error" not in r), key=lambda r: rank[r["category"]])
    names = {"DAY": "日线", "WEEK": "周线", "MONTH": "月线"}

    def label(category: str) -> str:
        return names.get(category, category.removeprefix("MIN_") + " 分钟")

    for small, large in zip(ordered, ordered[1:]):
        # Only report a divergence on the last completed bar or confirmed there;
        # old historical markers must not trigger a new current conflict.
        tops = [
            d
            for d in small["divergences"]
            if d["direction"] == "up" and small["last_date"] in (d["date"], d["confirmed_date"])
        ]
        if (
            tops
            and large["above_ma10"]
            and large["pairs"]["macd"]["fast"] > large["pairs"]["macd"]["slow"]
        ):
            conflicts.append(
                f"{label(small['category'])} 出现局部顶背离，"
                f"{label(large['category'])} 仍位于 MA10 上方且 DIF 高于 DEA；"
                "不能直接等同于大周期反转"
            )
        bottoms = [
            d
            for d in small["divergences"]
            if d["direction"] == "down" and small["last_date"] in (d["date"], d["confirmed_date"])
        ]
        if (
            bottoms
            and large["above_ma10"] is False
            and large["price"] < large["ma10"]
            and large["pairs"]["macd"]["fast"] < large["pairs"]["macd"]["slow"]
        ):
            conflicts.append(
                f"{label(small['category'])} 出现局部底背离，"
                f"{label(large['category'])} 仍位于 MA10 下方且 DIF 低于 DEA；"
                "不能直接等同于大周期反转"
            )
    # Independent lower-period support, never a vote and never a strict-pen gate.
    for i, large in enumerate(ordered):
        observation = large.get("direction_observation")
        if not observation:
            continue
        auxiliary = []
        for small in ordered[:i]:
            child = small.get("direction_observation", {})
            anchor = observation.get("anchor_date")
            frame = frames[small["category"]]
            pen = child.get("strict")
            covered = bool(anchor and str(frame.datetime.iloc[0]) <= anchor)
            recent_pen = bool(pen and anchor and pen["start_date"] >= anchor)
            movement = (
                frame[pd.to_datetime(frame.datetime) >= pd.Timestamp(anchor)]
                if anchor
                else frame.iloc[:0]
            )
            price = observation.get("anchor_price")
            broken = bool(
                not movement.empty
                and price is not None
                and (
                    movement.low.min() < price
                    if observation["direction"] == "up"
                    else movement.high.max() > price
                )
            )
            supports = (
                covered
                and recent_pen
                and not broken
                and observation["state"] not in ("invalidated", "insufficient")
                and pen["direction"] == observation["direction"]
            )
            auxiliary.append(
                {
                    "category": small["category"],
                    "covered": covered,
                    "supports": supports,
                    "description": "未覆盖本级观察端点，不能验证"
                    if not covered
                    else "本级观察极值已被小周期价格破坏"
                    if broken
                    else "观察端点后形成同向严格笔；仅为辅助，末笔仍可延伸"
                    if supports
                    else "尚无观察端点后的同向严格笔支持",
                    "last_closed_at": small["last_closed_at"],
                    "axis": small.get("axis"),
                    "recent": small.get("recent", {}).get("structure"),
                    "tail": child.get("description"),
                    "coordination": small.get("coordination", {}).get("summary"),
                    "pen": pen if recent_pen else None,
                    "divergences": [
                        d for d in small.get("divergences", []) if anchor and d["date"] >= anchor
                    ],
                }
            )
        observation["auxiliary"] = auxiliary
    return {
        "as_of": cutoff.isoformat(sep=" "),
        "rows": rows,
        "conflicts": conflicts,
        "rule_version": RULE_VERSION + "+signal-evidence-20261010",
        "eligible_for_trading": False,
        "parameters": {
            "macd": [12, 26, 9],
            "boll": [20, 2],
            "volume_multiple": req.volume_multiple,
            "squeeze_quantile": req.squeeze_quantile,
            "ma_periods": sorted(set(req.ma_periods)),
            "window_bars": req.window_bars,
            "window_start": req.window_start,
            "window_end": req.window_end,
        },
        "policy": (
            "仅使用共同截止点前完整 K 线；结构层级不等于图表周期；"
            "不按周期多数投票；过轴先后只记录事实，不作强制条件"
        ),
    }
