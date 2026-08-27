"""MAC EX 扩展市场 Web 路由测试。"""

from __future__ import annotations

import pandas as pd

from easy_tdx.mac.enums import Period
from easy_tdx.web.routers.ex_market import (
    ex_bars,
    ex_instruments,
    ex_markets,
    ex_minute,
    ex_quote,
    ex_transaction,
)


class FakeMacExClient:
    def __init__(self) -> None:
        self.last_kline: tuple[int, str, Period, int, int] | None = None

    async def goods_list(self, market: int, start: int, count: int) -> pd.DataFrame:
        return pd.DataFrame([{"market": market, "code": "00700", "name": "腾讯控股"}])

    async def goods_kline(
        self, market: int, code: str, *, period: Period, start: int, count: int
    ) -> pd.DataFrame:
        self.last_kline = (market, code, period, start, count)
        return pd.DataFrame(
            [{"datetime": pd.Timestamp("2026-08-27"), "open": 450.8, "close": 447.8}]
        )

    async def goods_quotes(self, stocks: list[tuple[int, str]]) -> pd.DataFrame:
        market, code = stocks[0]
        return pd.DataFrame([{"market": market, "code": code, "price": 447.8}])

    async def goods_tick_chart(self, market: int, code: str) -> pd.DataFrame:
        return pd.DataFrame([{"market": market, "code": code, "price": 447.8}])

    async def goods_transaction(
        self, market: int, code: str, *, start: int, count: int
    ) -> pd.DataFrame:
        return pd.DataFrame([{"market": market, "code": code, "price": 447.8, "vol": 100}])


async def test_mac_ex_market_directory_and_bars() -> None:
    client = FakeMacExClient()

    markets = await ex_markets(client=client)
    instruments = await ex_instruments(market="31", start=0, count=20, client=client)
    bars = await ex_bars(
        market="31", code="00700", category="DAY", start=0, count=20, client=client
    )

    assert markets.count > 20
    assert any(row["market"] == 31 and row["name"] == "香港主板" for row in markets.data)
    assert instruments.data[0]["name"] == "腾讯控股"
    assert bars.data[0]["datetime"] == "2026-08-27T00:00:00"
    assert client.last_kline == (31, "00700", Period.DAILY, 0, 20)


async def test_mac_ex_quote_minute_and_transaction() -> None:
    client = FakeMacExClient()

    quote = await ex_quote(market="31", code="00700", client=client)
    minute = await ex_minute(market="31", code="00700", client=client)
    transaction = await ex_transaction(
        market="31", code="00700", start=0, count=100, client=client
    )

    assert quote.data[0]["price"] == 447.8
    assert minute.data[0]["market"] == 31
    assert transaction.data[0]["vol"] == 100
