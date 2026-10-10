"""Independent paired-input checks; no synthetic fixture is claimed as real feed."""

import copy
import json

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor.benchmark import attach_benchmark, validate_benchmark
from easy_tdx.factor.snapshot import freeze_input, restore_input, snapshot_digest


def inputs(category="DAY"):
    dates = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"])
    stock = pd.DataFrame(
        {
            "datetime": dates,
            "open": [10.0, 11.0, 12.0, 13.0],
            "close": [11.0, 12.0, 13.0, 14.0],
            "is_closed": True,
        }
    )
    stock.index = [2, 4, 6, 8]
    stock.attrs["snapshot_metadata"] = {
        "category": category,
        "bar_time": "end",
        "source": "MAC",
        "actual_adjust": "QFQ",
    }
    index = pd.DataFrame(
        {
            "datetime": dates[[0, 2, 3]],
            "open": [3000.0, 3020.0, 3010.0],
            "close": [3010.0, 3015.0, 3010.0],
            "is_closed": True,
        }
    )
    index.attrs["snapshot_metadata"] = {
        "category": category,
        "bar_time": "end",
        "source": "MAC_INDEX",
        "actual_adjust": "NONE",
        "requested_adjust": "NONE",
        "instrument": {"kind": "index", "market": "SH", "code": "000001"},
    }
    return stock, index


def test_exact_missing_date_alignment_preserves_stock_and_original_index():
    stock, index = inputs()
    before_stock, before_index = copy.deepcopy(stock), copy.deepcopy(index)
    result = attach_benchmark(stock, index, "SH:000001")
    assert result.index.tolist() == [2, 4, 6, 8]
    np.testing.assert_array_equal(result.benchmark_open, [3000.0, np.nan, 3020.0, 3010.0])
    np.testing.assert_array_equal(result.benchmark_close, [3010.0, np.nan, 3015.0, 3010.0])
    assert result.attrs["factor_benchmark"]["matched_rows"] == 3
    assert result.attrs["factor_benchmark"]["missing_rows"] == 1
    pd.testing.assert_frame_equal(stock, before_stock)
    pd.testing.assert_frame_equal(index, before_index)
    assert stock.attrs == before_stock.attrs and index.attrs == before_index.attrs
    validate_benchmark(result)
    result.attrs["snapshot_metadata"]["source"] = "modified"
    assert stock.attrs["snapshot_metadata"]["source"] == "MAC"


@pytest.mark.parametrize("adjust", ["NONE", "QFQ", "HFQ"])
def test_equity_adjust_does_not_adjust_benchmark_and_roundtrip_retains_all_input(adjust):
    stock, index = inputs()
    stock.attrs["snapshot_metadata"]["actual_adjust"] = adjust
    result = attach_benchmark(stock, index, "SH:000001")
    frozen = freeze_input("SZ:000001", result)
    restored = restore_input(json.loads(json.dumps(frozen, allow_nan=False)))
    pd.testing.assert_frame_equal(result, restored)
    assert result.attrs == restored.attrs
    assert (
        restored.attrs["factor_benchmark"]["snapshot"]["attrs"]["snapshot_metadata"][
            "actual_adjust"
        ]
        == "NONE"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "stock_identity",
        "stock_source",
        "wrong_market",
        "wrong_code",
        "unknown_symbol",
        "adjust",
        "requested_adjust",
        "period",
        "start_time",
        "open_bar",
        "missing_closed",
        "string_closed",
        "duplicate",
        "unsorted",
        "no_overlap",
        "zero",
        "negative",
        "infinite",
        "nan",
        "text_price",
        "boolean_price",
        "missing_price",
        "empty",
        "too_long",
    ],
)
def test_invalid_index_never_silently_substitutes_stock_or_repairs(fault):
    stock, index = inputs()
    meta = index.attrs["snapshot_metadata"]
    symbol = "SH:000001"
    if fault == "stock_identity":
        meta["instrument"]["kind"] = "stock"
    elif fault == "stock_source":
        meta["source"] = "MAC"
    elif fault == "wrong_market":
        meta["instrument"]["market"] = "SZ"
    elif fault == "wrong_code":
        meta["instrument"]["code"] = "000300"
    elif fault == "unknown_symbol":
        symbol = "SZ:000001"
    elif fault == "adjust":
        meta["actual_adjust"] = "QFQ"
    elif fault == "requested_adjust":
        meta["requested_adjust"] = "QFQ"
    elif fault == "period":
        meta["category"] = "WEEK"
    elif fault == "start_time":
        meta["bar_time"] = "start"
    elif fault == "open_bar":
        index.loc[1, "is_closed"] = False
    elif fault == "missing_closed":
        index = index.drop(columns="is_closed")
    elif fault == "string_closed":
        index["is_closed"] = "true"
    elif fault == "duplicate":
        index.loc[1, "datetime"] = index.loc[0, "datetime"]
    elif fault == "unsorted":
        index = index.iloc[::-1]
    elif fault == "no_overlap":
        index["datetime"] += pd.Timedelta(days=20)
    elif fault in ("zero", "negative", "infinite", "nan"):
        index.loc[1, "close"] = {"zero": 0.0, "negative": -1.0, "infinite": np.inf, "nan": np.nan}[
            fault
        ]
    elif fault == "text_price":
        index["close"] = index.close.astype(str)
    elif fault == "boolean_price":
        index["close"] = True
    elif fault == "missing_price":
        index = index.drop(columns="open")
    elif fault == "empty":
        index = index.iloc[:0]
    elif fault == "too_long":
        index = pd.concat([index] * 300, ignore_index=True)
    with pytest.raises(ValueError):
        attach_benchmark(stock, index, symbol)


