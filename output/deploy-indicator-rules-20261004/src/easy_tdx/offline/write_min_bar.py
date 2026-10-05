"""离线分钟线写入 —— 将 SecurityBar 编码并追加到 .5 / .lc1 / .lc5 文件。"""

from __future__ import annotations

from pathlib import Path

from ..models.bar import SecurityBar
from .min_bar import _LC_MIN_FMT, _MIN_FMT

__all__ = [
    "encode_5min_bar",
    "encode_lc_min_bar",
    "append_5min_bars",
    "append_lc_min_bars",
    "get_last_5min_bar_datetime",
    "get_last_lc_min_bar_datetime",
]


# ---------------------------------------------------------------------------
# date/time 编码（与 min_bar._decode_tdx_date/time 互逆）
# ---------------------------------------------------------------------------


def _encode_tdx_date(year: int, month: int, day: int) -> int:
    """将 (year, month, day) 编码为 2 字节压缩日期。"""
    return (year - 2004) * 2048 + month * 100 + day


def _encode_tdx_time(hour: int, minute: int) -> int:
    """将 (hour, minute) 编码为从 0:00 起的分钟数。"""
    return hour * 60 + minute


def _bar_datetime_key(bar: SecurityBar) -> tuple[int, int, int, int, int]:
    return (bar.year, bar.month, bar.day, bar.hour, bar.minute)


# ---------------------------------------------------------------------------
# .5 文件 (OHLC 为整数 / 100)
# ---------------------------------------------------------------------------


def encode_5min_bar(bar: SecurityBar) -> bytes:
    """将 SecurityBar 编码为 32 字节 .5 记录。

    OHLC 为整数（实际价格 × 100），amount 为 float32。
    """
    return _MIN_FMT.pack(
        _encode_tdx_date(bar.year, bar.month, bar.day),
        _encode_tdx_time(bar.hour, bar.minute),
        int(round(bar.open * 100)),
        int(round(bar.high * 100)),
        int(round(bar.low * 100)),
        int(round(bar.close * 100)),
        bar.amount,  # float32
        int(round(bar.vol)),
        0,  # reserved
    )


def get_last_5min_bar_datetime(
    filepath: str | Path,
) -> tuple[int, int, int, int, int] | None:
    """读取 .5 文件最后一条记录的日期时间。

    Returns:
        (year, month, day, hour, minute) 元组，文件为空时返回 None。
    """
    filepath = Path(filepath)
    if not filepath.is_file():
        return None
    size = filepath.stat().st_size
    if size < _MIN_FMT.size:
        return None
    with filepath.open("rb") as f:
        f.seek(size - _MIN_FMT.size)
        last_record = f.read(_MIN_FMT.size)
    from .min_bar import _decode_tdx_date, _decode_tdx_time

    date_num, time_num, *_ = _MIN_FMT.unpack(last_record)
    year, month, day = _decode_tdx_date(date_num)
    hour, minute = _decode_tdx_time(time_num)
    return (year, month, day, hour, minute)


def append_5min_bars(
    filepath: str | Path,
    bars: list[SecurityBar],
) -> int:
    """将 5 分钟线 bars 追加写入 .5 文件，自动跳过重复时间点。

    Returns:
        实际写入的记录数。
    """
    filepath = Path(filepath)
    last_dt = get_last_5min_bar_datetime(filepath)

    if last_dt is not None:
        new_bars = [b for b in bars if _bar_datetime_key(b) > last_dt]
    else:
        new_bars = list(bars)

    if not new_bars:
        return 0

    encoded = b"".join(encode_5min_bar(b) for b in new_bars)
    with filepath.open("ab") as f:
        f.write(encoded)

    return len(new_bars)


# ---------------------------------------------------------------------------
# .lc1 / .lc5 文件 (OHLC 为 float32)
# ---------------------------------------------------------------------------


def encode_lc_min_bar(bar: SecurityBar) -> bytes:
    """将 SecurityBar 编码为 32 字节 .lc1/.lc5 记录。

    OHLC 为 float32，无需系数转换。
    """
    return _LC_MIN_FMT.pack(
        _encode_tdx_date(bar.year, bar.month, bar.day),
        _encode_tdx_time(bar.hour, bar.minute),
        bar.open,
        bar.high,
        bar.low,
        bar.close,
        bar.amount,  # float32
        int(round(bar.vol)),
        0,  # reserved
    )


def get_last_lc_min_bar_datetime(
    filepath: str | Path,
) -> tuple[int, int, int, int, int] | None:
    """读取 .lc1/.lc5 文件最后一条记录的日期时间。

    Returns:
        (year, month, day, hour, minute) 元组，文件为空时返回 None。
    """
    filepath = Path(filepath)
    if not filepath.is_file():
        return None
    size = filepath.stat().st_size
    if size < _LC_MIN_FMT.size:
        return None
    with filepath.open("rb") as f:
        f.seek(size - _LC_MIN_FMT.size)
        last_record = f.read(_LC_MIN_FMT.size)
    from .min_bar import _decode_tdx_date, _decode_tdx_time

    date_num, time_num, *_ = _LC_MIN_FMT.unpack(last_record)
    year, month, day = _decode_tdx_date(date_num)
    hour, minute = _decode_tdx_time(time_num)
    return (year, month, day, hour, minute)


def append_lc_min_bars(
    filepath: str | Path,
    bars: list[SecurityBar],
) -> int:
    """将分钟线 bars 追加写入 .lc1/.lc5 文件，自动跳过重复时间点。

    Returns:
        实际写入的记录数。
    """
    filepath = Path(filepath)
    last_dt = get_last_lc_min_bar_datetime(filepath)

    if last_dt is not None:
        new_bars = [b for b in bars if _bar_datetime_key(b) > last_dt]
    else:
        new_bars = list(bars)

    if not new_bars:
        return 0

    encoded = b"".join(encode_lc_min_bar(b) for b in new_bars)
    with filepath.open("ab") as f:
        f.write(encoded)

    return len(new_bars)
