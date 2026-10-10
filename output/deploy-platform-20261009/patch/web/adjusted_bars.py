"""Shared adjusted K-line fetcher for internal Web workflows."""

from __future__ import annotations

from typing import Any

import pandas as pd

from easy_tdx.web.market_data import load_equity_frame


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
    """Native close labels, explicit provenance; never silently change adjustment."""
    return await load_equity_frame(client, mac_client, market, code, category, start, count, adjust)
