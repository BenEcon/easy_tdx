import copy
import json

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from easy_tdx.factor import (
    FACTORY_REGISTRY,
    Factor,
    FactorEngine,
    PanelFactor,
    get_factor,
    list_factors,
)
from easy_tdx.factor.research import cross_section_report, prepare_frame
from easy_tdx.web.routers import research


class Score(Factor):
    name = "qa_score"
    category = "technical"
    description = "test"
    inputs = ("open",)

    def compute(self, df):
        return df["open"]


@pytest.fixture
def sample(monkeypatch):
    monkeypatch.setitem(FACTORY_REGISTRY, Score.name, Score)
    dates = pd.date_range("2025-01-01", periods=90, freq="B")
    return {
        f"SZ:{i:06}": pd.DataFrame(
            {
                "datetime": dates,
                "open": float(i),
                "close": 100 * (1 + i / 1000) ** np.arange(90),
                "vol": 100.0,
                "amount": 1000.0,
            }
        )
        for i in range(1, 7)
    }


def test_known_rank_ic_layers_and_no_tail_zero(sample):
    original = copy.deepcopy(sample)
    result = cross_section_report(sample, ["qa_score"], 5, 3)
    r = result["reports"][0]
    assert r["observations"] == 85
    assert r["rank_ic_mean"] == pytest.approx(1)
    assert r["positive_rate"] == 1
    assert r["rank_ic_ir"] is None
    assert r["layer_means"][0] < r["layer_means"][1] < r["layer_means"][2]
    assert r["spread"] == pytest.approx(r["layer_means"][-1] - r["layer_means"][0])
    assert all(row["rank_ic"] is None for row in r["daily"][-5:])
    assert all(row["rolling_rank_ic"] is None for row in r["daily"][:19])
    assert result["trade_eligible"] is False
    json.dumps(result, allow_nan=False)
    for code in original:
        pd.testing.assert_frame_equal(sample[code], original[code])


def test_labels_do_not_use_unfinished_future(sample):
    prefix = {key: frame.iloc[:70] for key, frame in sample.items()}
    early = cross_section_report(prefix, ["qa_score"], 5, 3)["reports"][0]["daily"]
    late = cross_section_report(sample, ["qa_score"], 5, 3)["reports"][0]["daily"]
    assert early[:65] == late[:65]
    assert all(row["n"] == 0 for row in early[-5:])


def test_missing_internal_bar_excludes_whole_label_window(sample):
    for key in list(sample)[:2]:
        sample[key] = sample[key].drop(index=30)
    rows = cross_section_report(sample, ["qa_score"], 5, 3)["reports"][0]["daily"]
    assert all(row["rank_ic"] is None for row in rows[25:31])
    assert rows[24]["rank_ic"] == pytest.approx(1)
    assert rows[31]["rank_ic"] == pytest.approx(1)


def test_constant_values_null_not_zero_or_arbitrary_groups(sample):
    for frame in sample.values():
        frame["open"] = 1.0
    result = cross_section_report(sample, ["qa_score"], 1, 5)
    r = result["reports"][0]
    assert r["rank_ic_mean"] is None and r["rank_ic_ir"] is None
    assert r["layer_means"] == [None] * 5 and r["spread"] is None
    assert r["positive_rate"] is None
    assert result["redundancy"][0]["correlation"] is None


def test_ties_not_forced_into_groups(sample):
    for i, frame in enumerate(sample.values()):
        frame["open"] = float(i // 2)
    r = cross_section_report(sample, ["qa_score"], 1, 5)["reports"][0]
    assert r["rank_ic_mean"] > 0
    assert r["spread"] is None
    assert r["diagnostics"]["因子取值过少，不能完整分层"] == 89


def test_preprocessing_uses_same_day_only_and_handles_zero_mad(sample):
    for i, frame in enumerate(sample.values()):
        frame["open"] = 1.0 if i < 5 else 100.0
    raw = cross_section_report(sample, ["qa_score"], 1, 3)
    clean = cross_section_report(sample, ["qa_score"], 1, 3, "mad_zscore")
    assert clean["reports"][0]["rank_ic_mean"] == pytest.approx(raw["reports"][0]["rank_ic_mean"])
    assert clean["latest"][-1]["qa_score"] > 0


@pytest.mark.parametrize("mutation", ["duplicate", "reverse", "zero", "nan"])
def test_invalid_market_grid_fails(sample, mutation):
    frame = next(iter(sample.values())).copy()
    if mutation == "duplicate":
        frame.loc[1, "datetime"] = frame.loc[0, "datetime"]
    if mutation == "reverse":
        frame = frame.iloc[::-1]
    if mutation == "zero":
        frame.loc[0, "close"] = 0
    if mutation == "nan":
        frame.loc[0, "close"] = np.nan
    with pytest.raises(ValueError):
        prepare_frame(frame)


def test_failed_factor_is_explicit_and_valid_factor_survives(sample):
    result = cross_section_report(sample, ["qa_score", "not_a_factor"], 1, 3)
    assert "not_a_factor" in result["errors"]
    assert [r["name"] for r in result["reports"]] == ["qa_score"]


def test_request_rejects_unknown_duplicate_and_unavailable_factors(sample):
    body = {
        "stocks": [{"market": "SZ", "code": f"{i:06}"} for i in range(1, 6)],
        "factors": ["qa_score"],
    }
    assert research.FactorEvaluationRequest(**body).horizon == 5
    for factors in [["missing"], ["pe_ratio"], ["chanlun_mmd"], ["qa_score", "qa_score"]]:
        with pytest.raises(ValidationError):
            research.FactorEvaluationRequest(**dict(body, factors=factors))
    with pytest.raises(ValidationError):
        research.FactorEvaluationRequest(**dict(body, stocks=body["stocks"][:4]))
    with pytest.raises(ValidationError):
        research.FactorEvaluationRequest(**dict(body, horizon=0))


@pytest.mark.asyncio
async def test_route_checks_every_asset_and_records_provenance(sample, monkeypatch):
    async def fetch(_client, _mac, market, code, *args):
        frame = sample[f"{market}:{code}"].copy()
        frame.attrs["snapshot_metadata"] = {"actual_adjust": "QFQ", "quality": {"status": "ok"}}
        return frame

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda frame: frame)
    req = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"{i:06}"} for i in range(1, 6)], factors=["qa_score"]
    )
    result = await research.factor_evaluate(req, None, None)
    assert len(result.data["provenance"]) == 5
    assert result.data["settings"]["count"] == req.count
    assert result.data["settings"]["stocks"] == [s.model_dump() for s in req.stocks]
    assert result.data["settings"]["category"] == "DAY"
    sample["SZ:000003"] = sample["SZ:000003"].iloc[:10]
    with pytest.raises(ValueError, match="000003"):
        await research.factor_evaluate(req, None, None)