def test_minutes_align_exact_end_and_timezone_not_nearest_or_trading_date():
    stock, index = inputs("MIN_30")
    stock["datetime"] = pd.to_datetime(
        ["2026-01-05 10:00", "2026-01-05 10:30", "2026-01-05 11:00", "2026-01-05 11:30"]
    )
    index["datetime"] = pd.to_datetime(
        ["2026-01-05 02:00Z", "2026-01-05 03:00Z", "2026-01-05 03:30Z"]
    )
    result = attach_benchmark(stock, index, "SH:000001")
    np.testing.assert_array_equal(result.benchmark_open, [3000.0, np.nan, 3020.0, 3010.0])
    index["datetime"] += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="相同观测时间"):
        attach_benchmark(stock, index, "SH:000001")


def test_prefix_alignment_and_snapshot_identity_change_without_altering_past_values():
    stock, index = inputs()
    full = attach_benchmark(stock, index, "SH:000001")
    short = attach_benchmark(stock.iloc[:3], index.iloc[:2], "SH:000001")
    np.testing.assert_array_equal(full.benchmark_close.iloc[:3], short.benchmark_close)
    index.loc[2, "close"] = 3200.0
    updated = attach_benchmark(stock, index, "SH:000001")
    np.testing.assert_array_equal(updated.benchmark_close.iloc[:3], short.benchmark_close)
    assert freeze_input("SZ:000001", full)["digest"] != freeze_input("SZ:000001", updated)["digest"]


@pytest.mark.parametrize(
    "fault",
    [
        "aligned_value",
        "filled_gap",
        "missing_field",
        "missing_contract",
        "name",
        "symbol",
        "nested_symbol",
        "count",
        "boolean_count",
        "alignment",
        "nested_contract",
        "nested_columns",
        "nested_raw",
        "missing_snapshot",
        "extra_key",
    ],
)
def test_even_rehashed_snapshot_cannot_hide_inconsistent_pair(fault):
    stock, index = inputs()
    saved = freeze_input("SZ:000001", attach_benchmark(stock, index, "SH:000001"))
    contract = saved["attrs"]["factor_benchmark"]
    nested = contract["snapshot"]
    if fault == "aligned_value":
        saved["rows"][0][-1] = 999.0
    elif fault == "filled_gap":
        saved["rows"][1][-1] = 3010.0
    elif fault == "missing_field":
        saved["columns"].pop()
        saved["dtypes"].pop()
        for row in saved["rows"]:
            row.pop()
    elif fault == "missing_contract":
        saved["attrs"].pop("factor_benchmark")
    elif fault == "name":
        contract["name"] = "假指数"
    elif fault == "symbol":
        contract["symbol"] = "SZ:399001"
    elif fault == "nested_symbol":
        nested["symbol"] = "SZ:399001"
    elif fault == "count":
        contract["missing_rows"] = 0
    elif fault == "boolean_count":
        contract["missing_rows"] = True
    elif fault == "alignment":
        contract["alignment"] = "forward_fill"
    elif fault == "nested_contract":
        nested["attrs"]["factor_benchmark"] = copy.deepcopy(contract)
    elif fault == "nested_columns":
        nested["columns"][1] = "benchmark_open"
    elif fault == "nested_raw":
        nested["rows"][0][2] = 999.0
    elif fault == "missing_snapshot":
        contract.pop("snapshot")
    elif fault == "extra_key":
        contract["inferred"] = True
    nested["digest"] = snapshot_digest(nested)
    saved["digest"] = snapshot_digest(saved)
    with pytest.raises(ValueError):
        restore_input(saved)


