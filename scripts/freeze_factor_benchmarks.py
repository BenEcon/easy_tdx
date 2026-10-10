"""Bounded public index snapshot capture, isolated config, never overwrite."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory


async def capture():
    from easy_tdx.factor.snapshot import freeze_input
    from easy_tdx.mac.client import AsyncMacClient
    from easy_tdx.web.factor_benchmark import load_factor_benchmark

    root = Path(__file__).resolve().parents[1] / "tests/fixtures/factor_benchmarks"
    root.mkdir(exist_ok=True)
    client = AsyncMacClient("121.36.248.138", timeout=4, auto_reconnect=False)
    hashes = []
    try:
        await asyncio.wait_for(client.connect(), 15)
        for symbol, category in [
            (s, "DAY") for s in ("SH:000001", "SZ:399001", "SH:000300", "SZ:399006")
        ] + [("SH:000001", "MIN_30")]:
            path = root / f"{symbol.replace(':', '-')}-{category}.json"
            if path.exists():
                raise FileExistsError(path)
            # No standard client: failed MAC calls remain failures, not equity replacements.
            frame = await asyncio.wait_for(
                load_factor_benchmark(symbol, category, 320, None, client), 25
            )
            data = {
                "scope": "current vendor snapshot, not historical PIT",
                "snapshot": freeze_input(symbol, frame),
            }
            payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode()
            with path.open("xb") as handle:
                handle.write(payload)
            hashes.append(f"{hashlib.sha256(payload).hexdigest()}  {path.name}\n")
            print(path.name, len(frame), flush=True)
    finally:
        await client.close()
        if hashes:
            with (root / "SHA256SUMS").open("x") as handle:
                handle.writelines(hashes)


if __name__ == "__main__":
    with TemporaryDirectory(prefix="factor-benchmark-config-") as config:
        os.environ["EASY_TDX_CONFIG_DIR"] = config
        asyncio.run(capture())
