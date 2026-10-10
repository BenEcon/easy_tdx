"""Explicit bounded capture for filtered-sample regression; no existing files overwritten."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory


async def capture():
    from easy_tdx.factor.snapshot import freeze_input
    from easy_tdx.mac.client import AsyncMacClient
    from easy_tdx.web.adjusted_bars import fetch_adjusted_bars
    from easy_tdx.web.factor_benchmark import load_factor_benchmark
    from easy_tdx.web.market_data import closed_frame

    root = Path(__file__).resolve().parents[1] / "tests/fixtures/factor_benchmark_long"
    root.mkdir(exist_ok=True)
    client = AsyncMacClient("121.36.248.138", timeout=4, auto_reconnect=False)
    hashes = []
    try:
        await asyncio.wait_for(client.connect(), 15)
        index = await asyncio.wait_for(
            load_factor_benchmark("SH:000001", "DAY", 800, None, client), 30
        )
        sources = [("SH-000001-index.json", "SH:000001", index)]
        for market, code in (("SZ", "000001"), ("SZ", "300750"), ("SH", "600036")):
            frame = await asyncio.wait_for(
                fetch_adjusted_bars(None, client, market, code, "DAY", 0, 800, "NONE"), 30
            )
            sources.append((f"{market}-{code}-stock.json", f"{market}:{code}", closed_frame(frame)))
        for name, symbol, frame in sources:
            payload = json.dumps(
                {
                    "scope": "Current vendor snapshot, not historical PIT",
                    "snapshot": freeze_input(symbol, frame),
                },
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ).encode()
            with (root / name).open("xb") as handle:
                handle.write(payload)
            hashes.append(f"{hashlib.sha256(payload).hexdigest()}  {name}\n")
            print(name, len(frame), flush=True)
    finally:
        await client.close()
        if hashes:
            with (root / "SHA256SUMS").open("x") as handle:
                handle.writelines(hashes)


if __name__ == "__main__":
    with TemporaryDirectory(prefix="factor-long-index-config-") as config:
        os.environ["EASY_TDX_CONFIG_DIR"] = config
        asyncio.run(capture())
