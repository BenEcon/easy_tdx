"""离线扩展市场日线写入 —— 将 ExDailyBar 编码并追加到 .day 文件。"""

from __future__ import annotations

from pathlib import Path

from .ex_daily_bar import _EX_DAILY_FMT, ExDailyBar

__all__ = [
    "encode_ex_daily_bar",
    "append_ex_daily_bars",
    "get_last_ex_bar_date",
    "sync_ex_daily_bars",
]


def encode_ex_daily_bar(bar: ExDailyBar) -> bytes:
    """将 ExDailyBar 编码为 32 字节扩展市场 .day 记录。

    扩展市场价格直接为 float32，无需系数转换。
    """
    date_int = bar.year * 10000 + bar.month * 100 + bar.day
    return _EX_DAILY_FMT.pack(
        date_int,
        bar.open,
        bar.high,
        bar.low,
        bar.close,
        bar.amount,
        bar.vol,
        bar.settlement,
    )


def get_last_ex_bar_date(filepath: str | Path) -> int | None:
    """读取扩展市场 .day 文件最后一条记录的日期。

    Returns:
        YYYYMMDD 整数，文件为空或太短时返回 None。
    """
    filepath = Path(filepath)
    if not filepath.is_file():
        return None
    size = filepath.stat().st_size
    if size < _EX_DAILY_FMT.size:
        return None
    with filepath.open("rb") as f:
        f.seek(size - _EX_DAILY_FMT.size)
        last_record = f.read(_EX_DAILY_FMT.size)
    (date_int, *_) = _EX_DAILY_FMT.unpack(last_record)
    return int(date_int)


def _bar_date_int(bar: ExDailyBar) -> int:
    return bar.year * 10000 + bar.month * 100 + bar.day


def append_ex_daily_bars(
    filepath: str | Path,
    bars: list[ExDailyBar],
) -> int:
    """将扩展市场 bars 追加写入 .day 文件，自动跳过重复日期。

    Returns:
        实际写入的记录数。
    """
    filepath = Path(filepath)
    last_date = get_last_ex_bar_date(filepath)

    new_bars = (
        [b for b in bars if _bar_date_int(b) > last_date] if last_date is not None else list(bars)
    )

    if not new_bars:
        return 0

    encoded = b"".join(encode_ex_daily_bar(b) for b in new_bars)
    with filepath.open("ab") as f:
        f.write(encoded)

    return len(new_bars)


def sync_ex_daily_bars(
    filepath: str | Path,
    server_bars: list[ExDailyBar],
) -> int:
    """将服务端获取的扩展市场日线同步写入本地 .day 文件。

    Returns:
        实际写入的记录数。
    """
    return append_ex_daily_bars(filepath, server_bars)
