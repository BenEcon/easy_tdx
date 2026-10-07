"""Read-only real-source acceptance in the release container, no account access."""
import asyncio
import json
from easy_tdx.mac.client import AsyncMacClient
from easy_tdx.web.routers.bars import security_bars
from easy_tdx.web.adjusted_bars import fetch_adjusted_bars


async def main():
    # Start at the reported faulty node to exercise real rotation if still down.
    client = AsyncMacClient("121.36.248.138", timeout=6, heartbeat_interval=0)
    try:
        await client.connect()
        for market, code in [("SH", "601208"), ("SZ", "300750"), ("SZ", "300450")]:
            for category in ["DAY", "MIN_60"]:
                result = await security_bars(market=market, code=code, category=category,
                    start=0, count=600, bar_time="start", adjust="QFQ", mac_client=client, client=None)
                assert result["count"] == 600, result["count"]
                assert result["metadata"]["actual_adjust"] == "QFQ"
                assert result["metadata"]["source"] == "MAC"
                assert all(float(row["low"]) > 0 for row in result["data"])
                print(json.dumps(dict(code=code, category=category, count=result["count"],
                    adjust=result["metadata"]["actual_adjust"], host=client._host,
                    last=result["data"][-1].get("date", result["data"][-1].get("datetime"))), default=str), flush=True)
            frame = await fetch_adjusted_bars(None, client, market, code, "DAY", 0, 600, "QFQ")
            assert len(frame) == 600
            assert frame["low"].gt(0).all()
            print("PASS shared Chanlun/backtest data path", code, flush=True)
    finally:
        await client.close()


asyncio.run(main())
