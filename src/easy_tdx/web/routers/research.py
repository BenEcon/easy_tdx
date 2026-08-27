"""量化研究 Web 路由：因子计算、组合权重与风险分析。"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from easy_tdx.web.convert import category_from_str, market_from_str
from easy_tdx.web.deps import get_client
from easy_tdx.web.schemas import DataFrameResponse, DictResponse, StockIdentifier

router = APIRouter(tags=["research"])


class FactorComputeRequest(BaseModel):
    market: str = Field(..., pattern=r"^(SZ|SH|BJ)$")
    code: str = Field(..., min_length=6, max_length=6)
    category: str = "DAY"
    count: int = Field(default=300, ge=60, le=800)
    factors: list[str] = Field(..., min_length=1, max_length=12)


class PortfolioRiskRequest(BaseModel):
    stocks: list[StockIdentifier] = Field(..., min_length=2, max_length=20)
    method: Literal["equal", "factor_weighted", "risk_parity", "mean_variance"] = "risk_parity"
    category: str = "DAY"
    count: int = Field(default=300, ge=60, le=800)


def _json_safe_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.replace([np.inf, -np.inf], np.nan).astype(object).where(pd.notna(df), None)


@router.get("/research/factors")
async def factor_list() -> list[dict[str, Any]]:
    """列出全部内置量化因子及其输入字段。"""
    from easy_tdx.factor import list_factors

    return list_factors()


@router.post("/research/factors/compute", response_model=DictResponse)
async def factor_compute(
    req: FactorComputeRequest,
    client: Any = Depends(get_client),
) -> DictResponse:
    """获取单股行情并计算一个或多个内置因子。"""
    from easy_tdx.factor import FactorEngine

    df = await client.get_security_bars(
        market_from_str(req.market), req.code, category_from_str(req.category), 0, req.count
    )
    if "date" in df.columns and "datetime" not in df.columns:
        df = df.rename(columns={"date": "datetime"})
    if df.empty:
        return DictResponse(data={"rows": [], "count": 0, "errors": {}})

    engine = FactorEngine()
    result = df.copy()
    errors: dict[str, str] = {}
    computed: list[str] = []
    for factor_name in req.factors:
        try:
            result = engine.compute_single(result, [factor_name])
            computed.append(factor_name)
        except Exception as exc:
            errors[factor_name] = str(exc)

    requested_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
        *computed,
    ]
    keep = [column for column in requested_columns if column in result.columns]
    output = _json_safe_frame(result[keep].tail(160).reset_index(drop=True))
    return DictResponse(
        data={
            "rows": DataFrameResponse.from_dataframe(output).data,
            "count": len(output),
            "computed": computed,
            "errors": errors,
        }
    )


@router.post("/research/portfolio-risk", response_model=DictResponse)
async def portfolio_risk(
    req: PortfolioRiskRequest,
    client: Any = Depends(get_client),
) -> DictResponse:
    """基于在线日线计算组合权重、相关性、年化波动与风险贡献。"""
    from easy_tdx.portfolio import RiskModel, get_optimizer

    series: list[pd.Series] = []
    asset_rows: list[dict[str, Any]] = []
    for stock in req.stocks:
        df = await client.get_security_bars(
            market_from_str(stock.market),
            stock.code,
            category_from_str(req.category),
            0,
            req.count,
        )
        if df.empty or "close" not in df.columns:
            continue
        time_col = "datetime" if "datetime" in df.columns else "date"
        close = pd.Series(
            pd.to_numeric(df["close"], errors="coerce").to_numpy(),
            index=pd.to_datetime(df[time_col]),
            name=stock.code,
        ).sort_index()
        ret = close.pct_change().replace([np.inf, -np.inf], np.nan)
        series.append(ret)
        annual_return = float(ret.mean(skipna=True) * 252)
        volatility = float(ret.std(skipna=True) * np.sqrt(252))
        asset_rows.append(
            {
                "code": stock.code,
                "market": stock.market,
                "annual_return": annual_return,
                "volatility": volatility,
                "score": annual_return / volatility if volatility > 0 else 0.0,
            }
        )

    if len(series) < 2:
        return DictResponse(
            data={"weights": {}, "risk": {}, "assets": asset_rows, "correlation": []}
        )

    returns = pd.concat(series, axis=1).sort_index().dropna(how="all").fillna(0.0)
    scores = pd.DataFrame(asset_rows)
    weights = get_optimizer(req.method).optimize(scores, n_stocks=len(scores))
    risk_model = RiskModel()
    covariance = risk_model.estimate_covariance(returns)
    risk = risk_model.portfolio_risk(weights, covariance)

    codes = [c for c in weights if c in covariance.columns]
    if codes:
        w = np.array([weights[c] for c in codes])
        cov = covariance.loc[codes, codes].to_numpy()
        contribution = np.abs(w * (cov @ w))
        contribution = contribution / contribution.sum() if contribution.sum() > 0 else contribution
        contribution_map = {code: float(contribution[i]) for i, code in enumerate(codes)}
    else:
        contribution_map = {}
    for row in asset_rows:
        row["weight"] = float(weights.get(str(row["code"]), 0.0))
        row["risk_contribution"] = contribution_map.get(str(row["code"]), 0.0)

    correlation = returns.corr().round(4)
    correlation.index.name = "code"
    correlation_rows = DataFrameResponse.from_dataframe(correlation.reset_index()).data
    return DictResponse(
        data={
            "weights": weights,
            "risk": risk,
            "assets": asset_rows,
            "correlation": correlation_rows,
            "observations": len(returns),
            "method": req.method,
        }
    )
