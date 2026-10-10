"""Independent counts, synthetic route checks and hash-verified real index tapes."""

import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from easy_tdx.factor import get_factor
from easy_tdx.factor.benchmark import attach_benchmark, validate_benchmark_pool
from easy_tdx.factor.configuration import configure_factor
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.routers import research
from tests.unit.test_factor_archive import record


def pair(frame=None, length=120):
    if frame is None:
        t = np.arange(length)
        frame = pd.DataFrame(
            {
                "datetime": pd.bdate_range("2025-01-01", periods=length),
                "open": 10.0 + t * 0.01,
                "close": 10.0 + t * 0.01 + np.sin(t),
                "high": 20.0,
                "low": 5.0,
                "vol": 100.0,
                "amount": 1000.0,
            }
        )
    stock = frame.copy(deep=True)
    stock.attrs = copy.deepcopy(frame.attrs)
    stock["is_closed"] = True
    stock.attrs["snapshot_metadata"] = {
        **stock.attrs.get("snapshot_metadata", {}),
        "actual_adjust": stock.attrs.get("snapshot_metadata", {}).get("actual_adjust", "QFQ"),
        "category": "DAY",
        "bar_time": "end",
    }
    time = (
        stock["datetime"]
        if "datetime" in stock
        else stock["date"]
        if "date" in stock
        else stock.index
    )
    index = pd.DataFrame(
        {
            "datetime": list(time),
            "open": 3000.0,
            "close": 3000.0 + 10 * np.cos(np.arange(len(stock))),
            "is_closed": True,
        }
    )
    index.attrs["snapshot_metadata"] = {
        "category": "DAY",
        "bar_time": "end",
        "actual_adjust": "NONE",
        "requested_adjust": "NONE",
        "source": "MAC_INDEX",
        "instrument": {"kind": "index", "market": "SH", "code": "000001"},
    }
    return stock, index


def independent(frame, number, window):
    rows = frame[["open", "close", "benchmark_open", "benchmark_close"]].to_numpy()
    output = []
    for end in range(len(rows)):
        selected = rows[max(0, end - window + 1) : end + 1]
        if len(selected) != window or any(
            not np.isfinite(v) or v <= 0 for row in selected for v in row
        ):
            output.append(np.nan)
            continue
        down = sum(bc < bo for o, c, bo, bc in selected)
        matches = sum(
            (c > o and bc < bo) if number == 75 else ((c > o and bc > bo) or (c < o and bc < bo))
            for o, c, bo, bc in selected
        )
        output.append(
            matches / (down if number == 75 else window) if number != 75 or down else np.nan
        )
    return np.array(output)


