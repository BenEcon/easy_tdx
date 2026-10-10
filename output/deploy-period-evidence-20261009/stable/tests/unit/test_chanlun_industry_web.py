from unittest.mock import AsyncMock

import pandas as pd
import pytest
from fastapi import HTTPException

from easy_tdx.mac.enums import Adjust
from easy_tdx.web.routers.chanlun import IndustryRequest, industry_analyze


@pytest.mark.asyncio
async def test_industry_uses_board_market_and_unadjusted_bars():
    client = AsyncMock()
    client.get_belong_board.return_value = pd.DataFrame(
        [
            {"board_code": "881155", "board_type": 12, "market": 90},
        ]
    )
    client.get_board_list.return_value = pd.DataFrame([{"code": "881155"}])
    client.get_stock_kline.return_value = pd.DataFrame(
        [
            {
                "datetime": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i),
                "open": 10 + i,
                "close": 11 + i,
                "high": 12 + i,
                "low": 9 + i,
                "vol": 100,
                "amount": 1000,
            }
            for i in range(40)
        ]
    )
    req = IndustryRequest(stock_market="SZ", stock_code="000001", board_code="881155")
    data = await industry_analyze(req, client)
    assert data["result"]["code"] == "881155"
    assert len(data["bars"]) == 40
    assert client.get_stock_kline.call_args.args[:2] == (90, "881155")
    assert client.get_stock_kline.call_args.kwargs["adjust"] == Adjust.NONE


@pytest.mark.asyncio
async def test_concept_is_not_an_industry():
    client = AsyncMock()
    client.get_board_list.return_value = pd.DataFrame([{"code": "881155"}])
    client.get_belong_board.return_value = pd.DataFrame(
        [
            {"board_code": "880001", "board_type": 3, "market": 90},
        ]
    )
    req = IndustryRequest(stock_market="SZ", stock_code="000001", board_code="880001")
    with pytest.raises(HTTPException) as exc:
        await industry_analyze(req, client)
    assert exc.value.status_code == 404
    client.get_stock_kline.assert_not_called()


@pytest.mark.asyncio
async def test_missing_service_is_explicit():
    req = IndustryRequest(stock_market="SZ", stock_code="000001", board_code="881155")
    with pytest.raises(HTTPException) as exc:
        await industry_analyze(req, None)
    assert exc.value.status_code == 503
