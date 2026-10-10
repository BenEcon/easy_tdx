"""公告检索路由（巨潮资讯网，独立数据源，不依赖 TDX 服务器）。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from easy_tdx.web.schemas import DataFrameResponse

router = APIRouter(tags=["announcement"])


@router.get("/announcements", response_model=DataFrameResponse)
async def announcements(
    code: str = Query(..., min_length=6, max_length=6, description="6位股票代码"),
    count: int = Query(30, ge=1, le=100, description="每页数量"),
    page: int = Query(1, ge=1, description="页码（1 起始）"),
) -> DataFrameResponse:
    """检索公司公告列表（巨潮资讯网，独立于 TDX 行情服务器）。

    TDX 行情不可用时本接口仍可调用。
    """
    from easy_tdx.cninfo import CninfoClient, CninfoError

    client = CninfoClient()

    def _fetch() -> DataFrameResponse:
        df = client.get_announcements(code, count=count, page=page)
        return DataFrameResponse.from_dataframe(df)

    try:
        return await asyncio.to_thread(_fetch)
    except CninfoError as e:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail=str(e)) from e
