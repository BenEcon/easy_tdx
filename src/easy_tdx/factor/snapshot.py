"""Portable bounded factor inputs. No pickle, executable code or market requests."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

VERSION = "factor-input-v1"
_DTYPE = re.compile(
    r"^(?:object|bool|u?int(?:8|16|32|64)|float(?:32|64)|datetime64\[(?:ns|us|ms|s)\])$"
)


def _cell(value: Any) -> Any:
    if value is pd.NaT:
        return {"special": "NaT"}
    if value is pd.NA:
        return {"special": "NA"}
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, pd.Timestamp):
        return {"timestamp": value.isoformat()}
    if isinstance(value, datetime):
        return {"datetime": value.isoformat()}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, float) and not math.isfinite(value):
        return {"special": "NaN" if math.isnan(value) else "Inf" if value > 0 else "-Inf"}
    if type(value) is float and value == 0 and math.copysign(1, value) < 0:
        return {"special": "-0"}
    if value is None or type(value) in (str, bool, int, float):
        if type(value) is int and abs(value) > 2**53 - 1:
            return {"integer": str(value)}
        return value
    raise ValueError("因子输入包含不支持的单元格类型；未静默丢弃")


def _decode(value: Any) -> Any:
    if value is None or type(value) in (str, bool, int, float):
        if type(value) in (int, float) and not math.isfinite(value):
            raise ValueError("快照中的非有限数值必须显式编码")
        return value
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError("快照单元格格式无效")
    key, item = next(iter(value.items()))
    if not isinstance(item, str):
        raise ValueError("快照单元格格式无效")
    if key == "special" and item in {"NaT", "NA", "NaN", "Inf", "-Inf", "-0"}:
        return {
            "NaT": pd.NaT,
            "NA": pd.NA,
            "NaN": np.nan,
            "Inf": np.inf,
            "-Inf": -np.inf,
            "-0": -0.0,
        }[item]
    if key == "timestamp":
        return pd.Timestamp(item)
    if key == "datetime":
        return datetime.fromisoformat(item)
    if key == "date":
        return date.fromisoformat(item)
    if key == "integer" and re.fullmatch(r"-?\d{1,20}", item):
        return int(item)
    raise ValueError("快照单元格标记无效")


def snapshot_digest(value: dict[str, Any]) -> str:
    # Browser JSON round trips turn 1.0 into 1 and -0.0 into 0. Hash their
    # numerical identity; scalar dtype is separately frozen in the schema.
    def canonical(item: Any) -> Any:
        if isinstance(item, dict):
            return {k: canonical(v) for k, v in item.items()}
        if isinstance(item, list | tuple):
            return [canonical(v) for v in item]
        if type(item) is float and math.isfinite(item) and item.is_integer():
            return int(item)
        return item

    body = {k: v for k, v in value.items() if k != "digest"}
    return hashlib.sha256(
        json.dumps(
            canonical(body),
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def freeze_input(symbol: str, frame: pd.DataFrame) -> dict[str, Any]:
    """Preserve all input columns, dtypes, index and calculation-relevant metadata."""
    if isinstance(frame.index, pd.MultiIndex):
        raise ValueError("不支持多重索引的因子输入快照")
    value = {
        "version": VERSION,
        "symbol": symbol,
        "columns": list(frame.columns),
        "dtypes": [str(dtype) for dtype in frame.dtypes],
        "rows": [[_cell(v) for v in row] for row in frame.itertuples(index=False, name=None)],
        "index": {
            "name": frame.index.name,
            "dtype": str(frame.index.dtype),
            "values": [_cell(v) for v in frame.index],
            "range": [frame.index.start, frame.index.stop, frame.index.step]
            if isinstance(frame.index, pd.RangeIndex)
            else None,
        },
        "attrs": copy.deepcopy(
            {
                key: frame.attrs[key]
                for key in ("snapshot_metadata", "factor_data_contract", "factor_input_errors")
                if key in frame.attrs
            }
        ),
    }
    value["digest"] = snapshot_digest(value)
    restore_input(value)  # Fail explicitly on a nonportable feed, never save a partial input.
    return value


def restore_input(value: dict[str, Any]) -> pd.DataFrame:
    """Structural validation and lossless restoration only; no factor execution."""
    if value.get("version") != VERSION or not re.fullmatch(
        r"(?:SZ|SH|BJ):\d{6}", str(value.get("symbol"))
    ):
        raise ValueError("因子快照版本或标的无效")
    columns, dtypes, rows, index = (value[k] for k in ("columns", "dtypes", "rows", "index"))
    if (
        not isinstance(columns, list)
        or not 1 <= len(columns) <= 64
        or any(not isinstance(k, str) or not k or len(k) > 100 for k in columns)
        or len(set(columns)) != len(columns)
        or not isinstance(dtypes, list)
        or len(dtypes) != len(columns)
        or any(not isinstance(d, str) or not _DTYPE.fullmatch(d) for d in dtypes)
        or not isinstance(rows, list)
        or not 1 <= len(rows) <= 800
        or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)
        or not isinstance(index, dict)
        or not isinstance(index.get("values"), list)
        or len(index["values"]) != len(rows)
        or not isinstance(index.get("dtype"), str)
        or not _DTYPE.fullmatch(index["dtype"])
        or (index.get("name") is not None and not isinstance(index["name"], str))
        or not isinstance(value.get("attrs"), dict)
    ):
        raise ValueError("因子快照列、类型或行数不完整")
    if value.get("digest") != snapshot_digest(value):
        raise ValueError("因子输入快照摘要不一致；未修复或重算")
    data = {
        column: pd.Series([_decode(row[i]) for row in rows], dtype=dtypes[i])
        for i, column in enumerate(columns)
    }
    frame = pd.DataFrame(data)
    if [[_cell(v) for v in row] for row in frame.itertuples(index=False, name=None)] != rows:
        raise ValueError("声明类型与单元格不一致；未截断、舍入或隐式转换")
    saved_index = pd.Index(
        [_decode(v) for v in index["values"]], dtype=index["dtype"], name=index.get("name")
    )
    if index.get("range") is not None:
        bounds = index["range"]
        if (
            not isinstance(bounds, list)
            or len(bounds) != 3
            or any(type(v) is not int for v in bounds)
            or not bounds[2]
        ):
            raise ValueError("索引范围无效")
        restored = pd.RangeIndex(*bounds, name=index.get("name"))
        if not restored.equals(saved_index):
            raise ValueError("索引范围与值不一致")
        saved_index = restored
    if saved_index.has_duplicates:
        raise ValueError("因子快照索引重复")
    frame.index = saved_index
    frame.attrs = copy.deepcopy(value["attrs"])
    return frame
