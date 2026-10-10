"""Durable input fidelity and bounded, non-executable decoding."""

import json
import struct
from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from easy_tdx.web import task_payload as codec
from easy_tdx.web.task_payload import (
    TaskInput,
    decode_task_input,
    encode_task_input,
    input_fingerprint,
)


def task(*frames, kind="backtest", request=None, context=None):
    return TaskInput(kind, "test-code-and-rules-v1", request or {}, frames, context or {})


def restore(payload, version="test-code-and-rules-v1"):
    return decode_task_input(
        payload, execution_version=version, fingerprint=input_fingerprint(payload)
    )


def mutated(payload, change):
    value = json.loads(payload)
    change(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode()


def assert_round_trip(frame):
    original = task(frame)
    encoded = encode_task_input(original)
    restored = restore(encoded)
    assert_frame_equal(restored.frames[0], frame, check_exact=True)
    assert restored.frames[0].attrs == frame.attrs
    assert encode_task_input(restored) == encoded
    return restored.frames[0]


@pytest.mark.parametrize("kind", sorted(codec.KINDS))
def test_registered_kinds_and_request_order(kind):
    request = {"grid": {"slow": [20, 30], "fast": [5, 10]}, "tag": "pd_na"}
    original = task(kind=kind, request=request, context={"symbol": "SZ:300750"})
    restored = restore(encode_task_input(original))
    assert restored == original
    assert list(restored.request["grid"]) == ["slow", "fast"]
    assert restored.request["tag"] == "pd_na"


def test_float_bits_large_integer_missing_and_signed_zero():
    nan = struct.unpack(">d", bytes.fromhex("7ff8000000000123"))[0]
    frame = pd.DataFrame(
        {
            "price": [np.nextafter(30.05, 31), np.nextafter(1.0, 0), -0.0, nan],
            "small": np.array([1.1, -0.0, np.inf, np.nan], dtype="float32"),
            "volume": np.array([2**63 + 1, 2**64 - 1, 0, 3], dtype="uint64"),
            "nullable": pd.array([1, None, 3, 4], dtype="Int64"),
            "closed": pd.array([True, None, False, True], dtype="boolean"),
            "note": pd.array(["中文", None, "", "来源"], dtype="string[python]"),
        }
    )
    result = assert_round_trip(frame)
    np.testing.assert_array_equal(
        result.price.to_numpy().view("u8"), frame.price.to_numpy().view("u8")
    )
    np.testing.assert_array_equal(
        result.small.to_numpy().view("u4"), frame.small.to_numpy().view("u4")
    )
    assert result.volume.iloc[1] == 2**64 - 1


@pytest.mark.parametrize(
    "dtype", ["int8", "uint8", "float16", "float64", "UInt64", "Float32", "Float64"]
)
def test_numeric_dtypes(dtype):
    assert_round_trip(pd.DataFrame({"factor": pd.Series([0, 1, 2], dtype=dtype)}))


@pytest.mark.parametrize(
    "index",
    [
        pd.RangeIndex(20, 14, -2, name="bar"),
        pd.Index([7, 7, 9], name="source_index"),
        pd.Index([("a", 1), ("b", 2), ("c", 3)], tupleize_cols=False),
        pd.date_range("2026-10-25 00:30", periods=3, freq="h", tz="Europe/Berlin"),
        pd.timedelta_range("1ns", periods=3, freq="s"),
    ],
)
def test_index_values_names_frequency_timezone(index):
    frame = pd.DataFrame({"close": [30.05, 29.02, 31.12]}, index=index)
    frame.columns.name = "行情"
    assert_round_trip(frame)


def test_datetime_columns_and_nested_metadata():
    frame = pd.DataFrame(
        {
            "datetime": pd.date_range(
                "2026-09-10 09:30", periods=3, freq="30min", tz="Asia/Shanghai"
            ),
            "period_end": [
                pd.Timestamp("2026-09-10 10:00:00.000000123"),
                pd.NaT,
                pd.Timestamp("2026-09-10 11:00"),
            ],
            "elapsed": pd.to_timedelta([1, None, 3], unit="ns"),
        }
    )
    frame.attrs = {
        "snapshot_metadata": {
            "actual_adjust": "QFQ",
            "data_fingerprint": "frozen-data",
            "source": "fixture",
        },
        "dates": (
            date(2026, 10, 9),
            datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo("Europe/Berlin"), fold=1),
        ),
        "period": timedelta(days=-1, microseconds=123),
        "numpy": np.int64(2**60),
        "timestamp": pd.Timestamp("2026-10-09", tz="Asia/Shanghai"),
        "duration": pd.Timedelta("1ns"),
        "literal": {"tag": "numpy", "dtype": "import.module", "hex": "not executable"},
    }
    frame.flags.allows_duplicate_labels = False
    assert_round_trip(frame)


