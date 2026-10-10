"""分钟 K 线数据读取（.5 文件和 .lc1/.lc5 文件）。"""

import struct
from pathlib import Path

from ..exceptions import TdxFileNotFoundError
from ..models.bar import SecurityBar

# .5 文件: 日期(2B) 时间(2B) 开盘(4B) 最高(4B) 最低(4B) 收盘(4B) 额(4B) 量(4B) 保留(4B)
_MIN_FMT = struct.Struct("<HHIIIIfII")

# .lc1/.lc5 文件: 日期(2B) 时间(2B) 开(4Bf) 高(4Bf) 低(4Bf) 收(4Bf) 额(4Bf) 量(4B) 保留(4B)
_LC_MIN_FMT = struct.Struct("<HHfffffII")


def _decode_tdx_date(num: int) -> tuple[int, int, int]:
    """解码通达信压缩日期（2 字节）。"""
    year = num // 2048 + 2004
    month = (num % 2048) // 100
    day = (num % 2048) % 100
    return year, month, day


def _decode_tdx_time(num: int) -> tuple[int, int]:
    """解码通达信分钟时间（从 0:00 开始的分钟数）。"""
    return num // 60, num % 60


def read_5min_bars(filepath: str | Path) -> list[SecurityBar]:
    """从本地 .5 文件读取 5 分钟 K 线数据。

    OHLC 为整数，需除以 100 得到实际价格。

    Args:
        filepath: .5 文件路径。

    Returns:
        SecurityBar 列表（按时间升序）。
    """
    filepath = Path(filepath)
    if not filepath.is_file():
        raise TdxFileNotFoundError(f"分钟线数据文件不存在: {filepath}")

    data = filepath.read_bytes()
    if len(data) < _MIN_FMT.size:
        return []

    results: list[SecurityBar] = []
    record_size = _MIN_FMT.size
    for offset in range(0, len(data) - record_size + 1, record_size):
        raw = data[offset : offset + record_size]
        date_num, time_num, op, hi, lo, cl, amount, vol, _res = _MIN_FMT.unpack(raw)

        year, month, day = _decode_tdx_date(date_num)
        hour, minute = _decode_tdx_time(time_num)

        results.append(
            SecurityBar(
                open=op / 100.0,
                close=cl / 100.0,
                high=hi / 100.0,
                low=lo / 100.0,
                vol=vol,
                amount=amount,
                year=year,
                month=month,
                day=day,
                hour=hour,
                minute=minute,
                _raw=raw,
            )
        )

    return results


def read_lc_min_bars(filepath: str | Path) -> list[SecurityBar]:
    """从本地 .lc1/.lc5 文件读取分钟 K 线数据。

    OHLC 为 float 类型，无需额外转换。

    Args:
        filepath: .lc1 或 .lc5 文件路径。

    Returns:
        SecurityBar 列表（按时间升序）。
    """
    filepath = Path(filepath)
    if not filepath.is_file():
        raise TdxFileNotFoundError(f"分钟线数据文件不存在: {filepath}")

    data = filepath.read_bytes()
    if len(data) < _LC_MIN_FMT.size:
        return []

    results: list[SecurityBar] = []
    record_size = _LC_MIN_FMT.size
    for offset in range(0, len(data) - record_size + 1, record_size):
        raw = data[offset : offset + record_size]
        date_num, time_num, op, hi, lo, cl, amount, vol, _res = _LC_MIN_FMT.unpack(raw)

        year, month, day = _decode_tdx_date(date_num)
        hour, minute = _decode_tdx_time(time_num)

        results.append(
            SecurityBar(
                open=op,
                close=cl,
                high=hi,
                low=lo,
                vol=vol,
                amount=amount,
                year=year,
                month=month,
                day=day,
                hour=hour,
                minute=minute,
                _raw=raw,
            )
        )

    return results
