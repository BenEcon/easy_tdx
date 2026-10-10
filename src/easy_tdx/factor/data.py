"""Verified native MAC equity fields for factor research, not chart mutation.

Volume is actual traded shares (NOT inverse-price-adjusted pseudo-volume).
VWAP is only amount/shares on unadjusted prices. An affine fit to OHLC is not
proof of the transformation of all trades, so adjusted VWAP is not inferred.
Unknown providers/units are not guessed.
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pandas as pd

CONTRACT_VERSION = "mac-factor-units-v1"


def _times(frame: pd.DataFrame) -> pd.Series:
    key = "datetime" if "datetime" in frame else "date"
    times = pd.to_datetime(frame[key], errors="raise")
    if times.isna().any() or not times.is_unique or not times.is_monotonic_increasing:
        raise ValueError("量额核验需要唯一、有效、升序的行情时间")
    return times.reset_index(drop=True)


def qualify_factor_fields(
    frame: pd.DataFrame,
    raw: pd.DataFrame,
    *,
    need_vwap: bool = False,
) -> pd.DataFrame:
    """Qualify all input rows without dropping/reordering/imputing observations.

    Both frames must come from the same requested symbol/range. The caller fetches
    raw bars with exactly that request. Date equality is mandatory; no inner join.
    Missing unit evidence or unavailable adjusted VWAP raises explicitly.
    """
    metadata = frame.attrs.get("snapshot_metadata", {})
    raw_metadata = raw.attrs.get("snapshot_metadata", {})
    if metadata.get("source") != "MAC" or raw_metadata.get("source") != "MAC":
        raise ValueError("因子量额单位目前仅核验 MAC 股票 K 线；不猜测其他来源单位")
    if raw_metadata.get("actual_adjust") != "NONE":
        raise ValueError("量额核验必须使用明确不复权行情")
    if metadata.get("actual_adjust") not in {"NONE", "QFQ", "HFQ"}:
        raise ValueError("因子行情缺少有效复权口径")
    category = metadata.get("category")
    if category != raw_metadata.get("category") or not category:
        raise ValueError("量额核验的行情周期不一致")
    if not _times(frame).equals(_times(raw)):
        raise ValueError("量额核验日期/数量不一致；未静默取交集或缩小样本")
    fields = ["open", "high", "low", "close", "vol", "amount"]
    for name, source in (("研究行情", frame), ("不复权行情", raw)):
        missing = set(fields) - set(source.columns)
        if missing:
            raise ValueError(f"{name}缺少量额核验字段：{', '.join(sorted(missing))}")
    left = frame[fields].apply(pd.to_numeric, errors="raise").reset_index(drop=True)
    right = raw[fields].apply(pd.to_numeric, errors="raise").reset_index(drop=True)
    if not np.isfinite(left.to_numpy()).all() or not np.isfinite(right.to_numpy()).all():
        raise ValueError("量额核验存在缺失或非有限原始输入；未补零")
    for prices in (left, right):
        if (prices[["open", "high", "low", "close"]] <= 0).any().any():
            raise ValueError("量额核验价格必须为正")
        if (
            (prices.high < prices[["open", "low", "close"]].max(axis=1))
            | (prices.low > prices[["open", "high", "close"]].min(axis=1))
        ).any():
            raise ValueError("量额核验的 OHLC 高低范围不合法")
    if metadata["actual_adjust"] == "NONE" and not left.equals(right):
        raise ValueError("两份不复权行情数值不一致；未混用不同快照")
    if (right[["vol", "amount"]] < 0).any().any():
        raise ValueError("成交量或成交额不能为负")
    if not np.allclose(left[["vol", "amount"]], right[["vol", "amount"]], rtol=1e-6, atol=0):
        raise ValueError("复权与不复权量额不同；未将其冒充实际成交股数")
    volume = right.vol
    if ((volume == 0) != (right.amount == 0)).any():
        raise ValueError("成交量与成交额的零值不一致，无法核验单位")
    traded = volume > 0
    if not traded.any():
        raise ValueError("样本内没有成交，缺少量额单位核验证据")
    mean = right.amount / volume.where(traded)
    # 1 cent for quoted-price rounding plus float32 decode precision. This is a
    # validation tolerance, NOT a unit search or an auto-rescaling heuristic.
    tolerance = 0.011 + right.high.abs() * 2e-6
    if ((mean < right.low - tolerance) | (mean > right.high + tolerance)).any():
        raise ValueError("成交额/成交股数超出不复权高低价；单位或上游行情不一致，未自动缩放")
    out = frame.copy()
    out["volume"] = volume.to_numpy()
    evidence: dict[str, Any] = {
        "version": CONTRACT_VERSION,
        "provider": "MAC",
        "volume_unit": "shares",
        "amount_unit": "CNY",
        "volume_adjustment": "actual_traded_shares_unadjusted",
        "unit_validation": "raw_amount_div_native_volume_within_raw_bar_range",
        "verified_rows": int(traded.sum()),
        "zero_volume_rows": int((~traded).sum()),
        "raw_adjust": "NONE",
        "price_adjust": metadata["actual_adjust"],
        "raw_data_fingerprint": hashlib.sha256(
            pd.util.hash_pandas_object(raw, index=True).values.tobytes()
        ).hexdigest(),
        "raw_observed_at": raw_metadata.get("observed_at"),
        "historical_data_vintage": False,
    }
    if need_vwap:
        if metadata["actual_adjust"] != "NONE":
            raise ValueError("复权 VWAP 缺少逐日价格变换依据；不从 OHLC 拟合或收盘价比例推断")
        out["vwap"] = mean.to_numpy()
        evidence.update(
            vwap_method="unadjusted_amount_div_actual_shares",
            vwap_invalid_rows=0,
            vwap_zero_volume_rows=int((~traded).sum()),
            vwap_note="仅不复权；停牌或零成交量时为空，未用收盘价或典型价填充",
        )
    out.attrs["factor_data_contract"] = evidence
    out.attrs["snapshot_metadata"] = {
        **metadata,
        "volume_policy": "实际成交股数，不作价格复权倒数缩放；已与同日期 MAC 不复权量额交叉核验",
    }
    return out