def test_object_columns_retain_scalar_types_and_null_distinctions():
    frame = pd.DataFrame(
        {
            "raw": pd.Series(
                [
                    pd.NA,
                    pd.NaT,
                    None,
                    np.int32(9),
                    np.float32(0.1),
                    np.datetime64("2026-01-01", "D"),
                    np.timedelta64(3, "h"),
                ],
                dtype=object,
            )
        }
    )
    result = assert_round_trip(frame)
    assert result.raw.iloc[0] is pd.NA
    assert result.raw.iloc[1] is pd.NaT
    assert result.raw.iloc[2] is None
    for i in (3, 4, 5, 6):
        assert type(result.raw.iloc[i]) is type(frame.raw.iloc[i])


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame(),
        pd.DataFrame(index=pd.RangeIndex(5)),
        pd.DataFrame({"price": pd.Series([], dtype="float64")}),
    ],
)
def test_empty_shapes(frame):
    assert_round_trip(frame)


def test_encoded_input_is_frozen_and_versions_change_identity():
    frame = pd.DataFrame({"close": [30.05]})
    frame.attrs["snapshot_metadata"] = {"actual_adjust": "QFQ"}
    original = task(frame, request={"params": {"fast": 5}})
    payload = encode_task_input(original)
    frame.loc[0, "close"] = 99.0
    frame.attrs["snapshot_metadata"]["actual_adjust"] = "NONE"
    original.request["params"]["fast"] = 10
    restored = restore(payload)
    assert restored.frames[0].close.iloc[0] == 30.05
    assert restored.frames[0].attrs["snapshot_metadata"]["actual_adjust"] == "QFQ"
    assert restored.request["params"]["fast"] == 5
    assert input_fingerprint(payload) != input_fingerprint(encode_task_input(original))
    assert input_fingerprint(payload) != input_fingerprint(
        encode_task_input(replace(restored, execution_version="v2"))
    )
    with pytest.raises(ValueError, match="执行版本"):
        restore(payload, version="v2")
    with pytest.raises(ValueError, match="指纹"):
        decode_task_input(
            payload + b" ",
            execution_version="test-code-and-rules-v1",
            fingerprint=input_fingerprint(payload),
        )


@pytest.mark.parametrize("value", [object(), lambda: None, np.array([1]), {1: "nonstring"}])
def test_unsupported_values_fail_instead_of_dropping_or_executing(value):
    with pytest.raises(ValueError):
        encode_task_input(task(context={"value": value}))


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame({"x": pd.Categorical(["a", "b"])}),
        pd.DataFrame({"x": [1 + 2j]}),
        pd.DataFrame([[1, 2]], columns=["duplicate", "duplicate"]),
        pd.DataFrame({1: [2]}),
        pd.DataFrame({"x": [1]}, index=pd.MultiIndex.from_tuples([("a", 1)])),
    ],
)
def test_unsupported_frame_shape_or_dtype_fails_closed(frame):
    with pytest.raises(ValueError):
        encode_task_input(task(frame))


@pytest.mark.parametrize("limit", [-1, 0, True, 1.5, 10])
def test_size_limit(limit):
    with pytest.raises(ValueError):
        encode_task_input(task(), max_bytes=limit)


