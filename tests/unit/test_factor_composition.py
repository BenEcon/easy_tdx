"""Hand-ranked composition, no fitting, complete coverage and frozen replay."""

import copy
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor.composition import SCORE_NAME, compose_scores, normalize_composition
from easy_tdx.factor.research import cross_section_report
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.research_archive import ArchiveError
from easy_tdx.web.routers import research
from easy_tdx.web.task_dispatch import dispatch_task
from tests.unit.test_factor_archive import record
from tests.unit.test_factor_tasks import round_trip, value  # noqa: F401


def config(names=("a", "b")):
    return {
        "method": "rank_centered",
        "components": [
            {"name": names[0], "weight": 3.0, "direction": 1},
            {"name": names[1], "weight": 1.0, "direction": -1},
        ],
    }


def matrices():
    template = pd.DataFrame(
        1.0, index=pd.date_range("2025-01-01", periods=3), columns=list("ABCDEF")
    )
    return template, {
        "a": pd.DataFrame([[1, 2, 2, 4, 5, 6]] * 3, index=template.index, columns=template.columns),
        "b": pd.DataFrame(
            [[60, 50, 40, 30, 20, 10]] * 3, index=template.index, columns=template.columns
        ),
    }


def test_hand_ranked_weights_ties_and_contributions():
    template, inputs = matrices()
    scores, details = compose_scores(inputs, template, config())
    # a centered ranks = [-1,-.4,-.4,.2,.6,1]; b = [1,.6,.2,-.2,-.6,-1].
    expected = np.array([-1, -0.45, -0.35, 0.2, 0.6, 1])
    np.testing.assert_allclose(scores, np.tile(expected, (3, 1)))
    assert details["effective_components"][0]["normalized_weight"] == 0.75
    assert details["latest"][1]["components"][0]["raw"] == 2
    assert details["latest"][1]["components"][0]["contribution"] == pytest.approx(-0.3)
    assert details["coverage"][0]["complete_assets"] == 6
    assert details["trade_eligible"] is False


def test_missing_component_and_small_intersection_are_not_zero_or_renormalized():
    template, inputs = matrices()
    inputs["a"].loc[template.index[0], "A"] = np.nan
    inputs["b"].loc[template.index[1], ["A", "B"]] = np.nan
    inputs["a"].loc[template.index[2], "B"] = np.nan
    scores, details = compose_scores(inputs, template, config())
    assert scores.iloc[0].notna().sum() == 5 and pd.isna(scores.iloc[0, 0])
    assert scores.iloc[1].isna().all()
    assert details["coverage"][1]["complete_assets"] == 4
    assert details["latest"][1]["score"] is None
    assert all(c["contribution"] is None for c in details["latest"][1]["components"])
    blocked, evidence = compose_scores({"a": inputs["a"]}, template, config())
    assert blocked.isna().all().all() and evidence["error"] == "组成因子未能计算：b"


def test_constant_component_remains_zero_with_original_weight_and_prefix_is_stable():
    template, inputs = matrices()
    inputs["a"] = inputs["a"].astype(float) * 0 + 1e-100
    scores, details = compose_scores(inputs, template, config())
    np.testing.assert_allclose(scores.iloc[0], [-0.25, -0.15, -0.05, 0.05, 0.15, 0.25])
    assert details["coverage"][0]["constant_components"] == ["a"]
    prefix, _ = compose_scores(
        {k: v.iloc[:2] for k, v in inputs.items()}, template.iloc[:2], config()
    )
    pd.testing.assert_frame_equal(prefix, scores.iloc[:2])


@pytest.mark.parametrize("bad", [0, -1, True, "3", np.nan, np.inf, 101, 0.001])
def test_invalid_weights_are_not_coerced(bad):
    selection = config()
    selection["components"][0]["weight"] = bad
    with pytest.raises(ValueError):
        normalize_composition(selection, ["a", "b"])


@pytest.mark.parametrize("bad", [True, "1", 1.0, 0, 2])
def test_invalid_directions_are_not_inferred(bad):
    selection = config()
    selection["components"][0]["direction"] = bad
    with pytest.raises(ValueError):
        normalize_composition(selection, ["a", "b"])


def test_selection_and_unsupported_transform_are_explicit():
    for selection, names in [
        (config(), ["a"]),
        (config(), ["a", "b", "c"]),
        (config(("a", "a")), ["a", "b"]),
        ({**config(), "method": "auto_best_ic"}, ["a", "b"]),
        ({**config(), "extra": 1}, ["a", "b"]),
    ]:
        with pytest.raises(ValueError):
            normalize_composition(selection, names)
    assert normalize_composition(config(), ["b", "a"])["components"][0]["name"] == "b"


