"""Read-only extraction of official-module signatures, NOT a formula registry.

No source code is imported or executed. The emitted JSON contains provenance,
interface/dependency facts and review flags, not copyrighted formula text.
Usage: python scripts/audit_alpha_reference.py /path/to/DolphinDBModules
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

COMMIT = "43ace2cc4b81d048864ec2e40c25728d5d464e05"
SOURCES = {
    "alpha101": (
        "wq101alpha/src/wq101alpha.dos",
        "WQAlpha",
        101,
        "ae7a52198542aa879d00d7f97a6281e036af116fcbb6c82fa95308021235f64a",
    ),
    "gtja191": (
        "gtja191Alpha/src/gtja191Alpha.dos",
        "gtjaAlpha",
        191,
        "e3d93adcdacff263795b8f0b97de1b806ce3666b118f7819af59d9ef5ff98543",
    ),
}
LICENSE_SHA256 = "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"


def inventory(text: str, prefix: str, count: int) -> list[dict]:
    matches = list(re.finditer(r"^def\s+" + prefix + r"(\d+)\s*\(([^)]*)\)\s*\{", text, re.M))
    numbers = [int(match[1]) for match in matches]
    if sorted(numbers) != list(range(1, count + 1)):
        raise ValueError(f"{prefix}: missing, duplicate or unexpected factor IDs")
    entries = []
    for offset, match in enumerate(matches):
        end = matches[offset + 1].start() if offset + 1 < len(matches) else len(text)
        body = re.sub(r"/\*.*?\*/|//[^\n]*", "", text[match.end() : end], flags=re.S)
        fields = [field.strip() for field in match[2].split(",")]
        special = {
            "indclass": "historical_industry_membership_and_classification_levels",
            "cap": "historical_market_cap_with_units",
            "index_open": "timestamp_aligned_benchmark_open",
            "index_close": "timestamp_aligned_benchmark_close",
            "MKT": "timestamp_aligned_market_risk_factor",
            "SMB": "timestamp_aligned_size_risk_factor",
            "HML": "timestamp_aligned_value_risk_factor",
            "vwap": "verified_same_adjustment_vwap",
            "vol": "verified_volume_units_and_zero_policy",
        }
        flags = [special[field] for field in fields if field in special]
        cross_section = bool(re.search(r"\b(rowRank|contextby)\b", body))
        if cross_section:
            flags.append("explicit_universe_and_exact_timestamp_alignment")
        if "indclass.row(0)" in body:
            flags.append("reference_uses_first_industry_row_not_point_in_time")
        entries.append(
            {
                "number": int(match[1]),
                "reference_function": prefix + match[1],
                "reference_inputs": fields,
                "reference_line": text[: match.start()].count("\n") + 1,
                "reference_has_cross_section_operator": cross_section,
                "dependency_review": flags,
                "app_status": "not_implemented",
                "formula_verified": False,
                "count_as_available": False,
            }
        )
    return sorted(entries, key=lambda item: item["number"])


def audit(root: Path) -> dict:
    license_bytes = (root / "LICENSE").read_bytes()
    if hashlib.sha256(license_bytes).hexdigest() != LICENSE_SHA256:
        raise ValueError("Reference LICENSE changed; review before continuing")
    result = {
        "schema": "alpha-reference-interface-audit-v1",
        "reference_repository": "https://github.com/dolphindb/DolphinDBModules",
        "reference_commit": COMMIT,
        "reference_license": "Apache-2.0",
        "license_sha256": LICENSE_SHA256,
        "scope": (
            "Interface inventory only; not original-formula validation or redistribution clearance"
        ),
        "libraries": {},
    }
    for name, (relative, prefix, count, digest) in SOURCES.items():
        raw = (root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"{relative}: reference source changed; review before continuing")
        entries = inventory(raw.decode("utf-8-sig"), prefix, count)
        result["libraries"][name] = {
            "path": relative,
            "sha256": digest,
            "interfaces": len(entries),
            "implemented_in_app": 0,
            "entries": entries,
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--output", type=Path, help="Optional generated audit JSON artifact")
    args = parser.parse_args()
    content = json.dumps(audit(args.reference), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        if args.output.exists():
            raise SystemExit("Refusing to overwrite existing audit artifact")
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
