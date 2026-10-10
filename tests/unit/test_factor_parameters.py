from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from easy_tdx.factor import FactorEngine, get_factor
from easy_tdx.factor.builtin.alpha158 import SPECS
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.configuration import configure_factor, configured_selection
from easy_tdx.factor.research import cross_section_report
from easy_tdx.web.routers.research import (
    FactorComputeRequest,
    FactorEvaluationRequest,
    _factor_result,
)
from tests.unit.test_alpha158 import oracle, sample


@pytest.mark.parametrize("key", [key for key, spec in SPECS.items() if spec.window])
def test_every_registered_window_accepts_custom_window_and_independent_oracle(key):
    name = f"alpha158_{key.lower()}"
    frame = sample(90)
    factor = configure_factor(name, {"window": 13})
    values = FactorEngine().compute_single(frame, [factor])[name]
    expected = [oracle(frame, key, i, spec=factor.spec) for i in range(len(frame))]
    np.testing.assert_allclose(values, expected, atol=2e-10, rtol=2e-8, equal_nan=True)
    pd.testing.assert_series_equal(values.iloc[:70], factor.compute(frame.iloc[:70]))
    assert get_factor(name).spec == SPECS[key]
    assert get_factor(name)().spec.window == SPECS[key].window
    description = describe_factor(get_factor(name), {"window": 13})
    assert description["resolved_parameters"] == {"window": 13}
    assert description["warmup_bars"] == factor.spec.warmup
    assert description["formula"] == factor.spec.formula
    assert description["parameters"]["window"]["default"] == SPECS[key].window
    assert description["parameters"]["window"]["value"] == 13


@pytest.mark.parametrize("value", [None, True, False, 0, 1, 601, 5.5, 13.0, "13", {}, [13]])
def test_bad_windows_rejected_not_coerced(value):
    with pytest.raises(ValueError):
        configure_factor("alpha158_ma5", {"window": value})


def test_invalid_parameter_keys_unselected_fixed_and_equivalent_duplicates():
    for name, params in [
        ("alpha158_ma5", {"span": 13}),
        ("alpha158_ma5", {"window": 13, "bad": 1}),
        ("alpha158_kmid", {"window": 13}),
        ("chanlun_bi_dir", {"window": 13}),
    ]:
        with pytest.raises(ValueError):
            configure_factor(name, params)
    with pytest.raises(ValueError, match="未选中"):
        configured_selection(["alpha158_ma5"], {"alpha158_ma10": {"window": 13}})
    with pytest.raises(ValueError, match="重复"):
        configured_selection(["alpha158_ma5", "alpha158_ma10"], {"alpha158_ma5": {"window": 10}})
    assert (
        len(
            configured_selection(
                ["alpha158_ma5", "alpha158_ma10"], {"alpha158_ma5": {"window": 13}}
            )
        )
        == 2
    )


def test_explicit_default_same_result_and_metadata_as_legacy_request():
    name = "alpha158_ma5"
    assert describe_factor(get_factor(name)) == describe_factor(get_factor(name), {"window": 5})
    frame = sample()
    assert (
        configure_factor(name)
        .compute(frame)
        .equals(configure_factor(name, {"window": 5}).compute(frame))
    )


def test_two_simultaneous_requests_do_not_mutate_defaults():
    frame = sample()

    def compute(window):
        return configure_factor("alpha158_ma5", {"window": window}).compute(frame)

    with ThreadPoolExecutor(2) as executor:
        five, thirteen = list(executor.map(compute, [5, 13]))
    assert five.iloc[:4].isna().all() and pd.notna(five.iloc[4])
    assert thirteen.iloc[:12].isna().all() and pd.notna(thirteen.iloc[12])
    assert get_factor("alpha158_ma5").spec.window == 5


def test_requests_result_formula_hash_and_effective_window():
    frame = sample()
    req = FactorComputeRequest(
        market="SZ",
        code="000001",
        factors=["alpha158_ma5"],
        factor_parameters={"alpha158_ma5": {"window": 13}},
    )
    result = _factor_result(req, frame).data
    assert result["diagnostics"]["alpha158_ma5"]["valid_count"] == len(frame) - 12
    assert result["factor_definitions"]["alpha158_ma5"]["formula"] == "Mean($close,13)/$close"
    assert result["settings"]["factor_parameters"] == req.factor_parameters
    baseline = _factor_result(req.model_copy(update={"factor_parameters": {}}), frame).data
    assert result["input_fingerprint"] != baseline["input_fingerprint"]
    assert (
        result["factor_definitions"]["alpha158_ma5"]["formula_sha256"]
        != baseline["factor_definitions"]["alpha158_ma5"]["formula_sha256"]
    )
    for params in ({"bad": {"window": 13}}, {"alpha158_ma5": {"window": True}}):
        with pytest.raises(ValidationError):
            FactorComputeRequest(
                market="SZ", code="000001", factors=req.factors, factor_parameters=params
            )
        with pytest.raises(ValidationError):
            FactorEvaluationRequest(
                stocks=[{"market": "SZ", "code": f"{i:06}"} for i in range(5)],
                factors=req.factors,
                factor_parameters=params,
            )


def test_cross_section_uses_actual_parameters_and_export_metadata():
    pool = {
        str(i): sample().assign(datetime=sample().index, close=lambda df: df.close * (1 + i * 0.01))
        for i in range(5)
    }
    name = "alpha158_ma5"
    baseline = cross_section_report(pool, [name], 5, 3)
    custom = cross_section_report(pool, [name], 5, 3, factor_parameters={name: {"window": 13}})
    assert custom["settings"]["factor_parameters"] == {name: {"window": 13}}
    assert custom["factor_definitions"][name]["warmup_bars"] == 13
    assert custom["input_fingerprint"] != baseline["input_fingerprint"]
    assert custom["reports"][0]["coverage"] == pytest.approx((145 - 12) / 145)


@pytest.mark.asyncio
async def test_pool_route_passes_configuration_into_real_report(monkeypatch):
    from easy_tdx.web.routers import research

    async def fetch(_client, _mac, market, code, *args):
        frame = sample().assign(datetime=sample().index)
        frame.attrs["snapshot_metadata"] = {"actual_adjust": "QFQ", "quality": {"status": "ok"}}
        return frame

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda frame: frame)
    req = FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"{i:06}"} for i in range(5)],
        factors=["alpha158_ma5"],
        factor_parameters={"alpha158_ma5": {"window": 13}},
    )
    result = (await research.factor_evaluate(req, None, None)).data
    assert result["settings"]["factor_parameters"] == req.factor_parameters
    assert result["factor_definitions"]["alpha158_ma5"]["warmup_bars"] == 13
    assert result["reports"][0]["coverage"] == pytest.approx((145 - 12) / 145)
