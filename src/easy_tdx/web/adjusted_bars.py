"""Shared adjusted K-line fetcher for internal Web workflows."""

from __future__ import annotations

from typing import Any

import pandas as pd

from easy_tdx.web.convert import (
    adjust_from_str,
    category_from_str,
    market_from_str,
    market_value_from_str,
    period_times_from_category,
)


async def fetch_adjusted_bars(
    client: Any,
    mac_client: Any | None,
    market: str,
    code: str,
    category: str,
    start: int,
    count: int,
    adjust: str = "QFQ",
) -> pd.DataFrame:
    """Fetch bars through MAC when available, preserving standard-client fallback."""
    cat = category_from_str(category)
    if mac_client is not None and hasattr(mac_client, "get_stock_kline"):
        period, times = period_times_from_category(cat)
        return await mac_client.get_stock_kline(
            market_value_from_str(market),
            code,
            period,
            start,
            count,
            times,
            adjust=adjust_from_str(adjust),
        )
    return await client.get_security_bars(
        market_from_str(market),
        code,
        cat,
        start,
        count,
    )
