"""Allow-listed server-observed query metadata, never arbitrary request content."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool

from easy_tdx.web.account_store import UserRecord
from easy_tdx.web.routers.auth import get_current_user
from easy_tdx.web.user_activity import get_activity_store

logger = logging.getLogger(__name__)
FEATURES = {
    "/chanlun/archive-recompute": "存档显式重算",
    "/research/factors/evaluate": "因子截面检验",
    "/research/factors/evaluate/async": "因子截面检验任务",
    "/research/factors/recompute": "因子存档显式重算",
    "/research/factors/recompute/async": "因子存档重算任务",
    "/bars": "个股行情",
    "/bars/range": "历史行情",
    "/bars/research": "研究行情",
    "/bars/index": "指数行情",
    "/minute": "分时行情",
    "/minute/history": "历史分时",
    "/transaction": "逐笔成交",
    "/transaction/history": "历史成交",
    "/quotes": "报价查询",
    "/chanlun/analyze": "缠论结构",
    "/chanlun/industry": "行业缠论",
    "/chanlun/replay": "缠论回放",
    "/chanlun/replay/compare": "缠论周期对比",
    "/chanlun/observations": "多周期研究",
    "/chanlun/industries": "所属行业",
    "/market/stat": "市场统计",
    "/market/strength": "市场强弱",
    "/fund-flow": "资金流向",
    "/fund-flow/history": "历史资金流向",
    "/mac/capital-flow": "个股资金",
    "/mac/symbol-info": "证券资料",
    "/board-mac/list": "板块列表",
    "/board-mac/members": "板块成员",
    "/board-mac/belong": "板块归属",
    "/board-mac/summary": "板块概览",
    "/board-mac/ranking": "板块排名",
    "/board-mac/change-ranking": "板块涨跌排名",
    "/company/category": "F10 目录",
    "/company/content": "F10 资料",
    "/finance": "财务资料",
    "/xdxr": "分红送转",
    "/security/list": "证券目录",
    "/ex/instruments": "扩展证券目录",
    "/financial/records": "专业财务",
    "/announcements": "公司公告",
    "/sina/financial-report": "财务报表",
    "/mac/quote-list": "市场报价",
    "/mac/auction": "集合竞价",
    "/mac/unusual": "市场异动",
    "/research/factors/compute": "因子研究",
    "/research/factors/compute/async": "因子序列任务",
    "/research/portfolio-risk": "组合风险",
    "/backtest/run": "个股回测",
    "/backtest/run/async": "个股回测任务",
    "/backtest/portfolio/run/async": "组合回测任务",
    "/backtest/multi-strategy/run/async": "多策略回测任务",
    "/backtest/optimize/run/async": "参数寻优",
    "/backtest/optimize-all/run/async": "全部策略寻优",
    "/backtest/signal-scan/run/async": "信号雷达",
    "/ex/bars": "扩展市场行情",
    "/ex/quote": "扩展市场报价",
    "/ex/minute": "扩展市场分时",
    "/ex/transaction": "扩展市场成交",
    "/block": "板块查询",
}
_SYMBOL = re.compile(r"^[A-Za-z0-9:_.,-]{1,80}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$")


def query_details(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    result: dict[str, Any] = {}
    for key in (
        "code",
        "symbol",
        "market",
        "category",
        "adjust",
        "kind",
        "board_type",
        "board_code",
        "board_symbol",
        "stock_code",
        "stock_market",
        "strategy",
        "strategy_name",
        "source_archive_id",
    ):
        value = body.get(key)
        if isinstance(value, str) and _SYMBOL.fullmatch(value):
            result[key] = value
    for key in ("start_date", "end_date", "as_of"):
        value = body.get(key)
        if isinstance(value, str) and _DATE.fullmatch(value):
            result[key] = value
    for key in ("count", "visible_count"):
        value = body.get(key)
        if type(value) is int and 0 <= value <= 100_000:
            result[key] = value
    # Only identities from series/portfolio, never bars, arrays, notes or source code.
    for key in ("series", "symbols", "codes", "stocks"):
        values = body.get(key)
        if isinstance(values, list):
            selected: list[Any] = []
            for value in values[:100]:
                if isinstance(value, str) and _SYMBOL.fullmatch(value):
                    selected.append(value)
                elif isinstance(value, dict):
                    clean = {
                        k: v
                        for k, v in value.items()
                        if k in {"code", "market", "category"}
                        and isinstance(v, str)
                        and _SYMBOL.fullmatch(v)
                    }
                    if clean:
                        selected.append(clean)
                elif (
                    isinstance(value, list | tuple)
                    and len(value) == 2
                    and all(isinstance(v, str) and _SYMBOL.fullmatch(v) for v in value)
                ):
                    selected.append(list(value))
            if selected:
                result[key] = selected
                result[f"{key}_total"] = len(values)
    return result


async def record_query(
    request: Request, user: UserRecord = Depends(get_current_user)
) -> AsyncIterator[None]:
    path = request.url.path.removeprefix("/api/v1").rstrip("/")
    feature = FEATURES.get(path)
    # Explicit UI intent only. Missing/unknown origins (including older clients,
    # automatic hydration, name lookup and polling) are not user queries.
    if (
        not feature
        or request.method not in {"GET", "POST"}
        or request.headers.get("x-query-origin") != "user"
        or (
            request.headers.get("x-task-owner") is not None
            and request.headers.get("x-task-owner") != user.id
        )
        or (
            path
            in {
                "/chanlun/archive-recompute",
                "/research/factors/recompute",
                "/research/factors/recompute/async",
            }
            and request.headers.get("x-research-owner") != user.id
        )
    ):
        yield
        return
    details = query_details(dict(request.query_params))
    if request.method == "POST":
        try:
            body = await request.json()
            details.update(query_details(body))
            if path == "/chanlun/archive-recompute" and isinstance(body, dict):
                mode = body.get("kind")
                if isinstance(mode, str) and mode in {"chart", "study"}:
                    details.update(query_details(body.get(mode)))
        except ValueError:
            pass
    outcome = "accepted"
    try:
        yield
    except BaseException:
        outcome = "failed"
        raise
    finally:
        # Telemetry failure must not turn an already accepted research request into a retry.
        try:
            await run_in_threadpool(
                get_activity_store().record,
                user.id,
                "query",
                request.client.host if request.client else "",
                feature,
                outcome,
                details,
            )
        except Exception:
            logger.warning("User query activity could not be persisted", exc_info=True)
