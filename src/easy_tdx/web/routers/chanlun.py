"""缠论分析路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from easy_tdx.chanlun.input_data import ChanlunInputError
from easy_tdx.chanlun.ownership_history import OwnershipHistoryMode
from easy_tdx.chanlun.structure_filter import filter_base_outputs
from easy_tdx.web.adjusted_bars import fetch_adjusted_bars
from easy_tdx.web.bar_snapshot import mark_indicator_closed_bars
from easy_tdx.web.deps import get_client, get_mac_client_optional
from easy_tdx.web.resource_admission import run_compute
from easy_tdx.web.routers.chanlun_archive import router as archive_router
from easy_tdx.web.routers.chanlun_observations import router as observations_router
from easy_tdx.web.routers.chanlun_replay import router as replay_router
from easy_tdx.web.schemas import ChanlunRequest
from easy_tdx.web.structure_settings import StructureSettings

router = APIRouter(tags=["chanlun"])
router.include_router(replay_router)
router.include_router(observations_router)
router.include_router(archive_router)


async def stock_industries(client: Any, market: str, code: str) -> list[dict[str, Any]]:
    from easy_tdx.mac.enums import BoardType
    from easy_tdx.web.convert import market_value_from_str

    belong = await client.get_belong_board(market=market_value_from_str(market), code=code)
    # Belong-board response types use a different numbering scheme than BoardType.
    # Match the official industry catalogs rather than interpreting those integers.
    catalog_codes: set[str] = set()
    for kind in (BoardType.HY, BoardType.HY2):
        catalog = await client.get_board_list(board_type=kind, count=5000)
        catalog_codes.update(str(r["code"]) for r in catalog.to_dict("records"))
    return [r for r in belong.to_dict("records") if str(r["board_code"]) in catalog_codes]


@router.get("/chanlun/industries")
async def industry_belong(
    market: str = Query(pattern=r"^(SZ|SH|BJ)$"),
    code: str = Query(pattern=r"^\d{6}$"),
    mac_client: Any | None = Depends(get_mac_client_optional),
) -> dict[str, Any]:
    if mac_client is None:
        raise HTTPException(503, "行业行情服务暂不可用")
    rows = await stock_industries(mac_client, market, code)
    return {"data": rows, "count": len(rows)}


class IndustryRequest(BaseModel):
    structure_settings: StructureSettings = Field(default_factory=StructureSettings)
    stock_market: str = Field(pattern=r"^(SZ|SH|BJ)$")
    stock_code: str = Field(pattern=r"^\d{6}$")
    board_code: str = Field(pattern=r"^\d{6}$")
    category: str = "DAY"
    count: int = Field(default=600, ge=1, le=800)


@router.post("/chanlun/industry")
async def industry_analyze(
    req: IndustryRequest,
    mac_client: Any | None = Depends(get_mac_client_optional),
    ownership_history: OwnershipHistoryMode = "full",
) -> dict[str, Any]:
    from easy_tdx.chanlun import ChanlunAnalyser
    from easy_tdx.mac.enums import Adjust
    from easy_tdx.web.convert import category_from_str, period_times_from_category
    from easy_tdx.web.market_data import checked_snapshot
    from easy_tdx.web.schemas import DataFrameResponse

    if mac_client is None:
        raise HTTPException(503, "行业行情服务暂不可用")
    rows = await stock_industries(mac_client, req.stock_market, req.stock_code)
    board = next((r for r in rows if str(r["board_code"]) == req.board_code), None)
    if board is None:
        raise HTTPException(404, "未找到该股票对应的行业")
    category = req.category.upper()
    period, times = period_times_from_category(
        category_from_str("MIN_60" if category == "MIN_120" else category)
    )
    if category == "MIN_120":
        from easy_tdx.mac.enums import Period

        period, times = Period.MINS, 24
    df = await mac_client.get_stock_kline(
        int(board["market"]),
        req.board_code,
        period,
        0,
        req.count,
        times,
        adjust=Adjust.NONE,
        bar_time="start",
    )
    if df.empty:
        raise HTTPException(404, "该行业在所选周期暂无行情")
    try:
        snapshot = checked_snapshot(
            DataFrameResponse.from_dataframe(df).data,
            category,
            source="MAC_BOARD",
            requested_adjust="NONE",
            actual_adjust="NONE",
            bar_time="end",
        )
    except HTTPException as exc:
        raise HTTPException(exc.status_code, f"行业行情数据异常：{exc.detail}") from exc
    try:

        def compute() -> dict[str, Any]:
            analysed = ChanlunAnalyser(
                code=req.board_code,
                frequency=req.category,
                config=req.structure_settings.engine_config(),
            ).process_klines(mark_indicator_closed_bars(df, req.category, bar_time="end"))
            output = filter_base_outputs(analysed, req.structure_settings.zs_min_lines).to_dict(
                ownership_history=ownership_history
            )
            output["structure_settings"] = req.structure_settings.model_dump()
            return output

        result = await run_compute(compute)
    except ChanlunInputError as exc:
        raise HTTPException(502, f"行业行情数据异常：{exc}") from exc
    return {"bars": snapshot["data"], "metadata": snapshot["metadata"], "result": result}


@router.post("/chanlun/analyze")
async def chanlun_analyze(
    req: ChanlunRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
    ownership_history: OwnershipHistoryMode = "full",
) -> dict[str, Any]:
    """执行缠论分析。

    自动从 TDX 服务器获取 K 线数据，运行完整缠论计算管道，
    返回笔、中枢、线段、买卖点、背驰等分析结果。
    """
    from easy_tdx.chanlun import ChanlunAnalyser

    # 1. Fetch kline data
    df = await fetch_adjusted_bars(
        client,
        mac_client,
        req.market,
        req.code,
        req.category,
        req.start,
        req.count,
        req.adjust,
    )

    # 2. Run chanlun analysis
    symbol = f"{req.market}{req.code}"
    frequency_map: dict[str, str] = {
        "MIN_1": "1min",
        "MIN_5": "5min",
        "MIN_15": "15min",
        "MIN_30": "30min",
        "MIN_60": "60min",
        "DAY": "daily",
        "WEEK": "weekly",
        "MONTH": "monthly",
        "YEAR": "yearly",
    }
    freq = frequency_map.get(req.category.upper(), req.category)
    analyser = ChanlunAnalyser(code=symbol, frequency=freq)
    try:

        def compute() -> dict[str, Any]:
            return analyser.process_klines(mark_indicator_closed_bars(df, req.category)).to_dict(
                ownership_history=ownership_history
            )

        output = await run_compute(compute)
    except ChanlunInputError as exc:
        raise HTTPException(502, f"股票行情数据异常：{exc}") from exc

    output["metadata"] = df.attrs.get("snapshot_metadata")
    return output