def test_full_research_prefix_preprocessing_and_missing_members(value):  # noqa: F811
    names = ["momentum_20d", "volatility_20d"]
    frames = dict(zip(value.context["symbols"], value.frames, strict=True))
    combined = config(names)
    raw = cross_section_report(frames, names, 5, 3, composition=combined)
    transformed = cross_section_report(frames, names, 5, 3, "mad_zscore", composition=combined)
    assert raw["composition"] == transformed["composition"]
    short = {k: v.iloc[:60] for k, v in frames.items()}
    prefix = cross_section_report(short, names, 5, 3, composition=combined)
    assert raw["composition"]["scores"][:60] == prefix["composition"]["scores"]
    missing = {k: v.copy() for k, v in frames.items()}
    symbol = next(iter(missing))
    missing[symbol] = missing[symbol].iloc[:-1]
    report = cross_section_report(missing, names, 5, 3, composition=combined)
    assert len(report["composition"]["latest"]) == len(frames)
    assert report["composition"]["coverage"][-1]["complete_assets"] == len(frames) - 1
    assert all(r["score"] is None for r in report["composition"]["latest"])


def test_component_error_blocks_combination_but_keeps_single_factor_report(value):  # noqa: F811
    names = ["momentum_20d", "vol_surge"]
    frames = dict(zip(value.context["symbols"], value.frames, strict=True))
    symbol = next(iter(frames))
    frames[symbol] = frames[symbol].drop(columns="vol", errors="ignore")
    report = cross_section_report(frames, names, 5, 3, composition=config(names))
    assert [r["name"] for r in report["reports"]] == ["momentum_20d"]
    assert "vol_surge" in report["errors"]
    assert report["composition"]["error"] == "组成因子未能计算：vol_surge"
    assert all(v is None for r in report["composition"]["scores"] for v in r["values"])


def test_shared_task_archive_replay_directions_and_single_reports_unchanged(value):  # noqa: F811
    request = research.FactorEvaluationRequest.model_validate(value.request)
    names = ["momentum_20d", "volatility_20d"]
    # Existing test fixture supplies a complete frozen pool, not live market data.
    settings = {
        **value.request,
        "factors": names,
        "factor_parameters": {},
        "composition": config(names),
    }
    task = replace(value, request=settings)
    actual = dispatch_task(round_trip(task))
    frames = dict(zip(value.context["symbols"], value.frames, strict=True))
    plain = cross_section_report(
        frames,
        names,
        request.horizon,
        request.groups,
        request.preprocess,
        horizons=request.horizons,
        validation=request.validation.model_dump() if request.validation else None,
    )
    assert actual["reports"] == plain["reports"]
    assert actual["horizon_comparison"] == plain["horizon_comparison"]
    assert actual["input_fingerprint"] != plain["input_fingerprint"]
    combined = actual["composition"]
    assert combined["reports"][0]["name"] == SCORE_NAME
    assert combined["horizon_comparison"]["horizons"] == request.horizons
    payload = {
        "format": "factor-research-v1",
        "mode": "evaluation",
        "title": "固定权重组合",
        "savedAt": "2026-10-10T00:00:00Z",
        "result": actual,
    }
    validate_factor_archive(payload)
    original = copy.deepcopy(payload)
    replay = research.recompute_factor_payload(record(payload))
    assert replay["result"]["composition"] == combined and payload == original
    # Direction changes must affect the fingerprint; no return-dependent sign fitting.
    changed = copy.deepcopy(settings)
    changed["composition"]["components"][0]["direction"] = -1
    other = dispatch_task(replace(task, request=changed))
    assert other["input_fingerprint"] != actual["input_fingerprint"]
    for mutation in (
        "weight",
        "missing_score",
        "contribution",
        "missing_config",
        "trading",
        "date",
    ):
        bad = copy.deepcopy(payload)
        c = bad["result"]["composition"]
        if mutation == "weight":
            c["effective_components"][0]["normalized_weight"] = 0.9
        elif mutation == "missing_score":
            c["scores"].pop()
        elif mutation == "contribution":
            c["latest"][0]["components"][0]["contribution"] = 9
        elif mutation == "missing_config":
            bad["result"]["settings"].pop("composition")
        elif mutation == "trading":
            c["trade_eligible"] = True
        else:
            c["coverage"][0]["date"] = "2000-01-01"
        with pytest.raises(ArchiveError):
            validate_factor_archive(bad)
