"""Readiness on a named, hashed ten-equity pool, not a live-market guarantee."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from easy_tdx.factor import FactorEngine, get_factor
from easy_tdx.factor.builtin.alpha101 import SPECS
from easy_tdx.factor.catalog import describe_factor
from tests.unit.test_gtja191_vwap import long_frozen


def report() -> dict:
    root = Path(__file__).resolve().parents[1] / "tests/fixtures/factor_vwap_long"
    files = sorted(root.glob("*-DAILY-NONE.json"))
    data = {p.stem: long_frozen(p.name).set_index("datetime") for p in files}
    rows = []
    for number in sorted(SPECS):
        name = f"alpha101_{number:03d}"
        factor = get_factor(name)()
        values = FactorEngine().compute_matrix(data, factor)
        definition = describe_factor(type(factor))
        rows.append(
            {
                "name": name,
                "alias_of": definition["alias_of"],
                "definition_sha256": definition["formula_sha256"],
                "version": definition["implementation_version"],
                "finite_cells": int(values.notna().sum().sum()),
                "latest_date": str(values.index[-1]),
                "latest_finite_symbols": int(values.iloc[-1].notna().sum()),
                "by_symbol": {
                    s: {
                        "finite": int(values[s].notna().sum()),
                        "first_valid": str(values[s].first_valid_index()),
                        "last_valid": str(values[s].last_valid_index()),
                    }
                    for s in values
                },
            }
        )
    return {
        "scope": "指定十股320根不复权日线冻结池；不代表实时、历史PIT或生产许可就绪",
        "inputs": [
            {"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in files
        ],
        "registered_in_batch": len(rows),
        "canonical_definitions": sum(not r["alias_of"] for r in rows),
        "canonical_ever_finite": sum(not r["alias_of"] and r["finite_cells"] > 0 for r in rows),
        "canonical_latest_any": sum(
            not r["alias_of"] and r["latest_finite_symbols"] > 0 for r in rows
        ),
        "canonical_latest_all": sum(
            not r["alias_of"] and r["latest_finite_symbols"] == len(files) for r in rows
        ),
        "ever_finite": sum(r["finite_cells"] > 0 for r in rows),
        "latest_any": sum(r["latest_finite_symbols"] > 0 for r in rows),
        "latest_all": sum(r["latest_finite_symbols"] == len(files) for r in rows),
        "rows": rows,
    }


if __name__ == "__main__":
    print(json.dumps(report(), ensure_ascii=False, indent=2))
