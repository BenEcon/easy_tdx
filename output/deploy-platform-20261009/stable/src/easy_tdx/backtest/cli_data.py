"""Synchronous CLI research input using the same calendar/quality contract as Web."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from easy_tdx.backtest.performance_sampling import performance_frame
from easy_tdx.backtest.reporting import clean_json
from easy_tdx.mac.enums import Adjust, Period
from easy_tdx.web.bar_snapshot import annotate_snapshot

PERIOD_CATEGORIES = {
    Period.MIN_1: "MIN_1",
    Period.MIN_5: "MIN_5",
    Period.MIN_15: "MIN_15",
    Period.MIN_30: "MIN_30",
    Period.MIN_60: "MIN_60",
    Period.DAILY: "DAY",
    Period.WEEKLY: "WEEK",
    Period.MONTHLY: "MONTH",
    Period.QUARTERLY: "SEASON",
    Period.YEARLY: "YEAR",
}


def load_cli_frame(
    client: Any,
    market: int,
    code: str,
    period: Period,
    adjust: Adjust,
    count: int,
    *,
    now: datetime | None = None,
) -> pd.DataFrame:
    """No silent adjustment fallback, open bars, or guessed custom-period annualization.

    MAC's original protocol labels are used unchanged, matching Web's native
    research path. They are actual close observations, despite the low-level
    API naming the unshifted option ``start`` for backwards compatibility.
    """
    if period not in PERIOD_CATEGORIES:
        raise ValueError(
            "回测不支持未明确倍数的自定义周期或秒线；请选择具体分钟／日／周／月／季／年"
        )
    if count < 2:
        raise ValueError("回测至少需要 2 根已收盘 K 线")
    frame = client.get_stock_kline(
        market, code, period=period, start=0, count=count, adjust=adjust, bar_time="start"
    )
    actual = frame.attrs.get("actual_adjust", adjust.name)
    if actual != adjust.name:
        raise ValueError(f"复权计算未成功：请求 {adjust.name}，实际 {actual}；已停止回测")
    # No Pydantic/FastAPI dependency: CLI must work without the optional Web extra.
    records = clean_json(frame.to_dict(orient="records"))
    args = dict(source="MAC", requested_adjust=adjust.name, actual_adjust=actual, bar_time="end")
    category = PERIOD_CATEGORIES[period]
    snapshot = annotate_snapshot(records, category, now=now, **args)
    quality = snapshot["metadata"]["quality"]
    if quality["errors"]:
        raise ValueError("行情质量检查失败：" + "；".join(quality["errors"]))
    selected = [row for row in snapshot["data"] if row["is_closed"]]
    if len(selected) < 2:
        raise ValueError("有效已收盘行情不足 2 根，回测未执行")
    measured = annotate_snapshot(
        selected,
        category,
        now=datetime.fromisoformat(snapshot["metadata"]["observed_at"]),
        **args,
    )
    result = pd.DataFrame(selected)
    if "datetime" not in result:
        result["datetime"] = result["date"]
    result["datetime"] = pd.to_datetime(result["datetime"], errors="raise")
    metadata = measured["metadata"]
    metadata.update(
        source_fingerprint=snapshot["metadata"]["data_fingerprint"],
        collection_quality=quality,
        excluded_open_count=len(records) - len(selected),
        adjustment_source=frame.attrs.get("adjustment_source", "server"),
    )
    result.attrs["snapshot_metadata"] = metadata
    return performance_frame(result, category)
