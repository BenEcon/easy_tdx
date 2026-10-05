"""技术指标路由：指标列表、指标计算。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter

from easy_tdx.web.schemas import ComputeIndicatorsRequest, DataFrameResponse

router = APIRouter(tags=["indicator"])


def _df_resp(df: Any) -> DataFrameResponse:
    return DataFrameResponse.from_dataframe(df)


@router.get("/indicator/list")
async def indicator_list() -> list[dict[str, Any]]:
    """获取所有可用技术指标列表。"""
    from easy_tdx.indicator import list_indicators

    return list_indicators()


@router.post("/indicator/compute", response_model=DataFrameResponse)
async def indicator_compute(
    req: ComputeIndicatorsRequest,
) -> DataFrameResponse:
    """在 OHLCV 数据上计算技术指标。

    请求体包含 K 线 records 和指标名称列表，返回计算后的 DataFrame。
    """
    from easy_tdx.indicator import compute_indicators

    df = pd.DataFrame(req.data)
    result = compute_indicators(
        df,
        indicators=req.indicators,
        params=req.params,
        keep_ohlcv=req.keep_ohlcv,
        tail=req.tail,
    )
    result = result.replace([np.inf, -np.inf], np.nan).astype(object).where(pd.notna(result), None)
    return _df_resp(result)