def test_capacity_is_checked_before_restoring_any_frame(monkeypatch):
    original = encode_task_input(task(pd.DataFrame({"x": [1, 2]})))
    monkeypatch.setattr(codec, "MAX_CELLS", 1)
    with pytest.raises(ValueError, match="容量"):
        encode_task_input(task(pd.DataFrame({"x": [1, 2]})))
    monkeypatch.setattr(
        codec, "_restore_frame", lambda frame: pytest.fail("must reject before allocation")
    )
    with pytest.raises(ValueError, match="容量"):
        restore(original)


@pytest.mark.parametrize(
    "change",
    [
        lambda v: v.update(contract="unknown"),
        lambda v: v.update(kind="os.system"),
        lambda v: v.update(extra="unexpected"),
        lambda v: v["frames"][0].update(rows=-1),
        lambda v: v["frames"][0].update(rows=True),
        lambda v: v["frames"][0].update(rows=codec.MAX_ROWS + 1),
        lambda v: v["frames"][0]["columns"][0].update(values=[1.125]),
        lambda v: v["frames"][0]["columns"][0].update(dtype="int8"),
        lambda v: v["frames"][0]["columns"][0].update(values=[1]),
        lambda v: v["frames"][0]["index"].update(stop=50),
        lambda v: v["frames"][0]["index"].update(step=0),
        lambda v: v["frames"][0].update(allows_duplicate_labels="false"),
        lambda v: v.update(context={"tag": "pickle", "value": "never load"}),
        lambda v: v.update(context={"tag": "dict", "items": [["a", 1], ["a", 2]]}),
        lambda v: v.update(context={"tag": "numpy", "dtype": "object", "hex": "00" * 8}),
        lambda v: v.update(context={"tag": "float", "hex": "00"}),
    ],
)
def test_malformed_input_rejected_even_with_matching_hash(change):
    payload = encode_task_input(task(pd.DataFrame({"x": [1.125, 2.25]})))
    with pytest.raises(ValueError):
        restore(mutated(payload, change))


@pytest.mark.parametrize(
    "payload", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b"not json", b"\xff"]
)
def test_invalid_json(payload):
    with pytest.raises(ValueError):
        restore(payload)


def test_nested_metadata_depth():
    nested = {}
    for _ in range(codec.MAX_DEPTH + 2):
        nested = {"nested": nested}
    with pytest.raises(ValueError, match="嵌套"):
        encode_task_input(task(context=nested))
    payload = encode_task_input(task())
    nested_tag = None
    for _ in range(codec.MAX_DEPTH + 2):
        nested_tag = [nested_tag]
    with pytest.raises(ValueError, match="嵌套"):
        restore(mutated(payload, lambda v: v.update(context=nested_tag)))


def test_real_backtest_and_input_evidence_are_identical_after_restore():
    from easy_tdx.web.backtest_schemas import BacktestRequest
    from easy_tdx.web.routers.backtest import _ohlcv_to_df, _run_backtest

    dates = pd.bdate_range("2026-01-05", periods=100)
    closes = 30 + 4 * np.sin(np.arange(100) / 5)
    records = [
        dict(
            datetime=str(day.date()),
            open=float(price - 0.1),
            high=float(price + 1),
            low=float(price - 1),
            close=float(price),
            vol=100000,
            amount=float(price * 100000),
        )
        for day, price in zip(dates, closes)
    ]
    request = BacktestRequest(
        strategy="ma_cross", symbol="SZ:300750", params={"fast": 5, "slow": 10}, ohlcv=records
    )
    frame = _ohlcv_to_df(records, category=request.category, adjust=request.adjust)
    original = task(frame, request=request.model_dump())
    restored = restore(encode_task_input(original))
    before = _run_backtest(frame, request)
    after = _run_backtest(restored.frames[0], BacktestRequest.model_validate(restored.request))
    assert before == after
    assert len(before["trades"]) > 0
