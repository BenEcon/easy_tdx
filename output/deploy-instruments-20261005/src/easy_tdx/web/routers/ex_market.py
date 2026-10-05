"""扩展市场路由：期货、港股、美股等扩展市场行情数据。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Query

from easy_tdx.web.convert import category_from_str, ex_market_from_str, period_times_from_category
from easy_tdx.web.deps import get_ex_client
from easy_tdx.web.schemas import DataFrameResponse

router = APIRouter(tags=["ex-market"])


def _records_to_df_resp(records: Any) -> DataFrameResponse:
    """将 DataFrame 或 dataclass 列表转换为统一响应。"""
    import pandas as pd

    if isinstance(records, pd.DataFrame):
        return DataFrameResponse.from_dataframe(records)
    if not records:
        return DataFrameResponse(data=[], count=0)
    rows = [{k: v for k, v in asdict(r).items() if not k.startswith("_")} for r in records]
    for row in rows:
        if all(key in row for key in ("year", "month", "day")):
            row["datetime"] = (
                f"{int(row['year']):04d}-{int(row['month']):02d}-{int(row['day']):02d}"
                f"T{int(row.get('hour', 0)):02d}:{int(row.get('minute', 0)):02d}:00"
            )
        if "trade" in row and "vol" not in row:
            row["vol"] = row["trade"]
    df = pd.DataFrame(rows)
    return DataFrameResponse.from_dataframe(df)


@router.get("/ex/markets", response_model=DataFrameResponse)
async def ex_markets(client: Any = Depends(get_ex_client)) -> DataFrameResponse:
    """列出 MAC 扩展行情支持的市场。"""
    from easy_tdx.ex.models import KNOWN_EX_MARKETS
    from easy_tdx.mac.enums import ExMarket

    rows = [
        {
            "market": int(item),
            "code": item.name,
            "name": KNOWN_EX_MARKETS.get(int(item), item.name.replace("_", " ").title()),
        }
        for item in ExMarket
    ]
    return DataFrameResponse(data=rows, count=len(rows))


@router.get("/ex/instruments", response_model=DataFrameResponse)
async def ex_instruments(
    market: str = Query(..., description="扩展市场代码"),
    start: int = Query(0, ge=0),
    count: int = Query(300, ge=1, le=1000),
    client: Any = Depends(get_ex_client),
) -> DataFrameResponse:
    """分页读取指定市场的期货、港股或外盘合约目录。"""
    return _records_to_df_resp(
        await client.goods_list(ex_market_from_str(market), start=start, count=count)
    )


@router.get("/ex/bars", response_model=DataFrameResponse)
async def ex_bars(
    market: str = Query(..., description="扩展市场代码，如 HK_MAIN_BOARD 或数字"),
    code: str = Query(..., description="合约/证券代码"),
    category: str = Query("DAY", description="K线周期: MIN_1/MIN_5/.../DAY/WEEK/MONTH"),
    start: int = Query(0, ge=0),
    count: int = Query(700, ge=1, le=700),
    client: Any = Depends(get_ex_client),
) -> DataFrameResponse:
    """获取扩展市场 K 线数据。"""
    period, _ = period_times_from_category(category_from_str(category))
    records = await client.goods_kline(
        ex_market_from_str(market), code, period=period, start=start, count=count
    )
    return _records_to_df_resp(records)


@router.get("/ex/quote", response_model=DataFrameResponse)
async def ex_quote(
    market: str = Query(..., description="扩展市场代码"),
    code: str = Query(..., description="合约/证券代码"),
    client: Any = Depends(get_ex_client),
) -> DataFrameResponse:
    """获取扩展市场实时报价。"""
    result = await client.goods_quotes([(ex_market_from_str(market), code)])
    return _records_to_df_resp(result)


@router.get("/ex/minute", response_model=DataFrameResponse)
async def ex_minute(
    market: str = Query(..., description="扩展市场代码"),
    code: str = Query(..., description="合约/证券代码"),
    client: Any = Depends(get_ex_client),
) -> DataFrameResponse:
    """获取扩展市场分时数据。"""
    records = await client.goods_tick_chart(ex_market_from_str(market), code)
    return _records_to_df_resp(records)


@router.get("/ex/transaction", response_model=DataFrameResponse)
async def ex_transaction(
    market: str = Query(..., description="扩展市场代码"),
    code: str = Query(..., description="合约/证券代码"),
    start: int = Query(0, ge=0),
    count: int = Query(1800, ge=1, le=3000),
    client: Any = Depends(get_ex_client),
) -> DataFrameResponse:
    """获取扩展市场逐笔成交数据。"""
    records = await client.goods_transaction(
        ex_market_from_str(market), code, start=start, count=count
    )
    return _records_to_df_resp(records)