def real_index(name="SH-000001-DAY.json"):
    from easy_tdx.factor.snapshot import restore_input

    root = Path(__file__).parents[1] / "fixtures/factor_benchmarks"
    hashes = dict(line.split()[::-1] for line in (root / "SHA256SUMS").read_text().splitlines())
    data = (root / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == hashes[name]
    return restore_input(json.loads(data)["snapshot"])


def real_equity(frame):
    from easy_tdx.web.market_data import checked_snapshot, closed_frame

    result = frame.copy(deep=True)
    meta = result.attrs["snapshot_metadata"]
    snapshot = checked_snapshot(
        result.to_dict("records"),
        meta["category"],
        source=meta["source"],
        requested_adjust=meta["actual_adjust"],
        actual_adjust=meta["actual_adjust"],
        bar_time="end",
        now=pd.Timestamp(meta["observed_at"]).tz_convert("Asia/Shanghai").tz_localize(None).to_pydatetime(),
    )
    result["is_closed"] = [row["is_closed"] for row in snapshot["data"]]
    result.attrs["snapshot_metadata"] = snapshot["metadata"]
    return closed_frame(result)


@pytest.mark.parametrize("number", [75, 182])
@pytest.mark.parametrize("symbol", ["SH:000001", "SZ:399001", "SH:000300", "SZ:399006"])
def test_real_frozen_independent_indices_multi_stock_default_oracle(number, symbol):
    from tests.unit.test_gtja191_vwap import long_frozen

    index = real_index(symbol.replace(":", "-") + "-DAY.json")
    factor = get_factor(f"gtja191_{number:03d}")()
    for filename in (
        "0-000001-DAILY-NONE.json",
        "0-300750-DAILY-NONE.json",
        "1-600036-DAILY-NONE.json",
    ):
        stock = real_equity(long_frozen(filename))
        frame = attach_benchmark(stock, index, symbol)
        values = factor.compute(frame)
        np.testing.assert_allclose(
            values, independent(frame, number, factor.spec.window), equal_nan=True
        )
        assert values.notna().sum() > 100


@pytest.mark.parametrize("number", [75, 182])
@pytest.mark.parametrize("adjust", ["NONE", "QFQ", "HFQ"])
def test_real_frozen_adjustments_and_minute_exact_alignment(number, adjust):
    from tests.unit.test_factor_data import frozen

    factor = get_factor(f"gtja191_{number:03d}")()
    for period in ("DAILY", "MIN_30"):
        stock = real_equity(frozen(f"0-300750-{period}-{adjust}.json"))
        index = real_index("SH-000001-" + ("DAY" if period == "DAILY" else period) + ".json")
        frame = attach_benchmark(stock, index, "SH:000001")
        values = factor.compute(frame)
        np.testing.assert_allclose(
            values, independent(frame, number, factor.spec.window), equal_nan=True
        )
        assert values.notna().any()


@pytest.mark.parametrize("number", [75, 182])
@pytest.mark.parametrize("window", [1, 3, 20, 50])
def test_independent_window_oracle_custom_warmup_and_prefix(number, window):
    stock, index = pair()
    factor = configure_factor(f"gtja191_{number:03d}", {"window": window})
    frame = attach_benchmark(stock, index, "SH:000001")
    values = factor.compute(frame)
    np.testing.assert_allclose(values, independent(frame, number, window), equal_nan=True)
    prefix = attach_benchmark(stock.iloc[:75], index.iloc[:75], "SH:000001")
    pd.testing.assert_series_equal(values.iloc[:75], factor.compute(prefix))
    assert values.iloc[: window - 1].isna().all()


@pytest.mark.parametrize("number", [75, 182])
def test_hand_ties_constant_zero_denominator_and_missing_window(number):
    stock, index = pair(length=6)
    stock["open"] = 10.0
    stock["close"] = [11.0, 9.0, 10.0, 11.0, 9.0, 10.0]
    index["open"] = 100.0
    index["close"] = [99.0, 99.0, 99.0, 101.0, 101.0, 100.0]
    frame = attach_benchmark(stock, index, "SH:000001")
    factor = configure_factor(f"gtja191_{number:03d}", {"window": 3})
    expected = (
        [np.nan, np.nan, 1 / 3, 0, 0, np.nan]
        if number == 75
        else [np.nan, np.nan, 1 / 3, 2 / 3, 1 / 3, 1 / 3]
    )
    np.testing.assert_allclose(factor.compute(frame), expected, equal_nan=True)
    index["close"] = 100.0
    flat = factor.compute(attach_benchmark(stock, index, "SH:000001"))
    assert flat.isna().all() if number == 75 else (flat.iloc[2:] == 0).all()
    missing = attach_benchmark(stock, index.drop(index=2), "SH:000001")
    assert factor.compute(missing).iloc[2:5].isna().all()
    bad = frame.copy()
    bad.loc[2, "close"] = 0
    assert factor.compute(bad).iloc[2:5].isna().all()


@pytest.mark.parametrize("number", [75, 182])
def test_formula_requires_independent_source_and_consistent_pair(number):
    stock, index = pair()
    factor = get_factor(f"gtja191_{number:03d}")()
    frame = attach_benchmark(stock, index, "SH:000001")
    frame.attrs.pop("factor_benchmark")
    with pytest.raises(ValueError, match="不完整"):
        factor.compute(frame)
    frame = attach_benchmark(stock, index, "SH:000001")
    frame.loc[0, "benchmark_close"] = 100.0
    with pytest.raises(ValueError, match="不一致"):
        factor.compute(frame)


@pytest.mark.asyncio
async def test_series_pool_fetch_once_archive_and_missing_index_does_not_hide_other_factors(
    monkeypatch,
):
    from easy_tdx.web import factor_benchmark

    stock, index = pair()
    stock_source = AsyncMock(return_value=stock)
    source = AsyncMock(return_value=index)
    monkeypatch.setattr(research, "fetch_adjusted_bars", stock_source)
    monkeypatch.setattr(factor_benchmark, "load_factor_benchmark", source)
    req = research.FactorComputeRequest(
        market="SZ",
        code="000001",
        factors=["gtja191_075", "gtja191_182", "alpha158_ma5"],
        benchmark="SH:000001",
    )
    frame = await research._series_frame(req, None, None)
    result = research._factor_result(req, frame).data
    assert not result["errors"]
    source.assert_awaited_once()
    payload = {
        "format": "factor-research-v1",
        "mode": "series",
        "title": "基准测试",
        "savedAt": "2026-10-10T10:00:00Z",
        "result": result,
    }
    validate_factor_archive(payload)
    original = copy.deepcopy(payload)
    source.reset_mock()
    new = research.recompute_factor_payload(record(payload))
    assert new["result"]["rows"] == result["rows"] and payload == original
    source.assert_not_awaited()
    pool_req = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(1, 6)],
        factors=req.factors,
        benchmark=req.benchmark,
    )
    frames = await research._evaluation_frames(pool_req, None, None)
    source.assert_awaited_once()
    assert len(frames) == 5
    evaluation = research.evaluation_result(pool_req, frames)
    assert not evaluation["errors"]
    validate_factor_archive({**payload, "mode": "evaluation", "result": evaluation})
    source.side_effect = ValueError("无基准数据")
    failed = research._factor_result(req, await research._series_frame(req, None, None)).data
    assert set(failed["errors"]) == {"gtja191_075", "gtja191_182"}
    assert failed["computed"] == ["alpha158_ma5"]
    validate_factor_archive({**payload, "result": failed})
    replay = research.recompute_factor_payload(record({**payload, "result": failed}))
    assert replay["result"]["errors"] == failed["errors"]


