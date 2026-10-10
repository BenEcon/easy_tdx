"""Lossless, bounded task inputs. No pickle, imports or executable payloads.

This is a storage contract, not an HTTP request schema or a job dispatcher.
Request validation, ownership and code-version authorization remain mandatory
at submission/claim. Finite floats use Python's round-trip JSON representation;
non-finite values are tagged rather than changed to null or zero.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

CONTRACT = "research-task-input-v1"
KINDS = frozenset(
    {
        "backtest",
        "portfolio",
        "multi_strategy",
        "optimize",
        "optimize_all",
        "signal_scan",
        "factor_evaluation",
        "factor_series",
        "factor_recompute",
    }
)
MAX_BYTES = 64 * 1024 * 1024
MAX_FRAMES = 256
MAX_ROWS = 100_000
MAX_COLUMNS = 256
MAX_CELLS = 4_000_000
MAX_DEPTH = 32


@dataclass(frozen=True)
class TaskInput:
    kind: str
    execution_version: str
    request: dict[str, Any]
    frames: tuple[pd.DataFrame, ...]
    context: dict[str, Any]


def _pack(value: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        raise ValueError("任务输入嵌套过深")
    if value is pd.NA:
        return {"tag": "pd_na"}
    if value is pd.NaT:
        return {"tag": "pd_nat"}
    if isinstance(value, np.generic):
        dtype = _dtype(value.dtype.str)
        if not isinstance(dtype, np.dtype) or dtype.kind == "O":
            raise ValueError("不支持此 NumPy 标量")
        return {"tag": "numpy", "dtype": dtype.str, "hex": value.tobytes().hex()}
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return (
            value
            if math.isfinite(value)
            else {"tag": "float", "hex": struct.pack(">d", value).hex()}
        )
    if isinstance(value, pd.Timestamp):
        return {
            "tag": "timestamp",
            "value": value.isoformat(),
            "zone": str(value.tz) if value.tz else None,
        }
    if isinstance(value, datetime):
        zone = getattr(value.tzinfo, "key", getattr(value.tzinfo, "zone", None))
        return {"tag": "datetime", "value": value.isoformat(), "zone": zone, "fold": value.fold}
    if isinstance(value, date):
        return {"tag": "date", "value": value.isoformat()}
    if isinstance(value, pd.Timedelta):
        return {"tag": "pd_delta", "value": value.isoformat()}
    if isinstance(value, timedelta):
        return {
            "tag": "delta",
            "days": value.days,
            "seconds": value.seconds,
            "microseconds": value.microseconds,
        }
    if isinstance(value, tuple | list):
        items = [_pack(item, depth + 1) for item in value]
        return {"tag": "tuple", "items": items} if isinstance(value, tuple) else items
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("任务字典键必须是字符串")
        # A pair list preserves param-grid iteration order. Wrapping every dict
        # prevents user data resembling a tag from acquiring special meaning.
        return {
            "tag": "dict",
            "items": [[key, _pack(item, depth + 1)] for key, item in value.items()],
        }
    raise ValueError(f"不支持持久化输入类型：{type(value).__name__}")


def _fields(value: dict[str, Any], *keys: str) -> None:
    if set(value) != {"tag", *keys}:
        raise ValueError("任务输入标签字段异常")


def _unpack(value: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        raise ValueError("任务输入嵌套过深")
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("非有限数必须使用显式标签")
        return value
    if isinstance(value, list):
        return [_unpack(item, depth + 1) for item in value]
    if not isinstance(value, dict):
        raise ValueError("任务输入格式异常")
    tag = value.get("tag")
    if tag in {"pd_na", "pd_nat"}:
        _fields(value)
        return pd.NA if tag == "pd_na" else pd.NaT
    if tag in {"float", "numpy"}:
        _fields(value, "hex", *(["dtype"] if tag == "numpy" else []))
        raw = value["hex"]
        if not isinstance(raw, str) or len(raw) > 16:
            raise ValueError("数值标量长度异常")
        data = bytes.fromhex(raw)
        if tag == "float":
            if len(data) != 8:
                raise ValueError("浮点标量长度异常")
            return struct.unpack(">d", data)[0]
        dtype = _dtype(value["dtype"])
        if not isinstance(dtype, np.dtype) or dtype.kind == "O" or len(data) != dtype.itemsize:
            raise ValueError("NumPy 标量类型或长度异常")
        return np.frombuffer(data, dtype=dtype, count=1)[0]
    if tag in {"timestamp", "datetime"}:
        _fields(value, "value", "zone", *(["fold"] if tag == "datetime" else []))
        if not isinstance(value["value"], str) or (
            value["zone"] is not None and not isinstance(value["zone"], str)
        ):
            raise ValueError("时间字段异常")
        if tag == "timestamp":
            stamp = pd.Timestamp(value["value"])
            return stamp.tz_convert(value["zone"]) if value["zone"] else stamp
        stamp_dt = datetime.fromisoformat(value["value"])
        if value["zone"]:
            if stamp_dt.tzinfo is None:
                raise ValueError("具名时区缺少 UTC 偏移")
            stamp_dt = stamp_dt.astimezone(ZoneInfo(value["zone"]))
        if type(value["fold"]) is not int or value["fold"] not in (0, 1):
            raise ValueError("时间 fold 异常")
        return stamp_dt.replace(fold=value["fold"])
    if tag in {"date", "pd_delta"}:
        _fields(value, "value")
        if not isinstance(value["value"], str):
            raise ValueError("时间字段异常")
        return date.fromisoformat(value["value"]) if tag == "date" else pd.Timedelta(value["value"])
    if tag == "delta":
        _fields(value, "days", "seconds", "microseconds")
        if any(type(value[key]) is not int for key in ("days", "seconds", "microseconds")):
            raise ValueError("时间间隔字段异常")
        return timedelta(
            days=value["days"], seconds=value["seconds"], microseconds=value["microseconds"]
        )
    if tag in {"tuple", "dict"}:
        _fields(value, "items")
        if not isinstance(value["items"], list):
            raise ValueError("任务容器字段异常")
        if tag == "tuple":
            return tuple(_unpack(item, depth + 1) for item in value["items"])
        result: dict[str, Any] = {}
        for pair in value["items"]:
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or not isinstance(pair[0], str)
                or pair[0] in result
            ):
                raise ValueError("任务字典键重复或格式异常")
            result[pair[0]] = _unpack(pair[1], depth + 1)
        return result
    raise ValueError("未知任务输入标签")


def _dtype(name: Any) -> Any:
    if not isinstance(name, str) or len(name) > 128:
        raise ValueError("输入列类型异常")
    try:
        dtype = pd.api.types.pandas_dtype(name)
    except (TypeError, ValueError, ImportError) as exc:
        raise ValueError("输入列类型无法恢复") from exc
    if isinstance(dtype, np.dtype):
        if dtype.kind in "biufMmO" and (dtype.kind == "O" or dtype.itemsize <= 8):
            return dtype
    elif isinstance(dtype, pd.DatetimeTZDtype | pd.StringDtype) or name in {
        "Int8",
        "Int16",
        "Int32",
        "Int64",
        "UInt8",
        "UInt16",
        "UInt32",
        "UInt64",
        "Float32",
        "Float64",
        "boolean",
    }:
        return dtype
    raise ValueError(f"尚不支持无损保存的输入列类型：{name}")


def _dtype_name(dtype: Any) -> str:
    name = f"string[{dtype.storage}]" if isinstance(dtype, pd.StringDtype) else str(dtype)
    _dtype(name)
    return name


def _frame(frame: pd.DataFrame) -> dict[str, Any]:
    if not isinstance(frame, pd.DataFrame) or isinstance(frame.index, pd.MultiIndex):
        raise ValueError("任务行情必须是单层索引 DataFrame")
    if len(frame) > MAX_ROWS or len(frame.columns) > MAX_COLUMNS or not frame.columns.is_unique:
        raise ValueError("任务行情规模或重复列名不受支持")
    if any(not isinstance(name, str) for name in frame.columns):
        raise ValueError("任务行情列名必须是字符串")
    if isinstance(frame.index, pd.RangeIndex):
        index: dict[str, Any] = {
            "kind": "range",
            "start": frame.index.start,
            "stop": frame.index.stop,
            "step": frame.index.step,
        }
    else:
        index = {
            "kind": "values",
            "dtype": _dtype_name(frame.index.dtype),
            "values": _pack(frame.index.tolist()),
        }
        if isinstance(frame.index, pd.DatetimeIndex | pd.TimedeltaIndex):
            index["freq"] = frame.index.freqstr
    index["name"] = _pack(frame.index.name)
    return {
        "rows": len(frame),
        "columns_name": _pack(frame.columns.name),
        "index": index,
        "columns": [
            {
                "name": name,
                "dtype": _dtype_name(frame[name].dtype),
                "values": _pack(frame[name].tolist()),
            }
            for name in frame.columns
        ],
        "attrs": _pack(frame.attrs),
        "allows_duplicate_labels": frame.flags.allows_duplicate_labels,
    }


def _restore_frame(value: Any) -> pd.DataFrame:
    if not isinstance(value, dict) or set(value) != {
        "rows",
        "columns_name",
        "index",
        "columns",
        "attrs",
        "allows_duplicate_labels",
    }:
        raise ValueError("任务行情字段异常")
    rows, columns, index = value["rows"], value["columns"], value["index"]
    if (
        type(rows) is not int
        or not 0 <= rows <= MAX_ROWS
        or not isinstance(columns, list)
        or len(columns) > MAX_COLUMNS
    ):
        raise ValueError("任务行情规模异常")
    data: dict[str, Any] = {}
    for column in columns:
        if not isinstance(column, dict) or set(column) != {"name", "dtype", "values"}:
            raise ValueError("任务行情列字段异常")
        name = column["name"]
        if (
            not isinstance(name, str)
            or name in data
            or not isinstance(column["values"], list)
            or len(column["values"]) != rows
        ):
            raise ValueError("任务行情列重复或长度异常")
        data[name] = pd.Series(_unpack(column["values"]), dtype=_dtype(column["dtype"]))
        if _pack(data[name].tolist()) != column["values"]:
            raise ValueError("任务行情列恢复会改变原始值")
    frame = pd.DataFrame(data, index=pd.RangeIndex(rows))
    if not isinstance(index, dict):
        raise ValueError("任务行情索引异常")
    if index.get("kind") == "range" and set(index) == {"kind", "start", "stop", "step", "name"}:
        if (
            any(type(index[key]) is not int for key in ("start", "stop", "step"))
            or not index["step"]
        ):
            raise ValueError("任务行情范围索引异常")
        restored: pd.Index = pd.RangeIndex(
            index["start"], index["stop"], index["step"], name=_unpack(index["name"])
        )
    elif index.get("kind") == "values" and set(index) in (
        {"kind", "dtype", "values", "name"},
        {"kind", "dtype", "values", "name", "freq"},
    ):
        if not isinstance(index["values"], list) or len(index["values"]) != rows:
            raise ValueError("任务行情索引长度异常")
        restored = pd.Index(
            _unpack(index["values"]),
            dtype=_dtype(index["dtype"]),
            name=_unpack(index["name"]),
            tupleize_cols=False,
        )
        if _pack(restored.tolist()) != index["values"]:
            raise ValueError("任务行情索引恢复会改变原始值")
        if "freq" in index:
            if not isinstance(restored, pd.DatetimeIndex | pd.TimedeltaIndex):
                raise ValueError("只有时间索引允许频率")
            restored.freq = index["freq"]
    else:
        raise ValueError("任务行情索引字段异常")
    if len(restored) != rows:
        raise ValueError("任务行情索引长度异常")
    frame.index = restored
    frame.columns.name = _unpack(value["columns_name"])
    attrs = _unpack(value["attrs"])
    if not isinstance(attrs, dict):
        raise ValueError("行情来源元信息必须是字典")
    frame.attrs = attrs
    if type(value["allows_duplicate_labels"]) is not bool:
        raise ValueError("任务行情重复标签设置异常")
    frame.flags.allows_duplicate_labels = value["allows_duplicate_labels"]
    return frame


def _identity(kind: Any, version: Any) -> None:
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("未知持久化任务种类")
    if not isinstance(version, str) or not version.strip() or len(version) > 256:
        raise ValueError("缺少有效执行版本")


def encode_task_input(value: TaskInput, *, max_bytes: int = MAX_BYTES) -> bytes:
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("存储大小上限必须为正整数")
    _identity(value.kind, value.execution_version)
    if not isinstance(value.request, dict) or not isinstance(value.context, dict):
        raise ValueError("任务参数与上下文必须是字典")
    if not isinstance(value.frames, tuple) or any(
        not isinstance(frame, pd.DataFrame) for frame in value.frames
    ):
        raise ValueError("任务行情必须是 DataFrame 元组")
    if len(value.frames) > MAX_FRAMES or sum(frame.size for frame in value.frames) > MAX_CELLS:
        raise ValueError("任务输入行情超出容量")
    envelope = {
        "contract": CONTRACT,
        "kind": value.kind,
        "execution_version": value.execution_version,
        "request": _pack(value.request),
        "frames": [_frame(frame) for frame in value.frames],
        "context": _pack(value.context),
    }
    buffer = BytesIO()
    size = 0
    for chunk in json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).iterencode(envelope):
        encoded = chunk.encode("utf-8")
        size += len(encoded)
        if size > min(max_bytes, MAX_BYTES):
            raise ValueError("任务输入超过存储大小上限")
        buffer.write(encoded)
    return buffer.getvalue()


def input_fingerprint(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("任务 JSON 字段重复")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"任务 JSON 不允许非标准常量：{value}")


def decode_task_input(payload: bytes, *, execution_version: str, fingerprint: str) -> TaskInput:
    if (
        not isinstance(payload, bytes)
        or len(payload) > MAX_BYTES
        or input_fingerprint(payload) != fingerprint
    ):
        raise ValueError("任务输入大小或指纹不匹配")
    try:
        value = json.loads(
            payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        if (
            not isinstance(value, dict)
            or set(value)
            != {"contract", "kind", "execution_version", "request", "frames", "context"}
            or value["contract"] != CONTRACT
        ):
            raise ValueError("任务输入契约版本或字段不匹配")
        _identity(value["kind"], value["execution_version"])
        if value["execution_version"] != execution_version:
            raise ValueError("执行版本已变化，不能复用旧任务输入")
        frames = value["frames"]
        if not isinstance(frames, list) or len(frames) > MAX_FRAMES:
            raise ValueError("任务行情数量异常")
        cells = 0
        for frame in frames:
            if (
                not isinstance(frame, dict)
                or type(frame.get("rows")) is not int
                or not isinstance(frame.get("columns"), list)
            ):
                raise ValueError("任务行情结构异常")
            if not 0 <= frame["rows"] <= MAX_ROWS or len(frame["columns"]) > MAX_COLUMNS:
                raise ValueError("任务行情规模异常")
            cells += frame["rows"] * len(frame["columns"])
        if cells > MAX_CELLS:
            raise ValueError("任务输入行情超出容量")
        request, context = _unpack(value["request"]), _unpack(value["context"])
        if not isinstance(request, dict) or not isinstance(context, dict):
            raise ValueError("任务参数与上下文必须是字典")
        return TaskInput(
            value["kind"],
            value["execution_version"],
            request,
            tuple(_restore_frame(frame) for frame in frames),
            context,
        )
    except (TypeError, KeyError, OverflowError, RecursionError) as exc:
        raise ValueError("任务输入损坏，拒绝恢复") from exc