def test_existing_benchmark_never_overwritten_or_old_archives_required_to_add_one():
    stock, index = inputs()
    old = freeze_input("SZ:000001", stock)
    assert "factor_benchmark" not in old["attrs"]
    pd.testing.assert_frame_equal(restore_input(old), stock)
    new = attach_benchmark(stock, index, "SH:000001")
    with pytest.raises(ValueError, match="覆盖"):
        attach_benchmark(new, index, "SH:000001")


def test_zero_or_nan_index_cannot_become_a_legitimate_flat_day():
    stock, index = inputs()
    index.loc[1, "close"] = 0
    with pytest.raises(ValueError, match="无效值"):
        attach_benchmark(stock, index, "SH:000001")
    index.loc[1, "close"] = index.loc[1, "open"]
    result = attach_benchmark(stock, index, "SH:000001")
    assert result.benchmark_close.iloc[2] == result.benchmark_open.iloc[2]


@pytest.mark.parametrize("timezone", ["UTC", "Asia/Shanghai"])
def test_timezone_columns_and_index_lossless_roundtrip(timezone):
    stock, index = inputs("MIN_30")
    for frame in (stock, index):
        frame["datetime"] = frame.datetime.dt.tz_localize("Asia/Shanghai").dt.tz_convert(timezone)
        frame.index = pd.DatetimeIndex(frame.datetime, name="timestamp")
    paired = attach_benchmark(stock, index, "SH:000001")
    restored = restore_input(freeze_input("SZ:000001", paired))
    pd.testing.assert_frame_equal(paired, restored)


def test_task_transport_and_cache_hash_include_same_valued_distinct_benchmark():
    from easy_tdx.web.task_payload import (
        TaskInput,
        decode_task_input,
        encode_task_input,
        input_fingerprint,
    )

    stock, index = inputs()
    one = attach_benchmark(stock, index, "SH:000001")
    index.attrs["snapshot_metadata"]["instrument"]["code"] = "000300"
    two = attach_benchmark(stock, index, "SH:000300")
    payloads = [
        encode_task_input(TaskInput("factor_series", "test-v1", {}, (frame,), {}))
        for frame in (one, two)
    ]
    assert input_fingerprint(payloads[0]) != input_fingerprint(payloads[1])
    restored = decode_task_input(
        payloads[0], execution_version="test-v1", fingerprint=input_fingerprint(payloads[0])
    )
    pd.testing.assert_frame_equal(restored.frames[0], one)
    assert restored.frames[0].attrs == one.attrs
    validate_benchmark(restored.frames[0])


