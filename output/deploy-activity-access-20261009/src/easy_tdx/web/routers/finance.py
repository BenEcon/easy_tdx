"""财务 / 公司信息路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from easy_tdx.web.convert import market_from_str
from easy_tdx.web.deps import get_client
from easy_tdx.web.schemas import DataFrameResponse

router = APIRouter(tags=["finance"])


def _df_resp(df: Any) -> DataFrameResponse:
    return DataFrameResponse.from_dataframe(df)


@router.get("/xdxr", response_model=DataFrameResponse)
async def xdxr_info(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取除权除息历史记录。"""
    df = await client.get_xdxr_info(market_from_str(market), code)
    return _df_resp(df)


@router.get("/finance", response_model=DataFrameResponse)
async def finance_info(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取最新财务数据。"""
    df = await client.get_finance_info(market_from_str(market), code)
    return _df_resp(df)


@router.get("/company/category", response_model=DataFrameResponse)
async def company_info_category(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取公司信息文件目录。"""
    df = await client.get_company_info_category(market_from_str(market), code)
    return _df_resp(df)


@router.get("/company/content")
async def company_info_content(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6),
    filename: str = Query(..., description="文件名"),
    offset: int = Query(0, ge=0),
    length: int = Query(1024, ge=1),
    client: Any = Depends(get_client),
) -> dict[str, str]:
    """读取公司信息文本。"""
    content = await client.get_company_info_content(
        market_from_str(market), code, filename, offset, length
    )
    return {"content": content}


@router.get("/financial/file-list", response_model=DataFrameResponse)
async def financial_file_list(
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取可用的历史专业财报文件列表。"""
    df = await client.get_financial_file_list()
    return _df_resp(df)


@router.get("/financial/records", response_model=DataFrameResponse)
async def financial_records(
    filename: str = Query(..., description="财报文件名，如 tdxfin/gpcw20260331.zip"),
    code: str | None = Query(None, min_length=6, max_length=6, description="可选：只返回指定股票"),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """下载财报 zip 并解析为记录列表。"""
    df = await client.get_financial_records(filename)
    if code and not df.empty and "code" in df.columns:
        df = df[df["code"].astype(str).str.zfill(6) == code]
    return _df_resp(df)
