"""Synthetic FF3 data-contract tests, not claims of real provider coverage."""

import copy

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor.risk_inputs import (
    FIELDS,
    VERSION,
    attach_risk_inputs,
    freeze_risk_tape,
    validate_risk_inputs,
    validate_risk_pool,
    validate_risk_tape,
)
from easy_tdx.factor.snapshot import freeze_input, restore_input, snapshot_digest
from tests.unit.test_factor_benchmark import inputs


def tape():
    metadata = {
        "version": VERSION,
        "dataset_id": "synthetic-test-only",
        "provider": "unit-test",
        "source": "synthetic fixture, no external feed",
        "methodology": "constructed signed return triples; not estimated FF3",
        "universe": "synthetic CN_A",
        "licence": "test data",
        "market": "CN_A",
        "frequency": "DAY",
        "unit": "decimal_return",
        "mkt_definition": "market_excess_return",
        "vintage_at": "2026-01-10T16:00:00+08:00",
    }
    rows = [
        {
            "date": f"2026-01-{d:02d}",
            "available_at": f"2026-01-{d:02d}T15:00:00+08:00",
            "mkt": -0.01,
            "smb": 0.002,
            "hml": 0.0,
        }
        for d in (5, 7, 8)
    ]
    return freeze_risk_tape(metadata, rows)


def resign(value):
    value["digest"] = snapshot_digest(value)
    return value


def test_signed_values_exact_dates_no_fill_and_no_input_mutation():
    stock, _ = inputs()
    before = copy.deepcopy(stock)
    source = tape()
    before_tape = copy.deepcopy(source)
    result = attach_risk_inputs(stock, source)
    np.testing.assert_array_equal(result.risk_mkt, [-0.01, np.nan, -0.01, -0.01])
    assert result.attrs["factor_risk_inputs"]["states"] == [
        "ready",
        "missing_date",
        "ready",
        "ready",
    ]
    pd.testing.assert_frame_equal(stock, before)
    assert stock.attrs == before.attrs and source == before_tape
    result.attrs["factor_risk_inputs"]["snapshot"]["metadata"]["provider"] = "changed"
    assert source == before_tape


@pytest.mark.parametrize(
    "field,value",
    [
        ("unit", "percent"),
        ("frequency", "MIN_30"),
        ("market", "US"),
        ("mkt_definition", "index_close"),
        ("licence", ""),
        ("provider", ""),
        ("vintage_at", "2026-01-10"),
        ("vintage_at", "2026-01-06T16:00:00+08:00"),
        ("version", "unknown"),
    ],
)
def test_explicit_data_semantics(field, value):
    source = tape()
    source["metadata"][field] = value
    with pytest.raises(ValueError):
        validate_risk_tape(resign(source))


@pytest.mark.parametrize(
    "field,value",
    [
        ("date", "2026-02-30"),
        ("date", "20260105"),
        ("available_at", "2026-01-05T14:59:59+08:00"),
        ("available_at", "2026-01-05T15:00:00"),
        ("available_at", "NaT"),
        ("mkt", True),
        ("smb", "0.1"),
        ("hml", float("inf")),
    ],
)
def test_reject_invalid_cells(field, value):
    source = tape()
    source["rows"][0][field] = value
    # Nonfinite JSON is rejected by hashing itself as well as validation.
    with pytest.raises(ValueError):
        validate_risk_tape(resign(source))


def test_late_release_and_missing_not_published_as_observed_predictors():
    stock, _ = inputs()
    source = tape()
    source["rows"][1]["available_at"] = "2026-01-07T15:00:01+08:00"
    source["rows"][2]["smb"] = None
    result = attach_risk_inputs(stock, resign(source))
    assert result.attrs["factor_risk_inputs"]["states"] == [
        "ready",
        "missing_date",
        "not_available_at_close",
        "missing_value",
    ]
    assert result[list(FIELDS)].iloc[1:].isna().all().all()
    assert len(result.attrs["factor_risk_inputs"]["snapshot"]["rows"]) == 3


def test_dates_and_timezone_are_explicit_daily_not_minute_resampling():
    stock, _ = inputs()
    reference = attach_risk_inputs(stock, tape())
    stock.datetime = stock.datetime.dt.tz_localize("Asia/Shanghai") + pd.Timedelta(hours=15)
    stock.datetime = stock.datetime.dt.tz_convert("UTC")
    pd.testing.assert_frame_equal(
        attach_risk_inputs(stock, tape())[list(FIELDS)], reference[list(FIELDS)]
    )
    stock.datetime += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="日线时间"):
        attach_risk_inputs(stock, tape())


@pytest.mark.parametrize("change", ["duplicate", "reverse", "empty", "oversized", "extra"])
def test_bounds_and_revision_dates(change):
    source = tape()
    if change == "duplicate":
        source["rows"][1] = copy.deepcopy(source["rows"][0])
    elif change == "reverse":
        source["rows"].reverse()
    elif change == "empty":
        source["rows"] = []
    elif change == "oversized":
        source["rows"] *= 267
    else:
        source["metadata"]["arbitrary"] = "ignored?"
    with pytest.raises(ValueError):
        validate_risk_tape(resign(source))


def test_frozen_roundtrip_revalidates_even_with_recomputed_outer_hash():
    stock, _ = inputs()
    result = attach_risk_inputs(stock, tape())
    frozen = freeze_input("SZ:000001", result)
    restored = restore_input(frozen)
    pd.testing.assert_frame_equal(restored, result)
    assert restored.attrs == result.attrs
    column = frozen["columns"].index("risk_mkt")
    frozen["rows"][0][column] = 0.5
    with pytest.raises(ValueError, match="对齐值"):
        restore_input(resign(frozen))


