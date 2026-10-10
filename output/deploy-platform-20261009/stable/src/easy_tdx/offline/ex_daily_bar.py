"""扩展市场日线数据读取（期货、港股等 .day 文件）。"""

import struct
from dataclasses import dataclass, field
from pathlib import Path

from ..exceptions import TdxFileNotFoundError

# 日期(4B) 开盘(4Bf) 最高(4Bf) 最低(4Bf) 收盘(4Bf) 成交额(4B) 成交量(4B) 结算价(4Bf)
_EX_DAILY_FMT = struct.Struct("<IffffIIf")


@dataclass
class ExDailyBar:
    """扩展市场日线（期货/港股等，含结算价）。"""

    open: float
    high: float
    low: float
    close: float
    amount: int
    vol: int
    settlement: float
    hk_stock_amount: float
    year: int
    month: int
    day: int
    _raw: bytes = field(default=b"", repr=False, compare=False)


def read_ex_daily_bars(filepath: str | Path) -> list[ExDailyBar]:
    """从本地扩展市场 .day 文件读取日线数据。

    文件位于 vipdoc/ds/ 目录下，如 29#A1801.day。

    Args:
        filepath: .day 文件路径。

    Returns:
        ExDailyBar 列表（按时间升序）。
    """
    filepath = Path(filepath)
    if not filepath.is_file():
        raise TdxFileNotFoundError(f"扩展市场日线文件不存在: {filepath}")

    data = filepath.read_bytes()
    if len(data) < _EX_DAILY_FMT.size:
        return []

    results: list[ExDailyBar] = []
    record_size = _EX_DAILY_FMT.size

    for offset in range(0, len(data) - record_size + 1, record_size):
        raw = data[offset : offset + record_size]
        date_int, op, hi, lo, cl, amt, vol, settlement = _EX_DAILY_FMT.unpack(raw)

        # 第 5 个字段（成交额位置）重新解释为 float 作为港股量
        hk_bytes = struct.pack("<I", amt)
        (hk_stock_amount,) = struct.unpack("<f", hk_bytes)

        year = date_int // 10000
        month = (date_int % 10000) // 100
        day = date_int % 100

        results.append(
            ExDailyBar(
                open=op,
                high=hi,
                low=lo,
                close=cl,
                amount=vol,
                vol=vol,
                settlement=settlement,
                hk_stock_amount=hk_stock_amount,
                year=year,
                month=month,
                day=day,
                _raw=raw,
            )
        )

    return results
