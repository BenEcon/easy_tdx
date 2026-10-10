"""Acquire bounded real research fixtures through the project's MAC client.

Explicit invocation only; never imported by tests. Configuration is isolated
before importing easy_tdx, and existing frozen files are never overwritten.
These are present-day vendor snapshots, not historical point-in-time vintages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="tdx-matrix-config-") as isolated:
        os.environ["EASY_TDX_CONFIG_DIR"] = isolated
        from easy_tdx.mac.client import MacClient
        from easy_tdx.mac.enums import Adjust, BoardType, Period

        observed = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
        client = MacClient(timeout=4, auto_reconnect=True)
        try:
            client.connect()
            catalog = client.get_board_list(BoardType.HY, count=300).to_dict("records")
            belong = client.get_belong_board(market=1, code="600699").to_dict("records")
            codes = {str(row["code"]) for row in catalog}
            board = next(row for row in belong if str(row["board_code"]) in codes)
            entry = next(row for row in catalog if str(row["code"]) == str(board["board_code"]))
            instruments = [
                {
                    "kind": "stock",
                    "code": "300750",
                    "market": "SZ",
                    "exchange": 0,
                    "name": "宁德时代",
                    "adjust": "QFQ",
                },
                {
                    "kind": "index",
                    "code": "000001",
                    "market": "SH",
                    "exchange": 1,
                    "name": "上证指数",
                    "adjust": "NONE",
                },
                {
                    "kind": "board",
                    "code": str(board["board_code"]),
                    "market": str(board["market"]),
                    "exchange": int(board["market"]),
                    "name": str(entry["name"]),
                    "adjust": "NONE",
                    "board_type": "HY",
                    "stock_market": "SH",
                    "stock_code": "600699",
                    "catalog_entry": entry,
                    "belong_entry": board,
                },
            ]
            for instrument in instruments:
                for category, period, count in [
                    ("DAY", Period.DAILY, 240),
                    ("WEEK", Period.WEEKLY, 150),
                    ("MONTH", Period.MONTHLY, 48),
                    ("MIN_30", Period.MIN_30, 240),
                ]:
                    filename = (
                        f"{instrument['kind']}-{instrument['code']}-"
                        f"{category.lower()}-{observed:%Y%m%d}.json"
                    )
                    path = args.output / filename
                    if path.exists():
                        raise FileExistsError(f"Refusing to overwrite {path}")
                    frame = client.get_stock_kline(
                        instrument["exchange"],
                        instrument["code"],
                        period,
                        0,
                        count,
                        adjust=Adjust[instrument["adjust"]],
                        bar_time="start",
                    )
                    if frame.empty:
                        raise ValueError(f"No real bars for {filename}")
                    actual = frame.attrs.get("actual_adjust", instrument["adjust"])
                    if actual != instrument["adjust"]:
                        raise ValueError(f"Adjustment mismatch: {actual}")
                    records = frame.to_dict("records")
                    for row in records:
                        row["datetime"] = row["datetime"].isoformat(sep=" ")
                    payload = {
                        "schema": "real-market-matrix-v1",
                        "instrument": instrument,
                        "category": category,
                        "source": "MAC",
                        "host": client._host,
                        "observed_at": observed.isoformat(sep=" "),
                        "bar_time": "native_end",
                        "requested_adjust": instrument["adjust"],
                        "actual_adjust": actual,
                        "adjustment_source": frame.attrs.get("adjustment_source"),
                        "historical_data_vintage": False,
                        "requested_count": count,
                        "catalog_observed_at": observed.isoformat(sep=" "),
                        "bars_sha256": hashlib.sha256(canonical(records).encode()).hexdigest(),
                        "bars": records,
                    }
                    with path.open("x", encoding="utf-8") as handle:
                        handle.write(
                            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
                            + "\n"
                        )
                    print(
                        filename,
                        len(records),
                        records[0]["datetime"],
                        records[-1]["datetime"],
                        flush=True,
                    )
        finally:
            client.close()


if __name__ == "__main__":
    main()