def test_nested_risk_tape_and_orphan_columns_rejected():
    stock, _ = inputs()
    stock["risk_mkt"] = 0
    with pytest.raises(ValueError, match="契约"):
        freeze_input("SZ:000001", stock)
    with pytest.raises(ValueError, match="覆盖"):
        attach_risk_inputs(stock, tape())
    source = tape()
    source["snapshot"] = copy.deepcopy(source)
    with pytest.raises(ValueError):
        validate_risk_tape(source)


def test_pool_requires_identical_tape_not_only_same_provider():
    stock, _ = inputs()
    first = attach_risk_inputs(stock, tape())
    second = attach_risk_inputs(stock.iloc[1:].copy(), tape())
    validate_risk_pool([first, second])
    other = tape()
    other["rows"][0]["mkt"] = -0.02
    second = attach_risk_inputs(stock, resign(other))
    with pytest.raises(ValueError, match="版本不一致"):
        validate_risk_pool([first, second])
    with pytest.raises(ValueError, match="部分缺失"):
        validate_risk_pool([first, stock])
    validate_risk_pool([stock, stock.copy()])


def test_prefix_values_unchanged_by_later_source_rows():
    stock, _ = inputs()
    full = attach_risk_inputs(stock, tape())
    for n in range(1, len(stock) + 1):
        prefix = attach_risk_inputs(stock.iloc[:n].copy(), tape())
        pd.testing.assert_frame_equal(prefix[list(FIELDS)], full[list(FIELDS)].iloc[:n])
    validate_risk_inputs(stock)  # Legacy inputs unaffected.


@pytest.mark.parametrize("change", ["period", "unclosed", "adjust", "quality", "wrong_states"])
def test_stock_and_frozen_state_guards(change):
    stock, _ = inputs()
    if change == "wrong_states":
        stock = attach_risk_inputs(stock, tape())
        stock.attrs["factor_risk_inputs"]["states"][1] = "ready"
        with pytest.raises(ValueError, match="可得性"):
            validate_risk_inputs(stock)
        return
    if change == "period":
        stock.attrs["snapshot_metadata"]["category"] = "MIN_30"
    elif change == "adjust":
        stock.attrs["snapshot_metadata"].pop("actual_adjust")
    elif change == "quality":
        stock.attrs["snapshot_metadata"]["quality"] = {"errors": ["bad feed"]}
    else:
        stock.loc[stock.index[-1], "is_closed"] = False
    with pytest.raises(ValueError):
        attach_risk_inputs(stock, tape())


def test_research_rejects_mixed_tapes_before_computing_factors(monkeypatch):
    from easy_tdx.factor.research import cross_section_report

    stock, _ = inputs()
    first = attach_risk_inputs(stock, tape())
    other = tape()
    other["rows"][0]["mkt"] = 0.03
    second = attach_risk_inputs(stock, resign(other))
    data = {f"SZ:{i:06d}": first.copy() for i in range(5)}
    data["SZ:000004"] = second
    with pytest.raises(ValueError, match="版本不一致"):
        cross_section_report(data, ["momentum_20"], 1, 2)


@pytest.mark.parametrize("adjust", ["NONE", "QFQ", "HFQ"])
def test_real_equity_with_explicit_synthetic_risks_roundtrips_browser_json(adjust):
    import json
    import subprocess

    from tests.unit.test_factor_data import frozen
    from tests.unit.test_gtja191_benchmark import real_equity

    stock = real_equity(frozen(f"0-000001-DAILY-{adjust}.json"))
    meta = tape()["metadata"]
    meta["vintage_at"] = "2030-01-01T15:00:00+08:00"
    dates = pd.to_datetime(stock.datetime).dt.strftime("%Y-%m-%d")
    rows = [
        {"date": d, "available_at": d + "T15:00:00+08:00", "mkt": -0.01, "smb": 0.02, "hml": -0.0}
        for d in dates
    ]
    result = attach_risk_inputs(stock, freeze_risk_tape(meta, rows))
    saved = freeze_input("SZ:000001", result)
    browser = subprocess.run(
        [
            "node",
            "-e",
            "let s='';process.stdin.on('data',c=>s+=c);"
            "process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s))))",
        ],
        input=json.dumps(saved),
        text=True,
        capture_output=True,
        check=True,
    )
    restored = restore_input(json.loads(browser.stdout))
    pd.testing.assert_frame_equal(restored, result)
    assert restored.attrs == result.attrs


def test_ordinary_factor_archive_preserves_risk_tape_readonly(monkeypatch):
    from easy_tdx.web import factor_archive
    from easy_tdx.web.routers import research
    from tests.unit.test_factor_archive import payload
    from tests.unit.test_gtja191_benchmark import real_equity

    original = payload()
    result = original["result"]
    # The raw snapshot key is the existing public archive schema, not a new format.
    saved = result["input_snapshots"][0]
    frame = real_equity(restore_input(saved))
    metadata = tape()["metadata"]
    metadata["vintage_at"] = "2030-01-01T15:00:00+08:00"
    date = pd.Timestamp(frame.datetime.iloc[0]).strftime("%Y-%m-%d")
    source = freeze_risk_tape(
        metadata,
        [
            {
                "date": date,
                "available_at": date + "T15:00:00+08:00",
                "mkt": 0.01,
                "smb": -0.02,
                "hml": 0.005,
            }
        ],
    )
    result["input_snapshots"][0] = freeze_input(saved["symbol"], attach_risk_inputs(frame, source))
    before = copy.deepcopy(original)

    def forbidden(*args, **kwargs):
        raise AssertionError("readonly validation must not compute or fetch")

    monkeypatch.setattr(research, "_factor_result", forbidden)
    factor_archive.validate_factor_archive(original)
    assert original == before
