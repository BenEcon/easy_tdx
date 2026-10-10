"""Explicitly freeze hashes and provenance for old and newly acquired cases."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from tests.market_matrix import canonical_hash

    fixtures = ROOT / "tests/fixtures"
    cases = []
    paths = sorted((fixtures / "chanlun").glob("*.json")) + sorted(
        p for p in (fixtures / "market_matrix").glob("*.json") if p.name != "manifest.json"
    )
    for path in paths:
        payload = json.loads(path.read_text())
        records = payload.get("bars", payload.get("data"))
        new = payload.get("schema") == "real-market-matrix-v1"
        metadata = payload.get("metadata", {})
        code = payload["instrument"]["code"] if new else path.name[:6]
        category = payload.get("category", metadata.get("category"))
        observed = payload.get(
            "observed_at", payload.get("acquired_at", metadata.get("observed_at"))
        )
        adjust = payload.get("actual_adjust", payload.get("adjust", metadata.get("actual_adjust")))
        old_index = code == "399006"
        case = {
            "id": path.stem,
            "path": str(path.relative_to(fixtures)),
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bars_sha256": canonical_hash(records),
            "count": len(records),
            "first": records[0].get("datetime", records[0].get("date")),
            "last": records[-1].get("datetime", records[-1].get("date")),
            "category": category,
            "code": code,
            "observed_at": observed,
            "adjust": adjust,
            "source": "MAC",
            "historical_data_vintage": False,
            "instrument": payload["instrument"]
            if new
            else {
                "kind": "index" if old_index else "stock",
                "code": code,
                "market": "SH" if code.startswith("6") else "SZ",
            },
            "native_bar_time": "end",
            "legacy_metadata_preserved": not new,
            "notes": []
            if new
            else ["Original fixture is unchanged; derived legacy period_end is not authoritative."],
        }
        if metadata.get("bar_time") == "start" and category.startswith("MIN_"):
            case["notes"].append(
                "Legacy metadata incorrectly describes native minute closing stamps as start times."
            )
        if old_index:
            case["notes"].append(
                "Legacy index QFQ fixture is retained for rule regression only, "
                "not current NONE index-contract acceptance."
            )
        cases.append(case)
    output = fixtures / "market_matrix/manifest.json"
    output.write_text(
        json.dumps(
            {
                "schema": "real-market-matrix-manifest-v1",
                "cases": cases,
                "historical_data_vintage": False,
                "scope": (
                    "Source snapshots, not proof of historical point-in-time availability "
                    "or all possible instruments/strategies."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(f"Frozen {len(cases)} source files")


if __name__ == "__main__":
    main()
