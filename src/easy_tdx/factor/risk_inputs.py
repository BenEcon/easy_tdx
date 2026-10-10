"""Dated Chinese daily FF3 tapes, without fetching, proxying or licence claims.

This contract checks internal consistency, not provider authenticity. A tape
must declare its construction and point-in-time availability. Later releases
remain in the frozen source but cannot enter a same-close predictive input.
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from easy_tdx.factor.panel import observation_index

VERSION = "factor-risk-input-v1"
FIELDS = ("risk_mkt", "risk_smb", "risk_hml")
ALIGNMENT = "china_daily_same_close_available_no_fill"
_TEXT = {"dataset_id", "provider", "source", "methodology", "universe", "licence"}
_META = _TEXT | {"version", "market", "frequency", "unit", "mkt_definition", "vintage_at"}
_ROW = {"date", "available_at", "mkt", "smb", "hml"}


def _timestamp(value: Any) -> pd.Timestamp:
    if not isinstance(value, str) or len(value) > 50:
        raise ValueError("风险因子可得时间必须为带时区的 ISO 时间")
    try:
        result = pd.Timestamp(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("风险因子时间格式无效") from exc
    if pd.isna(result) or result.tzinfo is None:
        raise ValueError("风险因子时间缺少时区，未猜测发布时间")
    return result.tz_convert("Asia/Shanghai")


def validate_risk_tape(tape: dict[str, Any]) -> None:
    """Accept decimal daily return spreads, never percentages or index levels."""
    from easy_tdx.factor.snapshot import snapshot_digest

    if not isinstance(tape, dict) or set(tape) != {"metadata", "rows", "digest"}:
        raise ValueError("风险三因子原始数据包不完整")
    meta, rows = tape["metadata"], tape["rows"]
    if not isinstance(meta, dict) or set(meta) != _META:
        raise ValueError("风险三因子来源、口径或许可声明不完整")
    if any(
        not isinstance(meta[k], str) or not meta[k].strip() or len(meta[k]) > 2000 for k in _TEXT
    ):
        raise ValueError("风险三因子来源声明为空或过长")
    if (
        meta["version"] != VERSION
        or meta["market"] != "CN_A"
        or meta["frequency"] != "DAY"
        or meta["unit"] != "decimal_return"
        or meta["mkt_definition"] != "market_excess_return"
    ):
        raise ValueError("仅接受 A 股日频、小数收益率的风险三因子；未转换单位或代理 MKT")
    vintage = _timestamp(meta["vintage_at"])
    if not isinstance(rows, list) or not 1 <= len(rows) <= 800:
        raise ValueError("风险三因子要求 1–800 行，未截断数据")
    previous = ""
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW:
            raise ValueError("风险三因子逐行日期、可得时间及数值不完整")
        date = row["date"]
        if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("风险三因子日期必须为 YYYY-MM-DD")
        close = _timestamp(date + "T15:00:00+08:00")
        if date <= previous:
            raise ValueError("风险三因子日期重复或未递增，未排序或合并修订版本")
        previous = date
        available = _timestamp(row["available_at"])
        if available < close or available > vintage:
            raise ValueError("风险因子可得时间早于当日收盘或晚于数据版本时间")
        for field in ("mkt", "smb", "hml"):
            value = row[field]
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError("风险三因子数值无效，缺失请明确使用 null")
    if tape["digest"] != snapshot_digest(tape):
        raise ValueError("风险三因子快照摘要不一致")


def freeze_risk_tape(metadata: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    from easy_tdx.factor.snapshot import snapshot_digest

    tape = copy.deepcopy({"metadata": metadata, "rows": rows})
    tape["digest"] = snapshot_digest(tape)
    validate_risk_tape(tape)
    return tape


def _aligned(frame: pd.DataFrame, tape: dict[str, Any]) -> tuple[NDArray[np.float64], list[str]]:
    validate_risk_tape(tape)
    meta = frame.attrs.get("snapshot_metadata", {})
    if (
        not isinstance(meta, dict)
        or meta.get("category") != "DAY"
        or meta.get("bar_time") != "end"
        or meta.get("actual_adjust") not in {"NONE", "QFQ", "HFQ"}
    ):
        raise ValueError("风险三因子仅对齐明确复权的日线收盘数据，不重采样到分钟线")
    quality = meta.get("quality", {})
    if isinstance(quality, dict) and quality.get("errors"):
        raise ValueError("行情质量检查未通过")
    if (
        not 1 <= len(frame) <= 800
        or "is_closed" not in frame
        or not all(type(v) is bool and v for v in frame.is_closed.tolist())
    ):
        raise ValueError("风险三因子对齐需要 1–800 根明确已收盘日线")
    times = observation_index(frame)
    if times.normalize().has_duplicates or any(
        t != t.normalize() and t != t.normalize() + pd.Timedelta(hours=15) for t in times
    ):
        raise ValueError("日线时间不是日期标签或 15:00 收盘；未猜测交易日")
    lookup = {row["date"]: row for row in tape["rows"]}
    values = np.full((len(frame), len(FIELDS)), np.nan)
    states = []
    for i, time in enumerate(times):
        row = lookup.get(time.strftime("%Y-%m-%d"))
        if row is None:
            states.append("missing_date")
        elif _timestamp(row["available_at"]) > time.normalize().tz_localize(
            "Asia/Shanghai"
        ) + pd.Timedelta(hours=15):
            states.append("not_available_at_close")
        elif any(row[k] is None for k in ("mkt", "smb", "hml")):
            states.append("missing_value")
        else:
            values[i] = [row[k] for k in ("mkt", "smb", "hml")]
            states.append("ready")
    return values, states


def attach_risk_inputs(frame: pd.DataFrame, tape: dict[str, Any]) -> pd.DataFrame:
    if "factor_risk_inputs" in frame.attrs or any(k in frame for k in FIELDS):
        raise ValueError("风险三因子已存在，未静默覆盖")
    values, states = _aligned(frame, tape)
    result = frame.copy(deep=True)
    result.attrs = copy.deepcopy(frame.attrs)
    for i, field in enumerate(FIELDS):
        result[field] = values[:, i]
    result.attrs["factor_risk_inputs"] = {
        "version": VERSION,
        "alignment": ALIGNMENT,
        "states": states,
        "snapshot": copy.deepcopy(tape),
    }
    return result


def validate_risk_inputs(frame: pd.DataFrame) -> None:
    if "factor_risk_inputs" not in frame.attrs and not any(k in frame for k in FIELDS):
        return
    value = frame.attrs.get("factor_risk_inputs")
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "alignment", "states", "snapshot"}
        or value["version"] != VERSION
        or value["alignment"] != ALIGNMENT
        or not all(k in frame for k in FIELDS)
    ):
        raise ValueError("风险三因子冻结契约不完整")
    expected, states = _aligned(frame, value["snapshot"])
    if value["states"] != states:
        raise ValueError("风险三因子可得性记录与原始输入不一致")
    for i, field in enumerate(FIELDS):
        if (
            not pd.api.types.is_numeric_dtype(frame[field])
            or pd.api.types.is_bool_dtype(frame[field])
            or not np.array_equal(
                frame[field].to_numpy(dtype=float, na_value=np.nan), expected[:, i], equal_nan=True
            )
        ):
            raise ValueError("风险三因子对齐值与原始输入不一致，未重算或修复")


def validate_risk_pool(frames: Iterable[pd.DataFrame]) -> None:
    identities: set[str | None] = set()
    for frame in frames:
        validate_risk_inputs(frame)
        value = frame.attrs.get("factor_risk_inputs")
        identities.add(value["snapshot"]["digest"] if value else None)
    if len(identities) > 1:
        raise ValueError("股票池风险三因子来源版本不一致或部分缺失，未静默混用")
