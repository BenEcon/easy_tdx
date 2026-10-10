"""Independent unit qualification, real feed pairs, and request isolation."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import get_factor
from easy_tdx.factor.builtin.alpha158 import SPECS, compute_alpha158
from easy_tdx.factor.data import qualify_factor_fields
from easy_tdx.factor.research import cross_section_report
from easy_tdx.web.routers import research
from tests.unit.test_alpha158 import oracle

ROOT = Path(__file__).parents[1] / "fixtures/factor_units"
FILES = dict(line.split()[::-1] for line in (ROOT / "SHA256SUMS").read_text().splitlines())


def frozen(name):
    data = (ROOT / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == FILES[name]
    payload = json.loads(data)
    encoded = json.dumps(payload["bars"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(encoded.encode()).hexdigest() == payload["bars_sha256"]
    frame = pd.DataFrame(payload["bars"])
    frame["datetime"] = pd.to_datetime(frame["datetime"])
    frame.attrs["snapshot_metadata"] = {
        "source": "MAC",
        "actual_adjust": payload["adjust"],
        "category": "DAY" if payload["period"] == "DAILY" else payload["period"],
        "observed_at": payload["observed_at"],
    }
    return frame


def raw_sample():
    t = np.arange(80)
    frame = pd.DataFrame(
        {
            "datetime": pd.date_range("2025-01-01", periods=80),
            "open": 11.0,
            "high": 12.0,
            "low": 10.0,
            "close": 11.5,
            "vol": 100.0 + t,
            "amount": (100.0 + t) * 11.0,
        }
    )
    frame.attrs["snapshot_metadata"] = {"source": "MAC", "actual_adjust": "NONE", "category": "DAY"}
    return frame


@pytest.mark.parametrize("name", FILES)
def test_real_pairs_preserve_shares_and_all_40_volume_formula_oracles(name):
    frame = frozen(name)
    raw = frozen(name.rsplit("-", 1)[0] + "-NONE.json")
    original = frame.copy(deep=True)
    qualified = qualify_factor_fields(frame, raw)
    np.testing.assert_array_equal(qualified.volume, raw.vol)
    assert qualified.attrs["factor_data_contract"]["verified_rows"] == len(raw)
    for spec in SPECS.values():
        if "volume" not in spec.inputs:
            continue
        values = compute_alpha158(qualified, spec)
        for i in (spec.warmup - 1, len(qualified) - 1):
            np.testing.assert_allclose(
                values.iloc[i], oracle(qualified, spec.key, i), atol=2e-8, rtol=2e-8
            )
        prefix = qualify_factor_fields(frame.iloc[:100], raw.iloc[:100])
        pd.testing.assert_series_equal(values.iloc[:100], compute_alpha158(prefix, spec))
    pd.testing.assert_frame_equal(frame, original)
    if frame.attrs["snapshot_metadata"]["actual_adjust"] != "NONE":
        with pytest.raises(ValueError, match="复权 VWAP"):
            qualify_factor_fields(frame, raw, need_vwap=True)


def test_hand_calculated_vwap_flat_and_zero_volume_preserve_index():
    raw = raw_sample().iloc[:3].copy()
    raw.index = [4, 8, 9]
    raw.loc[8, ["open", "high", "low", "close"]] = 11.0
    raw.loc[9, ["vol", "amount"]] = 0.0
    result = qualify_factor_fields(raw, raw, need_vwap=True)
    assert result.index.tolist() == [4, 8, 9]
    assert result.vwap.iloc[:2].tolist() == [11.0, 11.0]
    assert pd.isna(result.vwap.iloc[2])
    assert result.volume.iloc[2] == 0
    assert result.attrs["factor_data_contract"]["zero_volume_rows"] == 1


@pytest.mark.parametrize(
    "fault",
    [
        "lots",
        "source",
        "adjust",
        "period",
        "dates",
        "duplicate",
        "zero_amount",
        "negative",
        "nan",
        "ohlc",
        "changed_volume",
        "all_zero",
    ],
)
def test_reject_bad_contract_without_modification(fault):
    raw = raw_sample()
    frame = raw.copy(deep=True)
    if fault == "lots":
        raw["vol"] /= 100
        frame["vol"] /= 100
    elif fault == "source":
        raw.attrs["snapshot_metadata"]["source"] = "TDX_STANDARD"
    elif fault == "adjust":
        raw.attrs["snapshot_metadata"]["actual_adjust"] = "QFQ"
    elif fault == "period":
        raw.attrs["snapshot_metadata"]["category"] = "WEEK"
    elif fault == "dates":
        raw.loc[0, "datetime"] -= pd.Timedelta(days=1)
    elif fault == "duplicate":
        raw.loc[1, "datetime"] = raw.loc[0, "datetime"]
    elif fault == "zero_amount":
        raw.loc[0, "amount"] = frame.loc[0, "amount"] = 0
    elif fault == "negative":
        raw.loc[0, "low"] = frame.loc[0, "low"] = -1
    elif fault == "nan":
        raw.loc[0, "vol"] = frame.loc[0, "vol"] = np.nan
    elif fault == "ohlc":
        raw.loc[0, "high"] = frame.loc[0, "high"] = 9
    elif fault == "changed_volume":
        frame.loc[0, "vol"] += 1
    elif fault == "all_zero":
        raw[["vol", "amount"]] = frame[["vol", "amount"]] = 0.0
    original = frame.copy(deep=True)
    with pytest.raises(ValueError):
        qualify_factor_fields(frame, raw)
    pd.testing.assert_frame_equal(original, frame)


@pytest.mark.asyncio
async def test_route_internal_fetch_is_bounded_and_price_only_does_not_fetch(monkeypatch):
    calls = []
    raw = raw_sample()
    frame = raw.copy()
    frame.attrs["snapshot_metadata"]["actual_adjust"] = "QFQ"
    frame[["open", "high", "low", "close"]] -= 1

    async def fetch(*args):
        calls.append(args[2:])
        return raw.copy()

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda df: df)

    async def load(names, df=frame, adjust="QFQ"):
        return await research._factor_fields(
            df, names, None, None, "SZ", "000001", "DAY", 80, adjust
        )

    assert "volume" not in await load(["alpha158_ma5"])
    assert calls == []
    qualified = await load(["alpha158_vma5", "alpha158_corr5"])
    assert calls == [("SZ", "000001", "DAY", 0, 80, "NONE")]
    assert qualified.attrs["factor_data_contract"]["instrument"] == "SZ:000001"
    assert qualified.volume.equals(raw.vol)
    calls.clear()
    await load(["alpha158_vma5"], raw, "NONE")
    assert calls == []


@pytest.mark.asyncio
async def test_missing_raw_failure_only_blocks_volume_and_reports_real_reason(monkeypatch):
    async def fail(*args):
        raise ValueError("QA 原始行情不可用")

    monkeypatch.setattr(research, "fetch_adjusted_bars", fail)
    frame = raw_sample()
    frame["volume"] = 123.0  # stale unverified upstream canonical field must be discarded
    req = research.FactorComputeRequest(
        market="SZ", code="000001", count=80, factors=["alpha158_ma5", "alpha158_vma5"]
    )
    qualified = await research._factor_fields(
        frame, req.factors, None, None, req.market, req.code, req.category, req.count, req.adjust
    )
    result = research._factor_result(req, qualified).data
    assert result["computed"] == ["alpha158_ma5"]
    assert "QA 原始行情不可用" in result["errors"]["alpha158_vma5"]
    assert "volume" not in qualified
    assert "volume" in frame
    assert get_factor("alpha158_vma5").inputs == ("volume",)


def test_pool_never_silently_drops_an_asset_with_bad_units():
    frame = qualify_factor_fields(raw_sample(), raw_sample())
    pool = {f"QA:{i}": frame.copy() for i in range(6)}
    pool["QA:3"] = pool["QA:3"].drop(columns="volume")
    pool["QA:3"].attrs["factor_input_errors"] = {"volume": "量额单位不一致"}
    result = cross_section_report(pool, ["alpha158_vma5", "alpha158_ma5"], 5, 3)
    assert result["assets"] == 6
    assert "QA:3 量额单位不一致" == result["errors"]["alpha158_vma5"]
    assert [row["name"] for row in result["reports"]] == ["alpha158_ma5"]


def test_contract_versions_in_fingerprints_and_no_source_mutation():
    raw = raw_sample()
    frame = qualify_factor_fields(raw, raw)
    assert "未核验" not in frame.attrs["snapshot_metadata"]["volume_policy"]
    assert "volume_policy" not in raw.attrs["snapshot_metadata"]
    req = research.FactorComputeRequest(
        market="SZ", code="000001", count=80, factors=["alpha158_vma5"], adjust="NONE"
    )
    before = research._factor_result(req, frame).data
    pool = {str(i): frame.copy() for i in range(5)}
    pool_before = cross_section_report(pool, req.factors, 5, 3)
    frame.attrs["factor_data_contract"]["version"] = "QA-next-version"
    assert (
        research._factor_result(req, frame).data["input_fingerprint"] != before["input_fingerprint"]
    )
    pool["0"] = frame
    assert (
        cross_section_report(pool, req.factors, 5, 3)["input_fingerprint"]
        != pool_before["input_fingerprint"]
    )
