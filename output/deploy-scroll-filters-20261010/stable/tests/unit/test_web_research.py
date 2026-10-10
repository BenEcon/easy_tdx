"""量化研究 Web API 单元测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.web.routers.research import (
    FactorComputeRequest,
    PortfolioRiskRequest,
    factor_compute,
    factor_list,
    portfolio_risk,
)
from easy_tdx.web.schemas import StockIdentifier


class _FakeBarsClient:
    async def get_security_bars(self, _market, code, _category, _start, count, **kwargs):
        periods = min(count, 180)
        seed = int(code[-2:]) + 1
        trend = np.linspace(0, seed / 20, periods)
        close = 10 + trend + np.sin(np.arange(periods) / (7 + seed % 4)) * 0.2
        return pd.DataFrame(
            {
                "date": pd.date_range("2025-01-01", periods=periods, freq="B"),
                "open": close - 0.05,
                "high": close + 0.15,
                "low": close - 0.15,
                "close": close,
                "vol": np.arange(periods) * 100 + 10_000,
                "amount": close * (np.arange(periods) * 100 + 10_000),
            }
        )


@pytest.mark.asyncio
async def test_factor_list_and_compute() -> None:
    factors = await factor_list()
    assert any(item["name"] == "momentum_20d" for item in factors)

    result = await factor_compute(
        FactorComputeRequest(
            market="SZ",
            code="000001",
            factors=["momentum_20d", "rsi_14"],
            count=120,
            adjust="NONE",  # Standard feed cannot provide adjusted prices.
        ),
        client=_FakeBarsClient(),
    )
    assert result.data["computed"] == ["momentum_20d", "rsi_14"]
    assert result.data["count"] == 120
    assert "momentum_20d" in result.data["rows"][-1]


@pytest.mark.asyncio
async def test_portfolio_risk_returns_weights_and_correlation() -> None:
    result = await portfolio_risk(
        PortfolioRiskRequest(
            stocks=[
                StockIdentifier(market="SZ", code="000001"),
                StockIdentifier(market="SH", code="600519"),
                StockIdentifier(market="SH", code="600036"),
            ],
            method="risk_parity",
            count=120,
            adjust="NONE",
        ),
        client=_FakeBarsClient(),
    )
    weights = result.data["weights"]
    assert set(weights) == {"000001", "600519", "600036"}
    assert sum(weights.values()) == pytest.approx(1.0)
    assert len(result.data["assets"]) == 3
    assert len(result.data["correlation"]) == 3


def test_risk_request_rejects_wrong_annualization_period_and_duplicate_assets():
    stocks = [
        StockIdentifier(market="SZ", code="000001"),
        StockIdentifier(market="SH", code="600036"),
    ]
    with pytest.raises(ValueError, match="DAY"):
        PortfolioRiskRequest(stocks=stocks, category="WEEK")
    with pytest.raises(ValueError, match="重复"):
        PortfolioRiskRequest(stocks=[stocks[0], stocks[0]])


@pytest.mark.asyncio
async def test_risk_missing_asset_observations_not_zero_filled():
    class MissingClient(_FakeBarsClient):
        async def get_security_bars(self, *args, **kwargs):
            frame = await super().get_security_bars(*args, **kwargs)
            return frame.drop(index=[20]) if args[1] == "600036" else frame

    req = PortfolioRiskRequest(
        stocks=[
            StockIdentifier(market="SZ", code="000001"),
            StockIdentifier(market="SH", code="600036"),
        ],
        count=120,
        adjust="NONE",
    )
    result = (await portfolio_risk(req, client=MissingClient())).data
    # Initial pct_change plus missing day and its following return are excluded.
    assert result["observations"] == 117
    assert result["alignment"]["excluded_observations"] == 3
    assert result["alignment"]["annualization"] == 252
    assert len(result["provenance"]) == 2
    assert all(p["metadata"]["actual_adjust"] == "NONE" for p in result["provenance"])


@pytest.mark.asyncio
async def test_risk_missing_member_stops_instead_of_reweighting_remaining_assets():
    class EmptyClient(_FakeBarsClient):
        async def get_security_bars(self, *args, **kwargs):
            frame = await super().get_security_bars(*args, **kwargs)
            return frame.iloc[:0] if args[1] == "600036" else frame

    req = PortfolioRiskRequest(
        stocks=[
            StockIdentifier(market="SZ", code="000001"),
            StockIdentifier(market="SH", code="600036"),
        ],
        adjust="NONE",
    )
    with pytest.raises(ValueError, match="未跳过"):
        await portfolio_risk(req, client=EmptyClient())


@pytest.mark.asyncio
async def test_risk_common_missing_session_not_annualized_as_one_day():
    class CommonGapClient(_FakeBarsClient):
        async def get_security_bars(self, *args, **kwargs):
            frame = (await super().get_security_bars(*args, **kwargs)).iloc[:6].copy()
            frame["date"] = pd.bdate_range("2026-09-01", periods=6)
            return frame.drop(index=[1])

    req = PortfolioRiskRequest(
        stocks=[
            StockIdentifier(market="SZ", code="000001"),
            StockIdentifier(market="SH", code="600036"),
        ],
        adjust="NONE",
    )
    result = (await portfolio_risk(req, client=CommonGapClient())).data
    assert result["observations"] == 3
    assert result["alignment"]["calendar_gap_returns"] == ["2026-09-03 00:00:00"]
