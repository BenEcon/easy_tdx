"""离线日线数据写入 —— 将 SecurityBar 编码并追加到 .day 文件。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from ..models.bar import SecurityBar
from .daily_bar import _DAILY_FMT

__all__ = [
    "encode_daily_bar",
    "append_daily_bars",
    "get_last_bar_date",
    "sync_daily_bars_from_security_bars",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# encode
# ---------------------------------------------------------------------------


def encode_daily_bar(
    bar: SecurityBar,
    price_coeff: float,
    vol_coeff: float,
) -> bytes:
    """将 SecurityBar 编码为 32 字节 .day 记录。

    Args:
        bar: K 线数据（open/close/high/low 为实际价格，非整数）。
        price_coeff: 价格系数（A 股 0.01，基金 0.001 等）。
        vol_coeff: 成交量系数（A 股 0.01，指数 1.0 等）。

    Returns:
        32 字节的二进制记录。
    """
    date_int = bar.year * 10000 + bar.month * 100 + bar.day
    return _DAILY_FMT.pack(
        date_int,
        int(round(bar.open / price_coeff)),
        int(round(bar.high / price_coeff)),
        int(round(bar.low / price_coeff)),
        int(round(bar.close / price_coeff)),
        bar.amount,  # float32, 由 struct 自动截断
        int(round(bar.vol / vol_coeff)),
        0,  # reserved
    )


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


def get_last_bar_date(filepath: str | Path) -> int | None:
    """读取 .day 文件最后一条完整记录的日期（纯读，无副作用）。

    若文件尾部存在不完整记录（size 非 32 的整数倍，通常由上次写入中途崩溃/
    断电导致），只告警并跳过损坏尾部，返回最后一条完整记录的日期——
    不修改文件（遵守 command-query separation，"get" 不应写）。
    损坏尾部的清理由 :func:`_repair_tail` 在写入路径统一完成。

    Returns:
        YYYYMMDD 整数，文件为空/太短/无完整记录时返回 None。
    """
    filepath = Path(filepath)
    if not filepath.is_file():
        return None
    size = filepath.stat().st_size
    if size < _DAILY_FMT.size:
        return None
    # 完整性检查：非整数倍说明尾部有半条损坏记录，跳过它读最后一条完整记录。
    remainder = size % _DAILY_FMT.size
    if remainder != 0:
        logger.warning(
            "%s 大小 %d 不是 %d 的整数倍，尾部 %d 字节为损坏记录，"
            "将读取最后一条完整记录（文件未修改，写入时由 _repair_tail 清理）",
            filepath,
            size,
            _DAILY_FMT.size,
            remainder,
        )
        size -= remainder
        if size < _DAILY_FMT.size:
            return None
    with filepath.open("rb") as f:
        f.seek(size - _DAILY_FMT.size)
        last_record = f.read(_DAILY_FMT.size)
    (date_int, *_) = _DAILY_FMT.unpack(last_record)
    return int(date_int)


def _repair_tail(filepath: Path) -> None:
    """截断文件尾部的损坏记录（非整数倍 32 字节的残余）。

    仅在写入路径调用，保证 get_last_bar_date 这类查询函数无副作用（审计 #1）。
    """
    if not filepath.is_file():
        return
    size = filepath.stat().st_size
    remainder = size % _DAILY_FMT.size
    if remainder != 0:
        logger.warning(
            "%s 尾部 %d 字节为损坏记录，写入前截断到最后一条完整记录",
            filepath,
            remainder,
        )
        with filepath.open("r+b") as f:
            f.truncate(size - remainder)


def _bar_date_int(bar: SecurityBar) -> int:
    return bar.year * 10000 + bar.month * 100 + bar.day


# ---------------------------------------------------------------------------
# append
# ---------------------------------------------------------------------------


def append_daily_bars(
    filepath: str | Path,
    bars: list[SecurityBar],
    price_coeff: float,
    vol_coeff: float,
) -> int:
    """将 bars 追加写入 .day 文件，自动跳过重复日期。

    Args:
        filepath: .day 文件路径。
        bars: 待写入的 K 线列表（按时间升序）。
        price_coeff: 价格系数。
        vol_coeff: 成交量系数。

    Returns:
        实际写入的记录数。
    """
    filepath = Path(filepath)

    # 写入前清理上次崩溃可能残留的尾部半条记录（审计 #1）
    _repair_tail(filepath)

    # 获取文件末尾日期，用于去重
    last_date = get_last_bar_date(filepath)

    # 过滤出日期严格大于末尾的新记录
    new_bars = (
        [b for b in bars if _bar_date_int(b) > last_date] if last_date is not None else list(bars)
    )

    if not new_bars:
        return 0

    encoded = b"".join(encode_daily_bar(b, price_coeff, vol_coeff) for b in new_bars)
    with filepath.open("ab") as f:
        f.write(encoded)
        # flush + fsync 确保落盘，避免进程崩溃/断电导致文件尾部残留半条记录
        # （32 字节记录的非原子追加会损坏 get_last_bar_date 的去重依据）。
        f.flush()
        os.fsync(f.fileno())

    return len(new_bars)


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


def sync_daily_bars_from_security_bars(
    filepath: str | Path,
    server_bars: list[SecurityBar],
    price_coeff: float,
    vol_coeff: float,
) -> int:
    """将服务端获取的日线数据同步写入本地 .day 文件。

    完整流程：读取文件末尾日期 → 过滤新数据 → 追加写入。

    Args:
        filepath: .day 文件路径。
        server_bars: 服务端返回的日线数据（按时间升序）。
        price_coeff: 价格系数。
        vol_coeff: 成交量系数。

    Returns:
        实际写入的记录数。
    """
    return append_daily_bars(filepath, server_bars, price_coeff, vol_coeff)
