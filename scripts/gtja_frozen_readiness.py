"""Compute actual finite GTJA coverage on explicitly named hash-checked frozen tapes.

Local acceptance utility, not a live market scanner or a universal availability claim.
Uses test fixtures only; never fetches external data or fills undefined values.
"""

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from easy_tdx.factor import FactorEngine, list_factors
from easy_tdx.factor.builtin.gtja191 import SPECS
from easy_tdx.factor.configuration import configure_factor
from tests.unit.test_gtja191_vwap import long_frozen


def factor_coverage(name, result, definition):
    """Keep historical validity distinct from the latest aligned pool date."""
    valid = np.isfinite(result)
    latest = valid.iloc[-1] if len(result) else valid.any()
    return dict(
        name=name,
        implementation_version=definition["implementation_version"],
        definition_sha256=definition["formula_sha256"],
        resolved_parameters=definition["resolved_parameters"],
        warmup_bars=definition["warmup_bars"],
        finite_values=int(valid.sum().sum()),
        observations=len(result),
        latest_pool_date=str(result.index[-1]) if len(result) else None,
        latest_finite_symbols=int(latest.sum()),
        latest_missing_symbols=[str(s) for s in result.columns if not latest[s]],
        per_symbol={
            str(s): dict(
                finite_values=int(valid[s].sum()),
                coverage=float(valid[s].mean()) if len(result) else 0.0,
                first_finite_date=str(result.index[valid[s]][0]) if valid[s].any() else None,
                last_finite_date=str(result.index[valid[s]][-1]) if valid[s].any() else None,
            )
            for s in result.columns
        },
    )


def main():
    stocks = [
        (0, "000001"),
        (0, "300750"),
        (1, "600036"),
        (0, "000002"),
        (0, "000100"),
        (0, "000725"),
        (1, "600050"),
        (1, "600000"),
        (1, "600015"),
        (1, "601998"),
    ]
    data = {s: long_frozen(f"{m}-{s}-DAILY-NONE.json") for m, s in stocks}
    catalog = list_factors()
    catalog_by_name = {r["name"]: r for r in catalog}
    root = Path(__file__).resolve().parents[1] / "tests/fixtures/factor_vwap_long"
    inputs = []
    for m, s in stocks:
        path = root / f"{m}-{s}-DAILY-NONE.json"
        raw = path.read_bytes()
        payload = json.loads(raw)
        inputs.append(
            dict(
                symbol=s,
                file=path.name,
                file_sha256=hashlib.sha256(raw).hexdigest(),
                bars_sha256=payload["bars_sha256"],
                source=payload["source"],
                adjust=payload["adjust"],
                period=payload["period"],
                observed_at=payload["observed_at"],
                count=len(data[s]),
                first_date=str(data[s].datetime.iloc[0]),
                last_date=str(data[s].datetime.iloc[-1]),
            )
        )
    start = time.monotonic()
    values = []
    for n in sorted(SPECS):
        name = f"gtja191_{n:03d}"
        selected = data
        if n in {75, 149, 181, 182}:
            from easy_tdx.factor.benchmark import attach_benchmark
            from tests.unit.test_gtja191_benchmark import real_equity, real_index

            benchmark = real_index()
            selected = {
                s: attach_benchmark(real_equity(f), benchmark, "SH:000001") for s, f in data.items()
            }
        if n == 30:
            # This fixture pool has no risk-factor tape. Missing is not zero,
            # and it must remain visible in the denominator and inventory.
            dates = sorted(set().union(*(set(f.datetime) for f in data.values())))
            result = pd.DataFrame(np.nan, index=dates, columns=list(data))
        else:
            result = FactorEngine().compute_matrix(selected, configure_factor(name))
        coverage = factor_coverage(name, result, catalog_by_name[name])
        if n == 30:
            coverage["unavailable_reason"] = catalog_by_name[name]["unavailable_reason"]
            coverage["status"] = "missing_risk_data_not_computed"
        values.append(coverage)
    definitions = [r for r in catalog if not r["alias_of"]]
    counts = {}
    for adjust in ("NONE", "QFQ", "HFQ"):
        eligible = [
            r
            for r in definitions
            if r["implemented"] and adjust in r.get("supported_adjustments", ["NONE", "QFQ", "HFQ"])
        ]
        counts[adjust] = {
            "series": sum(r["available"] for r in eligible),
            "evaluation": sum(r["evaluation_available"] for r in eligible),
        }
    print(
        json.dumps(
            dict(
                scope=(
                    "Ten frozen 320-bar NONE tapes; not universal/live/PIT readiness. "
                    "Constant intermediate ranks remain missing."
                ),
                stocks=[s for _, s in stocks],
                inputs=inputs,
                benchmark_inputs={
                    "symbol": "SH:000001",
                    "category": "DAY",
                    "adjust": "NONE",
                    "snapshot_file": "tests/fixtures/factor_benchmarks/SH-000001-DAY.json",
                    "file_sha256": hashlib.sha256(
                        (root.parent / "factor_benchmarks/SH-000001-DAY.json").read_bytes()
                    ).hexdigest(),
                    "used_by": ["gtja191_075", "gtja191_149", "gtja191_181", "gtja191_182"],
                },
                seconds=time.monotonic() - start,
                registered=len(catalog),
                definitions=len(definitions),
                implemented=sum(r["implemented"] for r in definitions),
                conditional_ui=counts,
                ready=sum(r["finite_values"] > 0 for r in values),
                readiness_definition="ready仅指整个冻结窗口曾有有限值；不是末端或实时就绪",
                latest_any_ready=sum(r["latest_finite_symbols"] > 0 for r in values),
                latest_full_pool_ready=sum(
                    r["latest_finite_symbols"] == len(stocks) for r in values
                ),
                factors=values,
            ),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
