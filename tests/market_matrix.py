"""Source-preserving frozen market matrix; never fetches from the network."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from easy_tdx.web.bar_snapshot import annotate_snapshot

ROOT = Path(__file__).parent / "fixtures"
MANIFEST = ROOT / "market_matrix/manifest.json"


def canonical_hash(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def load_case(entry):
    path = ROOT / entry["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["file_sha256"]
    payload = json.loads(path.read_text())
    records = payload.get("bars", payload.get("data"))
    assert canonical_hash(records) == entry["bars_sha256"]
    # Preserve every raw fixture. Discard only derived legacy end times from the
    # analysis copy; native protocol stamps are already right-hand endpoints.
    raw = [
        {
            ("datetime" if key == "date" else key): value
            for key, value in row.items()
            if key != "period_end"
        }
        for row in records
    ]
    observed = datetime.fromisoformat(entry["observed_at"])
    if observed.tzinfo is not None:
        observed = observed.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    snapshot = annotate_snapshot(
        raw,
        entry["category"],
        source=entry["source"],
        requested_adjust=entry["adjust"],
        actual_adjust=entry["adjust"],
        bar_time="end",
        now=observed,
    )
    frame = pd.DataFrame(raw)
    frame["datetime"] = pd.to_datetime(frame["datetime"])
    frame.attrs["actual_adjust"] = entry["adjust"]
    frame.attrs["snapshot_metadata"] = snapshot["metadata"]
    return payload, frame, snapshot


def entries():
    return json.loads(MANIFEST.read_text())["cases"]
