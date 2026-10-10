"""Unadjusted VWAP integration, never an adjusted-close proxy."""

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from easy_tdx.factor import get_factor
from easy_tdx.factor.catalog import availability_reason, describe_factor
from easy_tdx.factor.data import qualify_factor_fields
from easy_tdx.factor.research import cross_section_report
from easy_tdx.web.routers import research
from tests.unit.test_factor_data import FILES, frozen, raw_sample


@pytest.mark.parametrize("filename", [name for name in FILES if name.endswith("-NONE.json")])
@pytest.mark.asyncio
async def test_real_vwap_compute_route_has_exact_amount_share_price_definition(
    filename, monkeypatch
):
    raw = frozen(filename)
    before = raw.copy(deep=True)
    calls = []

    async def fetch(*args):
        calls.append(args[2:])
        return raw.copy()

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda df: df)
    market, code, category = (
        ("SH" if filename.startswith("1-") else "SZ"),
        filename.split("-")[1],
        raw.attrs["snapshot_metadata"]["category"],
    )
    req = research.FactorComputeRequest(
        market=market,
        code=code,
        category=category,
        count=160,
        adjust="NONE",
        factors=["alpha158_vwap0"],
    )
    result = (await research.factor_compute(req, None, None)).data
    assert calls == [(market, code, category, 0, 160, "NONE")]
    assert result["errors"] == {} and result["count"] == len(raw)
    expected = raw.amount.to_numpy() / raw.vol.to_numpy() / raw.close.to_numpy()
    np.testing.assert_allclose([row["alpha158_vwap0"] for row in result["rows"]], expected)
    assert result["factor_data_contract"]["vwap_method"] == "unadjusted_amount_div_actual_shares"
    assert result["factor_data_contract"]["instrument"] == f"{market}:{code}"
    prefix = qualify_factor_fields(raw.iloc[:80], raw.iloc[:80], need_vwap=True)
    np.testing.assert_allclose(get_factor("alpha158_vwap0")().compute(prefix), expected[:80])
    pd.testing.assert_frame_equal(raw, before)


@pytest.mark.asyncio
@pytest.mark.parametrize("adjust", ["QFQ", "HFQ"])
async def test_adjusted_vwap_blocked_without_extra_fetch_but_volume_still_qualified(
    adjust, monkeypatch
):
    raw = raw_sample()
    frame = raw.copy()
    frame.attrs["snapshot_metadata"]["actual_adjust"] = adjust
    frame["vwap"] = 999.0  # An upstream canonical field must never bypass qualification.
    calls = []

    async def fetch(*args):
        calls.append(args[-1])
        return raw.copy()

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda df: df)
    for names in [["alpha158_vwap0", "alpha158_ma5"], ["alpha158_vwap0", "alpha158_vma5"]]:
        req = research.FactorComputeRequest(
            market="SZ", code="000001", adjust=adjust, factors=names
        )
        qualified = await research._factor_fields(
            frame, names, None, None, "SZ", "000001", "DAY", 80, adjust
        )
        result = research._factor_result(req, qualified).data
        assert "仅支持不复权" in result["errors"]["alpha158_vwap0"]
        assert result["computed"] == [names[1]]
        assert "vwap" not in qualified
        assert calls == ([] if names[1] == "alpha158_ma5" else ["NONE"])
    assert "vwap" in frame


@pytest.mark.asyncio
async def test_zero_volume_missing_and_bad_units_never_fallback_to_price(monkeypatch):
    frame = raw_sample()
    frame.loc[10, ["vol", "amount"]] = 0.0
    frame["vwap"] = 777.0
    req = research.FactorComputeRequest(
        market="SZ", code="000001", adjust="NONE", factors=["alpha158_vwap0", "alpha158_ma5"]
    )
    qualified = await research._factor_fields(
        frame, req.factors, None, None, "SZ", "000001", "DAY", 80, "NONE"
    )
    result = research._factor_result(req, qualified).data
    assert result["rows"][10]["alpha158_vwap0"] is None
    assert result["diagnostics"]["alpha158_vwap0"]["valid_count"] == 79
    frame.loc[11, "amount"] *= 100
    qualified = await research._factor_fields(
        frame, req.factors, None, None, "SZ", "000001", "DAY", 80, "NONE"
    )
    result = research._factor_result(req, qualified).data
    assert result["computed"] == ["alpha158_ma5"]
    assert "单位或上游行情不一致" in result["errors"]["alpha158_vwap0"]
    assert "vwap" not in qualified


@pytest.mark.asyncio
async def test_pool_route_accepts_none_exports_contract_and_never_drops_bad_asset(monkeypatch):
    calls = []
    bad = [False]

    async def fetch(*args):
        calls.append(args[2:])
        frame = raw_sample()
        offset = int(args[3]) / 20
        for field in ["open", "close", "high", "low"]:
            frame[field] += offset
        frame["amount"] += frame.vol * offset
        if bad[0] and args[3] == "000003":
            frame["amount"] *= 100
        return frame

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda df: df)
    req = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"{i:06}"} for i in range(1, 6)],
        factors=["alpha158_vwap0", "alpha158_ma5"],
        count=80,
        adjust="NONE",
        groups=3,
    )
    result = (await research.factor_evaluate(req, None, None)).data
    assert len(calls) == 5 and all(call[-1] == "NONE" for call in calls)
    assert result["assets"] == 5 and result["errors"] == {}
    assert result["settings"]["adjust"] == "NONE"
    assert result["reports"][0]["coverage"] == 1
    assert all(
        item["factor_data_contract"]["vwap_method"] == "unadjusted_amount_div_actual_shares"
        for item in result["provenance"]
    )
    bad[0] = True
    result = (await research.factor_evaluate(req, None, None)).data
    assert result["assets"] == 5
    assert "SZ:000003" in result["errors"]["alpha158_vwap0"]
    assert [r["name"] for r in result["reports"]] == ["alpha158_ma5"]
    for adjust in ["QFQ", "HFQ"]:
        with pytest.raises(ValidationError, match="仅支持不复权"):
            research.FactorEvaluationRequest(**{**req.model_dump(), "adjust": adjust})


def test_conditional_catalog_and_direct_pool_cannot_mislabel_adjustment():
    definition = describe_factor(get_factor("alpha158_vwap0"))
    assert definition["status"] == "conditional"
    assert not availability_reason(definition, "NONE")
    assert availability_reason(definition, "QFQ")
    frame = qualify_factor_fields(raw_sample(), raw_sample(), need_vwap=True)
    pool = {str(i): frame.copy() for i in range(5)}
    pool["2"].attrs["snapshot_metadata"]["actual_adjust"] = "QFQ"
    result = cross_section_report(pool, ["alpha158_vwap0"], 5, 3)
    assert "2 VWAP" in result["errors"]["alpha158_vwap0"]
    assert result["assets"] == 5 and result["reports"] == []
