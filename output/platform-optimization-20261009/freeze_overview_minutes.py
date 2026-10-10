"""Explicit read-only acquisition for the five-period UI acceptance sample."""
import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

with TemporaryDirectory(prefix="tdx-overview-market-") as isolated:
    os.environ["EASY_TDX_CONFIG_DIR"] = isolated
    from easy_tdx.mac.client import MacClient
    from easy_tdx.mac.enums import Adjust, Period
    from easy_tdx.web.bar_snapshot import annotate_snapshot

    client = MacClient(timeout=4, auto_reconnect=True)
    try:
        client.connect()
        for category in ("MIN_15", "MIN_5"):
            target = Path(__file__).parent / f"overview-300750-{category}.json"
            if target.exists():
                raise FileExistsError(target)
            frame = client.get_stock_kline(0, "300750", Period[category], 0, 240, adjust=Adjust.QFQ, bar_time="start")
            if frame.empty or frame.attrs.get("actual_adjust") != "QFQ":
                raise ValueError("Missing bars or unverified actual adjustment")
            records = frame.to_dict("records")
            for row in records:
                row["datetime"] = row["datetime"].isoformat(sep=" ")
            observed = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
            snapshot = annotate_snapshot(records, category, source="MAC", requested_adjust="QFQ", actual_adjust="QFQ", bar_time="end", now=observed)
            if snapshot["metadata"]["quality"]["errors"]:
                raise ValueError(snapshot["metadata"]["quality"]["errors"])
            with target.open("x") as handle:
                json.dump(snapshot, handle, ensure_ascii=False, allow_nan=False)
            print(category, len(records), records[0]["datetime"], records[-1]["datetime"], flush=True)
    finally:
        client.close()