@pytest.mark.asyncio
async def test_normal_factor_does_not_fetch_benchmark_and_invalid_choice_is_rejected(monkeypatch):
    from easy_tdx.web import factor_benchmark

    stock, _ = pair()
    source = AsyncMock(side_effect=AssertionError("no auxiliary query"))
    monkeypatch.setattr(factor_benchmark, "load_factor_benchmark", source)
    monkeypatch.setattr(research, "fetch_adjusted_bars", AsyncMock(return_value=stock))
    request = dict(market="SZ", code="000001", factors=["alpha158_ma5"])
    await research._series_frame(research.FactorComputeRequest(**request), None, None)
    source.assert_not_called()
    for change in (
        {"factors": ["gtja191_075"]},
        {"benchmark": "SZ:000001"},
        {"benchmark": "SH:000001"},
    ):
        with pytest.raises(ValidationError):
            research.FactorComputeRequest(**{**request, **change})


def test_old_archive_migration_is_explicit_and_new_config_cannot_change_index():
    from tests.unit.test_factor_archive import payload

    old = payload()
    old["result"]["settings"].pop("benchmark")
    result = research.recompute_factor_payload(record(old))
    assert (
        result["recomputed_from"]["benchmark_migration"] == "legacy_no_benchmark_to_explicit_none"
    )
    assert result["result"]["settings"]["benchmark"] is None
    stock, index = pair()
    req = research.FactorComputeRequest(
        market="SZ", code="000001", factors=["gtja191_075"], benchmark="SH:000001"
    )
    current = research._factor_result(req, attach_benchmark(stock, index, "SH:000001")).data
    current["settings"]["benchmark"] = "SH:000300"
    with pytest.raises(ValueError, match="基准"):
        validate_factor_archive({**old, "result": current})


def test_pool_shared_index_snapshot_and_reject_mixed_versions_in_archive_and_recompute():
    from easy_tdx.factor.snapshot import freeze_input

    stock, index = pair()
    first = attach_benchmark(stock, index, "SH:000001")
    shorter = attach_benchmark(stock.iloc[2:], index, "SH:000001")
    validate_benchmark_pool([first, shorter], "SH:000001")
    changed = index.copy(deep=True)
    changed.loc[0, "close"] += 0.1
    second = attach_benchmark(stock, changed, "SH:000001")
    with pytest.raises(ValueError, match="不同版本"):
        validate_benchmark_pool([first, second], "SH:000001")
    req = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(1, 6)],
        factors=["gtja191_075"], benchmark="SH:000001",
    )
    frames = {f"SZ:00000{i}": first for i in range(1, 6)}
    result = research.evaluation_result(req, frames)
    payload = {
        "format": "factor-research-v1", "mode": "evaluation", "title": "同一基准",
        "savedAt": "2026-10-10T10:00:00Z", "result": result,
    }
    validate_factor_archive(payload)
    frames["SZ:000005"] = second
    with pytest.raises(ValueError, match="不同版本"):
        research.evaluation_result(req, frames)
    result["input_snapshots"][-1] = freeze_input("SZ:000005", second)
    with pytest.raises(ValueError, match="不同版本"):
        validate_factor_archive(payload)
    with pytest.raises(ValueError, match="不同版本"):
        research.recompute_factor_payload(record(payload))
