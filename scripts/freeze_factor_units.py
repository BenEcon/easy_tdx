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


async def acquire(
    output: Path,
    count: int = 160,
    adjustments: tuple[str, ...] = ("NONE", "QFQ", "HFQ"),
    stocks: list[str] | None = None,
) -> None:
    from easy_tdx.mac.client import AsyncMacClient
    from easy_tdx.mac.enums import Adjust, Period

    output.mkdir(parents=True, exist_ok=True)
    client = AsyncMacClient("121.36.248.138", timeout=4, auto_reconnect=False)
    try:
        await asyncio.wait_for(client.connect(), 15)
        samples = (
            [
                (0, "000001", Period.DAILY),
                (0, "300750", Period.DAILY),
                (1, "600036", Period.DAILY),
                (0, "300750", Period.MIN_30),
            ]
            if stocks is None
            else [(int(s.split(":")[0]), s.split(":")[1], Period[s.split(":")[2]]) for s in stocks]
        )
        for market, code, period in samples:
            for name in adjustments:
                adjust = Adjust[name]
                path = output / f"{market}-{code}-{period.name}-{adjust.name}.json"
                if path.exists():
                    raise FileExistsError(f"Refusing to overwrite {path}")
                frame = await asyncio.wait_for(
                    client.get_stock_kline(
                        market,
                        code,
                        period,
                        count=count,
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
                    "requested_count": count,
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
    parser.add_argument("--count", type=int, default=160)
    parser.add_argument("--adjust", choices=("NONE", "QFQ", "HFQ"), action="append")
    parser.add_argument("--stock", action="append", help="Explicit market:code:period, at most 20")
    args = parser.parse_args()
    if not 1 <= args.count <= 800:
        parser.error("count must be between 1 and 800; no silent truncation")
    adjustments = tuple(args.adjust or ("NONE", "QFQ", "HFQ"))
    if len(set(adjustments)) != len(adjustments):
        parser.error("duplicate adjustments are not allowed")
    if args.stock:
        import re

        if (
            len(args.stock) > 20
            or len(set(args.stock)) != len(args.stock)
            or any(not re.fullmatch(r"[01]:[0-9]{6}:(DAILY|MIN_30)", s) for s in args.stock)
        ):
            parser.error("stock must be unique market:6-digit-code:DAILY/MIN_30, at most 20")
    with TemporaryDirectory(prefix="factor-unit-config-") as config:
        os.environ["EASY_TDX_CONFIG_DIR"] = config
        asyncio.run(acquire(args.output, args.count, adjustments, args.stock))


if __name__ == "__main__":
    main()
