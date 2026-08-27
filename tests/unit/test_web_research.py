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
    async def get_security_bars(self, _market, code, _category, _start, count):
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
        ),
        client=_FakeBarsClient(),
    )
    weights = result.data["weights"]
    assert set(weights) == {"000001", "600519", "600036"}
    assert sum(weights.values()) == pytest.approx(1.0)
    assert len(result.data["assets"]) == 3
    assert len(result.data["correlation"]) == 3
