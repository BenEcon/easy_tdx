"""板块分析路由：板块列表、成分、归属、摘要、涨幅排名、N日涨幅。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from easy_tdx.web.convert import (
    board_sort_from_str,
    board_type_from_str,
    market_value_from_str,
    sort_order_from_str,
    sort_type_from_str,
)
from easy_tdx.web.deps import get_mac_client
from easy_tdx.web.schemas import DataFrameResponse, DictResponse

router = APIRouter(tags=["board-mac"])


def _df_resp(df: Any) -> DataFrameResponse:
    return DataFrameResponse.from_dataframe(df)


@router.get("/board-mac/list", response_model=DataFrameResponse)
async def board_list(
    board_type: str = Query("ALL", description="板块类型: ALL/HY/HY2/GN/FG/DQ"),
    count: int = Query(500, ge=1, le=50000),
    sort_column: str = Query(
        "CHANGE_PCT",
        description=(
            "排序键: CHANGE_PCT/SPEED/CHANGE_3D/CHANGE_5D/CHANGE_10D/"
            "CHANGE_20D/CHANGE_60D/YTD；sort_value 列即该指标值"
            "（CHANGE_PCT 时恒 0，涨跌幅=price/pre_close-1）"
        ),
    ),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取板块列表（默认按涨跌幅降序；要取涨速传 sort_column=SPEED）。"""
    df = await client.get_board_list(
        board_type=board_type_from_str(board_type),
        count=count,
        sort_column=board_sort_from_str(sort_column),
    )
    return _df_resp(df)


@router.get("/board-mac/members", response_model=DataFrameResponse)
async def board_members(
    board_symbol: str = Query(..., description="板块代码，如 881001"),
    count: int = Query(100, ge=1, le=100000),
    sort_type: str = Query("CHANGE_PCT", description="排序字段"),
    sort_order: str = Query("DESC", description="排序方向: ASC/DESC"),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取板块成分股。"""
    df = await client.get_board_members(
        board_symbol=board_symbol,
        count=count,
        sort_type=sort_type_from_str(sort_type),
        sort_order=sort_order_from_str(sort_order),
    )
    return _df_resp(df)


@router.get("/board-mac/belong", response_model=DataFrameResponse)
async def board_belong(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6, description="6位股票代码"),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取股票所属板块列表。"""
    df = await client.get_belong_board(market=market_value_from_str(market), code=code)
    return _df_resp(df)


@router.get("/board-mac/summary", response_model=DictResponse)
async def board_summary(
    board_symbol: str = Query(..., description="板块代码，如 881001"),
    sort_type: str = Query("CHANGE_PCT", description="排序字段"),
    sort_order: str = Query("DESC", description="排序方向: ASC/DESC"),
    client: Any = Depends(get_mac_client),
) -> DictResponse:
    """获取板块摘要信息（含成分股资金流向）。"""
    result = await client.get_board_summary(
        board_symbol=board_symbol,
        sort_type=sort_type_from_str(sort_type),
        sort_order=sort_order_from_str(sort_order),
    )
    return DictResponse.from_dict(result)


@router.get("/board-mac/ranking", response_model=DataFrameResponse)
async def board_ranking(
    board_type: str = Query("HY", description="板块类型: HY/HY2/GN/FG/DQ"),
    top_n: int = Query(10, ge=1, le=200),
    sort_by: str = Query("change_pct", description="排序字段名"),
    ascending: bool = Query(False, description="是否升序"),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取板块涨幅排名。"""
    df = await client.get_board_ranking(
        board_type=board_type_from_str(board_type),
        top_n=top_n,
        sort_by=sort_by,
        ascending=ascending,
    )
    return _df_resp(df)


@router.get("/board-mac/change-ranking", response_model=DataFrameResponse)
async def board_change_ranking(
    board_type: str = Query("HY", description="板块类型: HY/HY2/GN/FG/DQ"),
    days: int = Query(20, ge=1, le=250, description="统计天数"),
    top_n: int = Query(10, ge=1, le=200),
    target_date: int | None = Query(None, description="目标日期，如 20250101"),
    ascending: bool = Query(False, description="是否升序"),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取板块 N 日涨幅排名。"""
    df = await client.get_board_change_ranking(
        board_type=board_type_from_str(board_type),
        target_date=target_date,
        days=days,
        top_n=top_n,
        ascending=ascending,
    )
    return _df_resp(df)
