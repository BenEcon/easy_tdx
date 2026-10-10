"""Independent index input contract; exact observed times, no market I/O or filling.

Identity is supplied by the index endpoint, never inferred from a stock code.
These checks establish internal consistency, not authenticity of client uploads.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from easy_tdx.factor.panel import observation_index

VERSION = "factor-benchmark-v1"
ALIGNMENT = "exact_observation_time_no_fill"
BENCHMARKS = {
    "SH:000001": "上证指数",
    "SZ:399001": "深证成指",
    "SH:000300": "沪深300",
    "SZ:399006": "创业板指",
}
FIELDS = ("benchmark_open", "benchmark_close")
_PERIODS = {"DAY", "WEEK", "MONTH", "MIN_1", "MIN_5", "MIN_15", "MIN_30", "MIN_60"}


def _metadata(frame: pd.DataFrame) -> dict[str, Any]:
    metadata = frame.attrs.get("snapshot_metadata")
    if not isinstance(metadata, dict) or metadata.get("category") not in _PERIODS:
        raise ValueError("基准对齐需要明确且支持的行情周期")
    if metadata.get("bar_time") != "end":
        raise ValueError("基准对齐仅接受收盘时间标记，未猜测或平移时间")
    quality = metadata.get("quality")
    if isinstance(quality, dict) and quality.get("errors"):
        raise ValueError("行情质量检查未通过，不能附加基准")
    if "is_closed" not in frame or not all(type(v) is bool and v for v in frame.is_closed.tolist()):
        raise ValueError("基准对齐仅接受明确已收盘的行情，未静默删除未收盘行")
    if frame.empty or len(frame) > 800:
        raise ValueError("基准对齐要求 1–800 根行情，未截断输入")
    observation_index(frame)
    return metadata


def validate_index(frame: pd.DataFrame, symbol: str) -> None:
    if symbol not in BENCHMARKS:
        raise ValueError("请选择支持的明确基准指数，不能按代码猜测市场")
    meta = _metadata(frame)
    market, code = symbol.split(":")
    instrument = meta.get("instrument")
    if not isinstance(instrument, dict) or any(
        instrument.get(k) != v for k, v in {"kind": "index", "market": market, "code": code}.items()
    ):
        raise ValueError("基准行情身份与所选指数不一致，不能使用同代码个股代替")
    if meta.get("source") not in {"MAC_INDEX", "TDX_INDEX"}:
        raise ValueError("基准缺少独立指数行情来源")
    if meta.get("actual_adjust") != "NONE" or meta.get("requested_adjust") != "NONE":
        raise ValueError("基准指数必须不复权，不跟随个股复权设置")
    if "factor_benchmark" in frame.attrs or any(k in frame for k in FIELDS):
        raise ValueError("基准原始行情不得包含嵌套基准输入")
    for field in ("open", "close"):
        if (
            field not in frame
            or not pd.api.types.is_numeric_dtype(frame[field])
            or pd.api.types.is_bool_dtype(frame[field])
        ):
            raise ValueError("基准开收价格缺失或不是数值")
        values = frame[field].to_numpy(dtype=float, na_value=np.nan)
        if not (np.isfinite(values) & (values > 0)).all():
            raise ValueError("基准开收价格含无效值，未伪造零值或填充")


def _aligned(
    stock: pd.DataFrame, index: pd.DataFrame, symbol: str
) -> tuple[NDArray[np.float64], int]:
    stock_meta = _metadata(stock)
    if stock_meta.get("actual_adjust") not in {"NONE", "QFQ", "HFQ"}:
        raise ValueError("个股实际复权方式缺失，不能建立配对输入")
    validate_index(index, symbol)
    if stock_meta["category"] != index.attrs["snapshot_metadata"]["category"]:
        raise ValueError("个股与基准周期不一致，未重采样或替换周期")
    target, source = observation_index(stock), observation_index(index)
    positions = source.get_indexer(target)
    matched = positions >= 0
    if not matched.any():
        raise ValueError("个股与基准没有相同观测时间，未用邻近日期替代")
    values = np.full((len(stock), 2), np.nan)
    values[matched] = index[["open", "close"]].to_numpy(dtype=float)[positions[matched]]
    return values, int(matched.sum())


def attach_benchmark(stock: pd.DataFrame, index: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Return an independent copy with aligned columns and a complete frozen index."""
    from easy_tdx.factor.snapshot import freeze_input

    if "factor_benchmark" in stock.attrs or any(k in stock for k in FIELDS):
        raise ValueError("行情已附有基准，不能静默覆盖；请从原始输入重新构建")
    values, matched = _aligned(stock, index, symbol)
    result = stock.copy(deep=True)
    result.attrs = copy.deepcopy(stock.attrs)
    for i, field in enumerate(FIELDS):
        result[field] = values[:, i]
    result.attrs["factor_benchmark"] = {
        "version": VERSION,
        "symbol": symbol,
        "name": BENCHMARKS[symbol],
        "alignment": ALIGNMENT,
        "matched_rows": matched,
        "missing_rows": len(stock) - matched,
        "snapshot": freeze_input(symbol, index),
    }
    return result


