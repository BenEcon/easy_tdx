"""本地前复权（QFQ）重算。

通达信 MAC 服务端在 QFQ 模式下，对长期重度除权股票的深层历史页会返回
负价格（上游缺陷）。本模块用 NONE（未复权）K 线 + XDXR（除权除息）记录
在客户端本地重算前复权序列，作为服务端 QFQ 异常时的兜底。

公式（见 ``examples/06_finance/xdxr_info.py``）::

    复权价 = (原价 - 每股分红 + 每股配股价 × 每股配股比例) /
             (1 + 每股送转股比例 + 每股配股比例)

约定：以除权日**前一交易日**的收盘价（含权价 ``P_cum``）作为基准，前复权
因子把该日及之前的价格乘以::

    f = (P_cum - fenhong + peigujia × peigu) / (P_cum × (1 + songzhuangu + peigu))

这样调整后的价格在除权日前后连续（除权日开盘价 ≈ 含权收盘价 - 分红）。
最新价不动（锚定最新）。fenhong/songzhuangu/peigu 为每股单位，peigujia 为元/股。
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

_logger = logging.getLogger(__name__)

# 前复权会同比缩放的 OHLC 列名（vol/amount 不动）
_OHLC_COLS = ("open", "high", "low", "close")


def compute_forward_factor(
    cum_close: float,
    fenhong: float,
    peigujia: float,
    songzhuangu: float,
    peigu: float,
) -> float:
    """计算单次除权除息事件的前复权乘子。

    Args:
        cum_close: 除权日前一交易日的 NONE 收盘价（含权价）。
        fenhong: 每股分红（元）。
        peigujia: 每股配股价（元/股）。
        songzhuangu: 每股送转股比例（如 0.1 = 10 送/转 1）。
        peigu: 每股配股比例。

    Returns:
        前复权因子。若输入非法（cum_close<=0、分母为 0、结果非有限）返回 NaN。
    """
    if cum_close <= 0:
        return float("nan")
    denom = cum_close * (1.0 + songzhuangu + peigu)
    if denom == 0:
        return float("nan")
    factor = (cum_close - fenhong + peigujia * peigu) / denom
    if not np.isfinite(factor):
        return float("nan")
    return float(factor)


def apply_forward_adjust(
    df: pd.DataFrame,
    xdxr_df: pd.DataFrame,
) -> pd.DataFrame:
    """对 NONE K 线应用前复权，返回新的 DataFrame。

    遍历 XDXR 中 category==1（除权除息）的事件，按日期升序，把每个事件
    的因子累乘到该除权日**前一交易日及之前**所有 bar 的 OHLC。最新价锚定不动。

    Args:
        df: NONE K 线，必须含 ``datetime`` 列与 OHLC 列。
        xdxr_df: ``get_xdxr_info`` 返回的 DataFrame，含 ``date``、``category``、
            ``fenhong``、``peigujia``、``songzhuangu``、``peigu`` 列。

    Returns:
        前复权后的 DataFrame（与输入同形状、同列、同索引）。无事件或异常时
        原样返回。
    """
    out = df.copy()
    ohlc_cols = [c for c in _OHLC_COLS if c in out.columns]
    if not ohlc_cols or "datetime" not in out.columns or xdxr_df is None or xdxr_df.empty:
        return out

    # 统一 datetime 为 pandas Timestamp（升序）
    dt = pd.to_datetime(out["datetime"])
    if not dt.is_monotonic_increasing:
        order = np.argsort(dt.to_numpy())
        out = out.iloc[order].reset_index(drop=True)
        dt = pd.to_datetime(out["datetime"])
    dt_arr = dt.to_numpy()

    # 筛选 category==1 且至少有一个非空除权字段的事件
    if "category" not in xdxr_df.columns or "date" not in xdxr_df.columns:
        return out
    cat1 = xdxr_df[xdxr_df["category"] == 1]
    events: list[tuple[pd.Timestamp, float, float, float, float]] = []
    for _, r in cat1.iterrows():
        fh = _to_float(r.get("fenhong"))
        pjk = _to_float(r.get("peigujia"))
        sz = _to_float(r.get("songzhuangu"))
        pg = _to_float(r.get("peigu"))
        if fh is None and pjk is None and sz is None and pg is None:
            continue
        try:
            ed = pd.Timestamp(str(r["date"]))
        except (ValueError, TypeError):
            continue
        events.append((ed, fh or 0.0, pjk or 0.0, sz or 0.0, pg or 0.0))
    if not events:
        return out
    events.sort(key=lambda e: e[0])

    # 取除权日前一交易日的 NONE 收盘价（cum-div close）作为基准
    none_close = out["close"].to_numpy(dtype=float) if "close" in out.columns else None

    for col in ohlc_cols:
        arr = out[col].to_numpy(dtype=float).copy()
        for ed, fh, pjk, sz, pg in events:
            # searchsorted(>=): 第一个 >= ex-date 的位置；其前一根即为含权收盘
            idx = int(np.searchsorted(dt_arr, np.datetime64(ed), side="left"))
            cum_idx = idx - 1
            if cum_idx < 0 or cum_idx >= len(arr):
                continue
            if none_close is not None:
                cum_close = float(none_close[cum_idx])
            else:
                cum_close = float(arr[cum_idx])
            factor = compute_forward_factor(cum_close, fh, pjk, sz, pg)
            if not np.isfinite(factor):
                _logger.warning(
                    "QFQ 本地重算：事件 %s 因子非法（cum_close=%s fh=%s sz=%s pg=%s），跳过",
                    ed.date(),
                    cum_close,
                    fh,
                    sz,
                    pg,
                )
                continue
            arr[: cum_idx + 1] *= factor
        out[col] = arr

    return out


def _to_float(v: object) -> float | None:
    """安全转 float，None/NaN 返回 None。"""
    if v is None:
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return f


def has_bad_prices(df: pd.DataFrame) -> bool:
    """检测 QFQ 结果是否含非法价格（<=0 或非有限值）。

    Args:
        df: 待检测的 K 线 DataFrame。

    Returns:
        任一 OHLC 列含 <=0 或 NaN/inf 时返回 True。
    """
    for col in _OHLC_COLS:
        if col not in df.columns:
            continue
        arr = df[col].to_numpy(dtype=float)
        if not np.all(np.isfinite(arr)):
            return True
        if np.any(arr <= 0):
            return True
    return False
