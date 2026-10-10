"""Explicit, bounded unit audit; isolated config, public bars, no overwrite.

Pairs NONE/QFQ/HFQ for fixed public examples. Does not infer or change production
unit metadata. Results are current vendor snapshots, not historical PIT data.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


async def acquire(output: Path) -> None:
    from easy_tdx.mac.client import AsyncMacClient
    from easy_tdx.mac.enums import Adjust, Period

    output.mkdir(parents=True, exist_ok=True)
    client = AsyncMacClient("121.36.248.138", timeout=4, auto_reconnect=False)
    try:
        await asyncio.wait_for(client.connect(), 15)
        for market, code, period in [
            (0, "000001", Period.DAILY),
            (0, "300750", Period.DAILY),
            (1, "600036", Period.DAILY),
            (0, "300750", Period.MIN_30),
        ]:
            for adjust in (Adjust.NONE, Adjust.QFQ, Adjust.HFQ):
                path = output / f"{market}-{code}-{period.name}-{adjust.name}.json"
                if path.exists():
                    raise FileExistsError(f"Refusing to overwrite {path}")
                frame = await asyncio.wait_for(
                    client.get_stock_kline(
                        market,
                        code,
                        period,
                        count=160,
                        adjust=adjust,
                        bar_time="start",
                    ),
                    20,
                )
                if frame.empty or frame.attrs.get("actual_adjust") != adjust.name:
                    raise ValueError("Empty or wrong-adjustment response")
                rows = frame.to_dict("records")
                for row in rows:
                    row["datetime"] = row["datetime"].isoformat()
                encoded = json.dumps(
                    rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
                )
                payload = {
                    "source": "MAC",
                    "host": client._host,
                    "market": market,
                    "code": code,
                    "period": period.name,
                    "adjust": adjust.name,
                    "observed_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                    "historical_data_vintage": False,
                    "attributes": frame.attrs,
                    "bars_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                    "bars": rows,
                }
                with path.open("x", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
                print(path.name, len(rows), flush=True)
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="factor-unit-config-") as config:
        os.environ["EASY_TDX_CONFIG_DIR"] = config
        asyncio.run(acquire(args.output))


if __name__ == "__main__":
    main()
