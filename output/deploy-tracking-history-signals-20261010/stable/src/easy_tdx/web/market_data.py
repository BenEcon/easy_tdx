"""One raw equity feed contract for charts, analysis, scanners and backtests.

Protocol clients retain their legacy bar_time API. Native exchange minute labels
are right endpoints; web consumers must not add an extra bar to these labels.
"""

from typing import Any

import pandas as pd
from fastapi import HTTPException

from easy_tdx.web.bar_snapshot import annotate_snapshot
from easy_tdx.web.convert import (
    adjust_from_str,
    category_from_str,
    market_from_str,
    market_value_from_str,
    period_times_from_category,
)
from easy_tdx.web.schemas import DataFrameResponse


def checked_snapshot(records: list[dict[str, Any]], category: str, **kwargs: Any) -> dict[str, Any]:
    """Translate bad upstream data consistently at every web feed entrance."""
    try:
        snapshot = annotate_snapshot(records, category, **kwargs)
    except (ValueError, TypeError) as exc:
        raise HTTPException(502, f"行情质量检查失败：{exc}") from exc
    if snapshot["metadata"]["quality"]["errors"]:
        raise HTTPException(
            502, "行情质量检查失败：" + "；".join(snapshot["metadata"]["quality"]["errors"])
        )
    return snapshot


async def load_equity_frame(
    client: Any,
    mac_client: Any | None,
    market: str,
    code: str,
    category: str,
    start: int,
    count: int,
    adjust: str,
    *,
    bar_time: str = "native",
    require_adjust: bool = True,
) -> pd.DataFrame:
    category, adjust = category.upper(), adjust.upper()
    if bar_time not in ("native", "start", "end"):
        raise HTTPException(422, "bar_time 须为 native、start 或 end")
    adjustment = adjust_from_str(adjust)
    adjust = adjustment.name
    cat = category_from_str("MIN_60" if category == "MIN_120" else category)
    use_mac = mac_client is not None and hasattr(mac_client, "get_stock_kline")
    if category == "MIN_120" and not use_mac:
        raise HTTPException(503, "120 分钟行情需要 MAC 行情服务；未用其他周期冒充")
    if not use_mac and adjust != "NONE" and require_adjust:
        raise HTTPException(
            503, f"{adjust} 复权服务不可用；未使用不复权行情替代。可稍后重试或明确选择不复权"
        )
    label = "start" if bar_time == "native" else bar_time
    if use_mac and mac_client is not None:
        period, times = period_times_from_category(cat)
        if category == "MIN_120":
            from easy_tdx.mac.enums import Period

            period, times = Period.MINS, 24
        df = await mac_client.get_stock_kline(
            market_value_from_str(market),
            code,
            period,
            start,
            count,
            times,
            adjust=adjustment,
            bar_time=label,
        )
    else:
        df = await client.get_security_bars(
            market_from_str(market), code, cat, start, count, bar_time=label
        )
    actual_adjust = df.attrs.get("actual_adjust", adjust if use_mac else "NONE")
    if require_adjust and actual_adjust != adjust:
        raise HTTPException(
            503, f"复权计算未成功：请求 {adjust}，实际 {actual_adjust}；已停止分析，未替换口径"
        )
    snapshot = checked_snapshot(
        DataFrameResponse.from_dataframe(df).data,
        category,
        source="MAC" if use_mac else "TDX_STANDARD",
        requested_adjust=adjust,
        actual_adjust=actual_adjust,
        bar_time="end" if bar_time == "native" else bar_time,
    )
    result = df.copy()
    if len(result):
        result["is_closed"] = [r["is_closed"] for r in snapshot["data"]]
        result["period_end"] = [r["period_end"] for r in snapshot["data"]]
    result.attrs["snapshot_metadata"] = snapshot["metadata"]
    result.attrs["snapshot_metadata"]["adjustment_source"] = df.attrs.get(
        "adjustment_source", "server"
    )
    return result


def closed_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Confirmed studies/backtests never consume a current unfinished candle."""
    if "is_closed" not in frame:
        return frame.copy()
    flags = frame.is_closed.tolist()
    if any(not isinstance(flag, bool) for flag in flags):
        raise ValueError("收盘标记必须为布尔值")
    if any(a is False and b is True for a, b in zip(flags, flags[1:])):
        raise ValueError("收盘标记存在历史断层，未删除后拼接行情")
    result = frame.loc[frame.is_closed].copy().reset_index(drop=True)
    metadata = frame.attrs.get("snapshot_metadata")
    # Older in-process callers may supply only a timestamp convention. Preserve
    # that convention without inventing source/adjustment provenance for them.
    required = {
        "category",
        "source",
        "requested_adjust",
        "actual_adjust",
        "bar_time",
        "observed_at",
        "data_fingerprint",
    }
    if metadata and required <= metadata.keys():
        snapshot = checked_snapshot(
            DataFrameResponse.from_dataframe(result).data,
            metadata["category"],
            source=metadata["source"],
            requested_adjust=metadata["requested_adjust"],
            actual_adjust=metadata["actual_adjust"],
            bar_time=metadata["bar_time"],
            now=pd.Timestamp(metadata["observed_at"]).to_pydatetime(),
        )
        result.attrs["snapshot_metadata"] = {
            **metadata,
            **snapshot["metadata"],
            "source_fingerprint": metadata["data_fingerprint"],
            "excluded_open_count": len(frame) - len(result),
            "input_count": len(result),
        }
    return result
