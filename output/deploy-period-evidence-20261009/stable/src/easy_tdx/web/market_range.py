"""Bounded, overlap-verified history retrieval; never return a silently truncated range."""

from datetime import date
from typing import Any

import pandas as pd
from fastapi import HTTPException

from easy_tdx.web.bar_snapshot import annotate_snapshot
from easy_tdx.web.market_data import checked_snapshot, load_equity_frame
from easy_tdx.web.schemas import DataFrameResponse

PAGE_SIZE = 800
MAX_PAGES = 10
VALUE_FIELDS = ("open", "high", "low", "close", "vol", "amount")


def _stamp(row: dict[str, Any]) -> str:
    return str(pd.Timestamp(row.get("datetime", row.get("date"))).isoformat())


def _same_values(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return all(a.get(key) == b.get(key) for key in VALUE_FIELDS)


async def load_equity_range(
    client: Any,
    mac_client: Any,
    market: str,
    code: str,
    category: str,
    adjust: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, "开始日期不得晚于结束日期")
    rows: dict[str, dict[str, Any]] = {}
    pages: list[dict[str, Any]] = []
    first_rows: list[dict[str, Any]] = []
    stop_reason = ""
    oldest = ""
    for page in range(MAX_PAGES):
        frame = await load_equity_frame(
            client,
            mac_client,
            market,
            code,
            category,
            page * (PAGE_SIZE - 1),
            PAGE_SIZE,
            adjust,
        )
        metadata = frame.attrs["snapshot_metadata"]
        if pages:
            for key in (
                "source",
                "actual_adjust",
                "bar_time",
                "category",
                "calendar_version",
                "adjustment_source",
            ):
                if metadata.get(key) != pages[0].get(key):
                    raise HTTPException(409, f"分页行情口径发生变化（{key}），请重新查询")
        pages.append(metadata)
        data = DataFrameResponse.from_dataframe(frame).data
        if not data:
            if page:
                # The overlap must still exist, even when no older rows remain.
                raise HTTPException(409, "分页行情重叠数据消失，请重新查询；未使用部分历史")
            stop_reason = "source_exhausted"
            break
        if page == 0:
            first_rows = data
        else:
            if _stamp(data[-1]) != oldest or not _same_values(data[-1], rows[oldest]):
                raise HTTPException(409, "分页行情时间或数值发生变化，请重新查询；未拼接不同版本")
            if len(data) > 1 and _stamp(data[0]) >= oldest:
                raise HTTPException(409, "行情分页未向历史推进，已停止查询")
        for row in data:
            stamp = _stamp(row)
            if stamp in rows and stamp != oldest:
                raise HTTPException(409, "行情分页出现非边界重复，已停止查询")
            rows[stamp] = row
        oldest = _stamp(data[0])
        # A minute page can end halfway through the first requested day.
        # Cross the date boundary before declaring that day fully retrieved.
        if start_date and oldest[:10] < start_date.isoformat():
            stop_reason = "requested_start_reached"
            break
        if len(data) < PAGE_SIZE:
            stop_reason = "source_exhausted"
            break
    if not stop_reason:
        raise HTTPException(422, "查询超过历史分页上限，请缩短日期范围；未将截断数据用于分析")

    if len(pages) > 1:
        # Validate the head again: bars may have arrived while offsets were paged,
        # or closed prices may have been revised (including adjustment revisions).
        check = await load_equity_frame(
            client,
            mac_client,
            market,
            code,
            category,
            0,
            PAGE_SIZE,
            adjust,
        )
        latest = {_stamp(r): r for r in DataFrameResponse.from_dataframe(check).data}
        if list(latest) != [_stamp(r) for r in first_rows] or any(
            row.get("is_closed") and not _same_values(row, latest[_stamp(row)])
            for row in first_rows
        ):
            raise HTTPException(409, "取数期间行情已更新，请重新查询；未混用分页快照")
        if any(
            check.attrs["snapshot_metadata"].get(k) != pages[0].get(k)
            for k in ("source", "actual_adjust", "adjustment_source")
        ):
            raise HTTPException(409, "取数期间行情来源或复权口径已更新，请重新查询")

    selected = [
        r
        for stamp, r in sorted(rows.items())
        if (not start_date or stamp[:10] >= start_date.isoformat())
        and (not end_date or stamp[:10] <= end_date.isoformat())
    ]
    base = pages[0]
    # Validate closure continuity across page boundaries before removing open
    # rows; per-page checks alone cannot detect a false→true boundary.
    checked_snapshot(
        selected,
        category,
        source=base["source"],
        requested_adjust=base["requested_adjust"],
        actual_adjust=base["actual_adjust"],
        bar_time="end",
    )
    open_count = sum(not r["is_closed"] for r in selected)
    selected = [r for r in selected if r["is_closed"]]
    result = annotate_snapshot(
        selected,
        category,
        source=base["source"],
        requested_adjust=base["requested_adjust"],
        actual_adjust=base["actual_adjust"],
        bar_time="end",
    )
    result["metadata"].update(
        adjustment_source=base.get("adjustment_source"),
        collection_started_at=base["observed_at"],
        range_start=_stamp(selected[0]) if selected else None,
        range_end=_stamp(selected[-1]) if selected else None,
        requested_start=start_date.isoformat() if start_date else None,
        requested_end=end_date.isoformat() if end_date else None,
        page_count=len(pages),
        pagination_stop=stop_reason,
        excluded_open_count=open_count,
        consistency_check="overlap_and_head_recheck" if len(pages) > 1 else "single_page",
        consistency_note=(
            "相邻页重叠及首段复核通过；" if len(pages) > 1 else "单页行情质量校验通过；"
        )
        + "上游未提供原子快照版本，不代表历史当时可得数据。",
    )
    quality = result["metadata"]["quality"]
    if quality["errors"]:
        raise HTTPException(502, "完整区间行情校验失败：" + "；".join(quality["errors"]))
    if (
        start_date
        and stop_reason == "source_exhausted"
        and (not rows or oldest[:10] > start_date.isoformat())
    ):
        quality["warnings"].append(
            "上游历史起点晚于请求起点或无数据；未补造更早行情，上市时间未独立核验"
        )
        quality["status"] = "warning"
    return result
