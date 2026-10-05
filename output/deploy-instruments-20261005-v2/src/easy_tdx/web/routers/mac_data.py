"""MAC 数据路由：资金流向、个股信息、服务器信息。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from easy_tdx.web.convert import market_value_from_str
from easy_tdx.web.deps import get_mac_client
from easy_tdx.web.schemas import DataFrameResponse

router = APIRouter(tags=["mac-data"])


def _df_resp(df: Any) -> DataFrameResponse:
    return DataFrameResponse.from_dataframe(df)


@router.get("/mac/capital-flow", response_model=DataFrameResponse)
async def capital_flow(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6, description="6位股票代码"),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取个股资金流向（主力/散户净流入）。"""
    df = await client.get_capital_flow(market=market_value_from_str(market), code=code)
    return _df_resp(df)


@router.get("/mac/symbol-info", response_model=DataFrameResponse)
async def symbol_info(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6, description="6位股票代码"),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取个股基本信息快照。"""
    df = await client.get_symbol_info(market=market_value_from_str(market), code=code)
    return _df_resp(df)


@router.get("/mac/server-info", response_model=DataFrameResponse)
async def server_info(
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取服务器交易时段信息。"""
    df = await client.get_server_info()
    return _df_resp(df)
