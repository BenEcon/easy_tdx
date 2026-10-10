"""Historical finite values are not a claim of present pool availability."""

import numpy as np
import pandas as pd

from scripts.gtja_frozen_readiness import factor_coverage


def definition():
    return dict(
        implementation_version="test-v1",
        formula_sha256="frozen-hash",
        resolved_parameters={},
        warmup_bars=2,
    )


def test_frozen_readiness_distinguishes_history_from_latest_and_nonfinite():
    values = pd.DataFrame(
        {"A": [np.nan, 1e-200, np.nan], "B": [1.0, np.inf, 2.0]},
        index=pd.date_range("2026-01-01", periods=3),
    )
    result = factor_coverage("test", values, definition())
    assert result["finite_values"] == 3
    assert result["latest_finite_symbols"] == 1
    assert result["latest_missing_symbols"] == ["A"]
    assert result["per_symbol"]["A"]["last_finite_date"] == "2026-01-02 00:00:00"
    assert result["per_symbol"]["B"]["coverage"] == 2 / 3
    assert result["definition_sha256"] == "frozen-hash"
    assert result["implementation_version"] == "test-v1"


def test_frozen_readiness_empty_and_missing_are_not_ready():
    for values in (pd.DataFrame(columns=["A"], dtype=float), pd.DataFrame({"A": [np.nan]})):
        result = factor_coverage("test", values, definition())
        assert result["finite_values"] == result["latest_finite_symbols"] == 0
        assert result["per_symbol"]["A"]["last_finite_date"] is None
        assert result["latest_missing_symbols"] == ["A"]
