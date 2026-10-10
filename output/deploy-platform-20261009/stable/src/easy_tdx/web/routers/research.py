"""量化研究 Web 路由：因子计算、组合权重与风险分析。"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

from easy_tdx.web.adjusted_bars import fetch_adjusted_bars
from easy_tdx.web.deps import get_client, get_mac_client_optional
from easy_tdx.web.market_data import closed_frame
from easy_tdx.web.schemas import DataFrameResponse, DictResponse, StockIdentifier

router = APIRouter(tags=["research"])


class FactorComputeRequest(BaseModel):
    market: str = Field(..., pattern=r"^(SZ|SH|BJ)$")
    code: str = Field(..., min_length=6, max_length=6)
    category: str = "DAY"
    count: int = Field(default=300, ge=60, le=800)
    factors: list[str] = Field(..., min_length=1, max_length=12)
    adjust: Literal["NONE", "QFQ", "HFQ"] = "QFQ"


class PortfolioRiskRequest(BaseModel):
    stocks: list[StockIdentifier] = Field(..., min_length=2, max_length=20)
    method: Literal["equal", "factor_weighted", "risk_parity", "mean_variance"] = "risk_parity"
    category: Literal["DAY"] = "DAY"
    count: int = Field(default=300, ge=60, le=800)
    adjust: Literal["NONE", "QFQ", "HFQ"] = "QFQ"

    @model_validator(mode="after")
    def unique_assets(self) -> PortfolioRiskRequest:
        if len({s.code for s in self.stocks}) != len(self.stocks):
            raise ValueError("组合标的代码不得重复；当前风险模型按股票代码标识资产")
        return self


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
    mac_client: Any | None = Depends(get_mac_client_optional),
) -> DictResponse:
    """获取单股行情并计算一个或多个内置因子。"""
    from easy_tdx.web.resource_admission import run_compute

    df = await fetch_adjusted_bars(
        client, mac_client, req.market, req.code, req.category, 0, req.count, req.adjust
    )
    df = closed_frame(df)
    if "date" in df.columns and "datetime" not in df.columns:
        df = df.rename(columns={"date": "datetime"})
    if df.empty:
        return DictResponse(
            data={
                "rows": [],
                "count": 0,
                "errors": {},
                "metadata": df.attrs.get("snapshot_metadata"),
            }
        )

    return await run_compute(lambda: _factor_result(req, df))


def _factor_result(req: FactorComputeRequest, df: pd.DataFrame) -> DictResponse:
    from easy_tdx.factor import FactorEngine

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
            "metadata": df.attrs.get("snapshot_metadata"),
            "input_count": len(df),
        }
    )


@router.post("/research/portfolio-risk", response_model=DictResponse)
async def portfolio_risk(
    req: PortfolioRiskRequest,
    client: Any = Depends(get_client),
    mac_client: Any | None = Depends(get_mac_client_optional),
) -> DictResponse:
    """基于在线日线计算组合权重、相关性、年化波动与风险贡献。"""
    from easy_tdx.web.resource_admission import run_compute

    series: list[pd.Series] = []
    asset_rows: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    for stock in req.stocks:
        df = await fetch_adjusted_bars(
            client,
            mac_client,
            stock.market,
            stock.code,
            req.category,
            0,
            req.count,
            req.adjust,
        )
        df = closed_frame(df)
        if df.empty or "close" not in df.columns:
            raise ValueError(f"{stock.market}:{stock.code} 无有效收盘行情；未跳过该资产")
        provenance.append(
            {
                "market": stock.market,
                "code": stock.code,
                "count": len(df),
                "metadata": df.attrs.get("snapshot_metadata"),
            }
        )
        time_col = "datetime" if "datetime" in df.columns else "date"
        close = pd.Series(
            pd.to_numeric(df["close"], errors="coerce").to_numpy(),
            index=pd.to_datetime(df[time_col]),
            name=stock.code,
        ).sort_index()
        series.append(close)

    return await run_compute(lambda: _risk_result(req, series, asset_rows, provenance))


def _risk_result(
    req: PortfolioRiskRequest,
    series: list[pd.Series],
    asset_rows: list[dict[str, Any]],
    provenance: list[dict[str, Any]],
) -> DictResponse:
    from easy_tdx.portfolio import RiskModel, get_optimizer

    # Align price observations before computing returns, so missing observations
    # never become zero returns or mismatched holding-period returns across assets.
    prices = pd.concat(series, axis=1).sort_index()
    raw_returns = prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    from datetime import timedelta

    from easy_tdx.web.trading_calendar import missing_sessions

    # If every asset lacks a date, outer alignment alone cannot reveal the gap.
    # A multi-session return must not be annualized as one daily observation.
    calendar_gap_returns = []
    for previous, current in zip(prices.index, prices.index[1:]):
        if missing_sessions(
            previous.date() + timedelta(days=1), current.date() - timedelta(days=1), set()
        ):
            raw_returns.loc[current] = np.nan
            calendar_gap_returns.append(str(current))
    returns = raw_returns.dropna(how="any")
    if len(returns) < 2:
        raise ValueError("共同有效日收益不足 2 条，不能估计组合风险；未用零收益填充缺失行情")
    for stock in req.stocks:
        ret = returns[stock.code]
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
            "provenance": provenance,
            "alignment": {
                "policy": "common_observed_daily_returns_no_fill",
                "excluded_observations": len(raw_returns) - len(returns),
                "start": str(returns.index[0]),
                "end": str(returns.index[-1]),
                "annualization": 252,
                "calendar_gap_returns": calendar_gap_returns,
                "note": "仅使用共同有效日收益，不补零；年化按 252 个交易日，非未来收益预测。",
            },
        }
    )
