"""Verify every prefix of the frozen real matrix, with no future-price leakage.

This is a reproducible long-running acceptance job, not a network test. A partial
report never means completion. Resume is allowed only for identical source,
runtime, manifest and verifier bytes; failed reports cannot resume silently.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from easy_tdx.web.routers.chanlun_replay import ReplayRequest, replay_snapshot
    from easy_tdx.web.task_version import execution_version
    from tests.market_matrix import MANIFEST, canonical_hash, entries, load_case

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    identity = {
        "execution_version": execution_version(),
        "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "loader_sha256": hashlib.sha256((ROOT / "tests/market_matrix.py").read_bytes()).hexdigest(),
    }
    if args.output.exists():
        if not args.resume:
            raise FileExistsError("Existing acceptance report; use --resume explicitly")
        report = json.loads(args.output.read_text())
        if report["identity"] != identity or report["status"] == "failed":
            raise ValueError("Source/runtime changed or previous verification failed")
    else:
        report = {
            "schema": "real-prefix-acceptance-v1",
            "identity": identity,
            "status": "running",
            "historical_data_vintage": False,
            "cases": {},
            "scope": (
                "Every prefix of these frozen cases; not every instrument, "
                "rule interpretation or historical vintage."
            ),
        }

    def persist():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(".pending.json")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(args.output)

    current = None
    count = None
    try:
        persist()
        for entry in sorted(
            entries(), key=lambda row: (row["legacy_metadata_preserved"], row["count"], row["id"])
        ):
            current = entry["id"]
            case = report["cases"].setdefault(
                current,
                {
                    "source_sha256": entry["file_sha256"],
                    "total": entry["count"],
                    "status": "running",
                    "prefixes": [],
                },
            )
            assert case["source_sha256"] == entry["file_sha256"]
            _, _, snapshot = load_case(entry)
            request = ReplayRequest(
                code=entry["code"],
                category=entry["category"],
                bars=snapshot["data"],
                visible_count=len(snapshot["data"]),
            )
            poisoned = []
            for i, bar in enumerate(request.bars):
                poisoned.append(
                    bar.model_copy(
                        update={
                            **{
                                key: getattr(bar, key) * (100 + i)
                                for key in ("open", "high", "low", "close")
                            },
                            "vol": bar.vol * 100,
                            "amount": bar.amount * 100,
                            "is_closed": False,
                        }
                    )
                )
            for count in range(len(case["prefixes"]) + 1, len(request.bars) + 1):
                direct = replay_snapshot(
                    request.model_copy(
                        update={"bars": request.bars[:count], "visible_count": count}
                    ),
                    ownership_history="full",
                )
                suffix = replay_snapshot(
                    request.model_copy(
                        update={
                            "bars": request.bars[:count] + poisoned[count:],
                            "visible_count": count,
                        }
                    ),
                    ownership_history="full",
                )
                # Only the transport's full snapshot size differs. All computed
                # structures, histories, evidence, events and timestamps must agree.
                del direct["replay"]["total_count"]
                del suffix["replay"]["total_count"]
                assert direct == suffix, (current, count, "future suffix changed result")
                assert direct["kline_count"] == count
                for family in ("bis", "xds", "bcs", "mmds"):
                    for item in direct[family]:
                        for key in ("confirmed_index", "detected_index", "invalidated_index"):
                            if item.get(key) is not None:
                                assert 0 <= item[key] < count, (current, count, family, key)
                case["prefixes"].append(
                    {
                        "count": count,
                        "result_sha256": canonical_hash(direct),
                        "structure_counts": {
                            key: direct[key]
                            for key in ("bi_count", "xd_count", "zs_count", "mmd_count", "bc_count")
                        },
                    }
                )
                if count % 50 == 0:
                    persist()
                    print(current, count, "/", len(request.bars), flush=True)
            case["status"] = "passed"
            persist()
            print(current, "passed", len(case["prefixes"]), flush=True)
        if execution_version() != identity["execution_version"]:
            raise ValueError("Source/runtime changed during verification")
        assert len(report["cases"]) == len(entries())
        assert all(case["status"] == "passed" for case in report["cases"].values())
        report["status"] = "passed"
        report["completed_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
        persist()
        print(
            "FULL MATRIX PASSED",
            sum(len(c["prefixes"]) for c in report["cases"].values()),
            flush=True,
        )
    except BaseException as exc:
        report.update(
            status="failed", failure={"case": current, "prefix": count, "error": repr(exc)}
        )
        persist()
        raise


if __name__ == "__main__":
    main()
