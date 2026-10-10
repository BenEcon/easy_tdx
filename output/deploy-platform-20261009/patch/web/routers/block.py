"""板块信息路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from easy_tdx.web.deps import get_client
from easy_tdx.web.schemas import DataFrameResponse

router = APIRouter(tags=["block"])


def _df_resp(df: Any) -> DataFrameResponse:
    return DataFrameResponse.from_dataframe(df)


@router.get("/block", response_model=DataFrameResponse)
async def block_info(
    filename: str = Query(
        ...,
        description=("板块文件名: block_zs.dat(行业指数), block_gn.dat(概念), block_fg.dat(风格)"),
    ),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取并解析板块文件。"""
    df = await client.get_block_info(filename)
    return _df_resp(df)