def test_series_and_pool_fingerprints_distinguish_same_prices_different_indices():
    from easy_tdx.factor.research import cross_section_report
    from easy_tdx.web.routers.research import FactorComputeRequest, _factor_result

    stock, index = inputs()
    dates = pd.bdate_range("2025-01-01", periods=80)
    stock = pd.concat([stock.iloc[:1]] * 80, ignore_index=True)
    stock["datetime"] = dates
    stock["close"] = 10 + np.arange(80) * 0.05
    index = pd.concat([index.iloc[:1]] * 80, ignore_index=True)
    index["datetime"] = dates
    one = attach_benchmark(stock, index, "SH:000001")
    index.attrs["snapshot_metadata"]["instrument"]["code"] = "000300"
    two = attach_benchmark(stock, index, "SH:000300")
    series = [
        _factor_result(
            FactorComputeRequest(
                market="SZ",
                code="000001",
                count=80,
                factors=["gtja191_182"],
                benchmark=f.attrs["factor_benchmark"]["symbol"],
            ),
            f,
        ).data
        for f in (one, two)
    ]
    assert series[0]["rows"] == series[1]["rows"]
    assert series[0]["input_fingerprint"] != series[1]["input_fingerprint"]
    pools = []
    for frame in (one, two):
        pool = {f"SZ:{i:06d}": copy.deepcopy(frame) for i in range(1, 6)}
        pools.append(cross_section_report(pool, ["alpha158_ma5"], 5, 5, "raw"))
    assert pools[0]["input_fingerprint"] != pools[1]["input_fingerprint"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mac", [False, True])
async def test_loader_uses_existing_index_service_and_never_equity_fallback(mac):
    from unittest.mock import AsyncMock, Mock

    from easy_tdx.web.factor_benchmark import load_factor_benchmark

    _, index = inputs()
    index["high"] = index[["open", "close"]].max(axis=1) + 1
    index["low"] = index[["open", "close"]].min(axis=1) - 1
    index["vol"] = 100.0
    index["amount"] = 300000.0
    client = Mock(get_index_bars=AsyncMock(return_value=index), get_security_bars=AsyncMock())
    mac_client = Mock(get_stock_kline=AsyncMock(return_value=index)) if mac else None
    loaded = await load_factor_benchmark("SH:000001", "DAY", 3, client, mac_client)
    assert len(loaded) == 3
    assert loaded.attrs["snapshot_metadata"]["source"] == ("MAC_INDEX" if mac else "TDX_INDEX")
    assert loaded.attrs["snapshot_metadata"]["instrument"] == {
        "kind": "index",
        "market": "SH",
        "code": "000001",
    }
    client.get_security_bars.assert_not_called()
    if mac:
        client.get_index_bars.assert_not_called()
        assert mac_client.get_stock_kline.call_args.kwargs["adjust"].name == "NONE"
    else:
        client.get_index_bars.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args",
    [
        ("SZ:000001", "DAY", 80),
        ("SH:000001", "YEAR", 80),
        ("SH:000001", "DAY", 801),
        ("SH:000001", "DAY", True),
    ],
)
async def test_loader_invalid_selection_rejected_before_any_query(args):
    from unittest.mock import Mock

    from easy_tdx.web.factor_benchmark import load_factor_benchmark

    client = Mock()
    with pytest.raises(ValueError):
        await load_factor_benchmark(*args, client, None)
    assert not client.mock_calls


@pytest.mark.parametrize("side", ["stock", "index"])
def test_quality_errors_cannot_be_hidden_in_metadata(side):
    stock, index = inputs()
    frame = stock if side == "stock" else index
    frame.attrs["snapshot_metadata"]["quality"] = {"errors": ["invalid"]}
    with pytest.raises(ValueError, match="质量"):
        attach_benchmark(stock, index, "SH:000001")


def test_null_contract_is_not_a_legacy_input():
    stock, _ = inputs()
    stock.attrs["factor_benchmark"] = None
    with pytest.raises(ValueError, match="不完整"):
        freeze_input("SZ:000001", stock)


@pytest.mark.asyncio
async def test_loader_reports_excluded_unclosed_bar_and_does_not_requery_equity(monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from easy_tdx.web import factor_benchmark

    _, index = inputs()
    index.loc[2, "is_closed"] = False
    snapshot = {"data": index.to_dict("records"), "metadata": index.attrs["snapshot_metadata"]}
    service = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(factor_benchmark, "research_bars", service)
    client = Mock()
    frame = await factor_benchmark.load_factor_benchmark("SH:000001", "DAY", 3, client, None)
    assert len(frame) == 2 and frame.is_closed.all()
    assert frame.attrs["snapshot_metadata"]["excluded_open_count"] == 1
    assert frame.attrs["snapshot_metadata"]["input_count"] == 2
    service.assert_awaited_once()
    assert not client.mock_calls


@pytest.mark.asyncio
async def test_loader_does_not_swallow_index_service_failure(monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from fastapi import HTTPException

    from easy_tdx.web import factor_benchmark

    service = AsyncMock(side_effect=HTTPException(503, "指数服务不可用"))
    monkeypatch.setattr(factor_benchmark, "research_bars", service)
    client = Mock()
    with pytest.raises(HTTPException, match="指数服务不可用"):
        await factor_benchmark.load_factor_benchmark("SH:000001", "DAY", 3, client, None)
    service.assert_awaited_once()
    assert not client.mock_calls