def test_chanlun_failure_never_becomes_valid_zero(monkeypatch, sample):
    from easy_tdx.chanlun.analyser import ChanlunAnalyser
    from easy_tdx.factor.builtin.chanlun import ChanlunBiDir, ChanlunMMD

    def fail(*args):
        raise ValueError("test failure")

    monkeypatch.setattr(ChanlunAnalyser, "process_klines", fail)
    for factor in (ChanlunBiDir(), ChanlunMMD()):
        with pytest.raises(RuntimeError, match="不能以 0"):
            factor.compute(next(iter(sample.values())))


@pytest.mark.parametrize(
    "name", [f["name"] for f in list_factors() if f["category"] not in {"value", "chanlun"}]
)
def test_every_eligible_builtin_preserves_dates_and_causal_prefix(name):
    t = np.arange(100, dtype=float)
    close = 30 + 0.01 * t + np.sin(t / 5)
    frame = pd.DataFrame(
        {
            "close": close,
            "high": close + 1,
            "low": close - 1,
            "open": close - 0.2,
            "vol": 1000 + t * t,
            # Synthetic canonical fields, not a production feed conversion.
            "volume": 100000 + 100 * t * t,
            "vwap": close - 0.1,
            "amount": 10000 + t * t,
        },
        index=pd.date_range("2025-01-01", periods=100, freq="B"),
    )
    factor = get_factor(name)()
    if isinstance(factor, PanelFactor):
        with pytest.raises(ValueError, match="整池截面"):
            factor.compute(frame)
        other = frame.copy()
        other["open"] = other["close"] + 0.1
        pool = {"A": frame, "B": other}
        engine = FactorEngine()
        values = engine.compute_matrix(pool, factor)
        assert values.index.equals(frame.index)
        if getattr(getattr(factor, "spec", None), "family", "").startswith("panel_"):
            from tests.unit.test_gtja191_panel_compound import DEFAULTS, independent

            # This two-stock fixture has constant cross-sectional volume ranks;
            # rank correlations are undefined, not finite zeros. 184 also needs
            # 201 observations. Check exact expected missingness and values.
            oracle_pool = {s: f.rename_axis("datetime").reset_index() for s, f in pool.items()}
            number = int(name[-3:])
            np.testing.assert_allclose(
                values,
                independent(oracle_pool, number, DEFAULTS[number]),
                rtol=2e-8,
                atol=2e-10,
                equal_nan=True,
            )
        else:
            assert values.iloc[65:].notna().all().all()
        pd.testing.assert_frame_equal(
            values.iloc[:75],
            engine.compute_matrix({s: f.iloc[:75] for s, f in pool.items()}, factor),
        )
        return
    values = factor.compute(frame)
    assert values.index.equals(frame.index)
    if name == "gtja191_128":
        # An entirely rising 14-bar window has no negative money flow:
        # the published U / D expression is undefined, not automatically 100.
        typical = (frame.high + frame.low + frame.close) / 3
        for i in range(65, len(frame)):
            negative_flow = sum(
                typical.iloc[j] * frame.volume.iloc[j]
                for j in range(i - 13, i + 1)
                if typical.iloc[j] < typical.iloc[j - 1]
            )
            assert bool(pd.isna(values.iloc[i])) == (negative_flow == 0)
        assert values.iloc[65:].isna().any()
        assert values.iloc[65:].notna().any()
    elif name == "gtja191_180":
        # 7-bar delta followed by 60-bar rank requires 67 input rows,
        # including when the currently selected branch is negative volume.
        assert values.iloc[:66].isna().all()
        assert values.iloc[66:].notna().all()
    else:
        assert values.iloc[65:].notna().all()
    pd.testing.assert_series_equal(values.iloc[:75], factor.compute(frame.iloc[:75]))


def test_builtin_warmup_is_not_zero():
    frame = pd.DataFrame({"close": np.linspace(10, 15, 70)})
    assert get_factor("macd_hist_signal")().compute(frame).iloc[:19].isna().all()
    assert get_factor("win_rate_20d")().compute(frame).iloc[:20].isna().all()
