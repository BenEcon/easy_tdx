"""Definition/readiness contracts; counts are not formula acceptance claims."""

import json

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from easy_tdx.factor import FACTORY_REGISTRY, Factor, FactorEngine, get_factor, list_factors
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.web.routers.research import (
    FactorComputeRequest,
    FactorEvaluationRequest,
    _factor_result,
    _json_safe_frame,
)


def test_nonfinite_serialization_is_null_not_nan_or_zero():
    clean = _json_safe_frame(pd.DataFrame({"value": [np.inf, -np.inf, np.nan, 0.0]}))
    assert clean.value.tolist() == [None, None, None, 0.0]
    json.dumps(clean.to_dict("records"), allow_nan=False)


def frame(n=500):
    close = pd.Series(np.arange(n, dtype=float) + 10)
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=n),
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "vol": close * 100,
            "amount": close * 1000,
        }
    )


def test_builtin_catalog_counts_separate_aliases_and_placeholders():
    catalog = [f for f in list_factors() if f["library"] == "easy_tdx_builtin"]
    unique = [f for f in catalog if not f["alias_of"]]
    assert len(catalog) == 20
    assert len(unique) == 19
    assert sum(f["implemented"] for f in unique) == 17
    assert sum(f["evaluation_available"] for f in unique) == 15
    assert len({f["canonical_name"] for f in catalog}) == 19
    json.dumps(catalog, allow_nan=False)
    for f in unique:
        assert f["display_name"] and f["formula"] and f["source"]
        assert len(f["formula_sha256"]) == 64
        assert f["inputs"] and f["data_requirements"] and f["supported_categories"]
        assert all(p["editable"] is True for p in f["parameters"].values())
        assert f["formula_sha256"] == describe_factor(get_factor(f["name"]))["formula_sha256"]


def test_proxy_has_distinct_canonical_name_but_old_configuration_is_unchanged():
    data = frame(50)
    expected = pd.Series(
        [np.nan] * 19
        + [data.amount.iloc[i] / sum(data.amount.iloc[i - 19 : i + 1]) * 20 for i in range(19, 50)]
    )
    for name in ["turnover_rate", "amount_relative_20"]:
        pd.testing.assert_series_equal(
            get_factor(name)().compute(data), expected, check_names=False
        )
    old = describe_factor(get_factor("turnover_rate"))
    new = describe_factor(get_factor("amount_relative_20"))
    assert old["alias_of"] == new["name"]
    assert old["formula_sha256"] == new["formula_sha256"]
    assert "换手率" in " ".join(new["limitations"])


@pytest.mark.parametrize(
    "factors", [["momentum_20d", "momentum_20d"], ["turnover_rate", "amount_relative_20"]]
)
def test_duplicate_definitions_rejected_in_both_entry_points(factors):
    with pytest.raises(ValidationError):
        FactorComputeRequest(market="SZ", code="000001", factors=factors)
    with pytest.raises(ValidationError):
        FactorEvaluationRequest(
            stocks=[{"market": "SZ", "code": f"{i:06}"} for i in range(5)], factors=factors
        )


@pytest.mark.parametrize("category", ["MIN_30", "WEEK"])
def test_structural_factor_does_not_silently_use_daily_algorithm_on_other_period(category):
    with pytest.raises(ValidationError, match="不支持"):
        FactorComputeRequest(
            market="SZ", code="000001", category=category, factors=["chanlun_bi_dir"]
        )


def test_results_return_all_requested_rows_definitions_coverage_and_fingerprint():
    req = FactorComputeRequest(
        market="SZ", code="000001", count=500, factors=["momentum_20d", "amount_relative_20"]
    )
    data = frame()
    result = _factor_result(req, data).data
    assert result["count"] == result["input_count"] == 500
    assert result["output_truncated"] is False
    assert result["settings"] == req.model_dump()
    assert len(result["rows"]) == 500
    assert result["rows"][0]["momentum_20d"] is None
    assert result["diagnostics"]["momentum_20d"]["valid_count"] == 480
    assert result["diagnostics"]["amount_relative_20"]["missing_count"] == 19
    assert set(result["factor_definitions"]) == set(req.factors)
    assert result["input_fingerprint"] == _factor_result(req, data).data["input_fingerprint"]
    changed = data.copy()
    changed.loc[499, "close"] += 1
    assert result["input_fingerprint"] != _factor_result(req, changed).data["input_fingerprint"]
    json.dumps(result, allow_nan=False, default=str)


def test_data_gap_and_unimplemented_formula_are_explicit_not_successful_zero():
    data = frame(60)
    data["amount"] = 0
    req = FactorComputeRequest(
        market="SZ", code="000001", factors=["amount_relative_20", "pe_ratio"]
    )
    result = _factor_result(req, data).data
    assert "历史财务" in result["errors"]["pe_ratio"]
    assert result["diagnostics"]["amount_relative_20"]["status"] == "no_valid_values"
    assert all(row["amount_relative_20"] is None for row in result["rows"])
    assert "pe_ratio" not in result["computed"]


def test_engine_rejects_missing_fields_and_incorrect_index(monkeypatch):
    with pytest.raises(ValueError, match="缺少字段"):
        FactorEngine().compute_single(frame().drop(columns="amount"), ["amount_relative_20"])

    class BadIndex(Factor):
        name, category, description, inputs = "bad_index", "test", "bad", ("close",)

        def compute(self, df):
            return df.close.reset_index(drop=True)

    monkeypatch.setitem(FACTORY_REGISTRY, BadIndex.name, BadIndex)
    with pytest.raises(ValueError, match="输出索引"):
        FactorEngine().compute_single(frame().set_index("datetime"), ["bad_index"])