def validate_benchmark(frame: pd.DataFrame) -> None:
    """Validate restored paired inputs without fetching or calculating any factor."""
    from easy_tdx.factor.snapshot import restore_input

    value = frame.attrs.get("factor_benchmark")
    if "factor_benchmark" not in frame.attrs and not any(k in frame for k in FIELDS):
        return  # Legacy inputs did not use a benchmark.
    required = {
        "version",
        "symbol",
        "name",
        "alignment",
        "matched_rows",
        "missing_rows",
        "snapshot",
    }
    if not isinstance(value, dict) or set(value) != required or not all(k in frame for k in FIELDS):
        raise ValueError("基准原始快照或对齐字段不完整")
    symbol = value["symbol"]
    if (
        not isinstance(symbol, str)
        or symbol not in BENCHMARKS
        or (
            value["version"] != VERSION
            or value["alignment"] != ALIGNMENT
            or value["name"] != BENCHMARKS[symbol]
        )
    ):
        raise ValueError("基准身份、版本或对齐规则无效")
    snapshot = value["snapshot"]
    # Reject recursion before restore_input recurses into its metadata validator.
    if (
        not isinstance(snapshot, dict)
        or not isinstance(snapshot.get("attrs"), dict)
        or (
            "factor_benchmark" in snapshot["attrs"]
            or not isinstance(snapshot.get("columns"), list)
            or any(k in snapshot["columns"] for k in FIELDS)
        )
    ):
        raise ValueError("基准原始快照无效或存在嵌套")
    if snapshot.get("symbol") != symbol:
        raise ValueError("冻结基准标识不一致")
    index = restore_input(snapshot)
    expected, matched = _aligned(frame, index, symbol)
    if any(type(value[k]) is not int for k in ("matched_rows", "missing_rows")) or (
        value["matched_rows"] != matched or value["missing_rows"] != len(frame) - matched
    ):
        raise ValueError("基准覆盖统计与原始观测时间不一致")
    for i, field in enumerate(FIELDS):
        if not pd.api.types.is_numeric_dtype(frame[field]) or pd.api.types.is_bool_dtype(
            frame[field]
        ):
            raise ValueError("冻结基准价格字段不是数值")
        if not np.array_equal(
            frame[field].to_numpy(dtype=float, na_value=np.nan), expected[:, i], equal_nan=True
        ):
            raise ValueError("对齐后的基准价格与原始快照不一致；未修复或重算")


def needs_benchmark(factors: list[str]) -> bool:
    from easy_tdx.factor import get_factor

    return any(set(get_factor(name).inputs).intersection(FIELDS) for name in factors)


def validate_frozen_benchmark(frame: pd.DataFrame, selected: str | None) -> None:
    """Request and frozen source must agree, including explicit fetch failure."""
    validate_benchmark(frame)
    contract = frame.attrs.get("factor_benchmark")
    if contract is not None:
        if contract["symbol"] != selected:
            raise ValueError("研究配置与冻结基准指数不一致")
    elif selected is not None:
        errors = frame.attrs.get("factor_input_errors", {})
        if not all(isinstance(errors.get(k), str) and errors[k] for k in FIELDS):
            raise ValueError("所选基准缺少快照或明确的取数失败记录")


def validate_benchmark_pool(frames: Iterable[pd.DataFrame], selected: str | None) -> None:
    """A study has one frozen index tape, even when equity calendars differ."""
    digests: set[str] = set()
    for frame in frames:
        validate_frozen_benchmark(frame, selected)
        contract = frame.attrs.get("factor_benchmark")
        if contract is not None:
            digests.add(contract["snapshot"]["digest"])
    if len(digests) > 1:
        raise ValueError("股票池混用了不同版本的基准指数快照；请使用同一次取数结果")
