"""日线 K 线数据读取（.day 文件）。"""

import struct
from pathlib import Path

from ..exceptions import TdxFileNotFoundError
from ..models.bar import SecurityBar
from .paths import _market_to_exchange, resolve_vipdoc

# struct 格式：日期(YYYYMMDD) 开盘 最高 最低 收盘 成交额 成交量 保留
# 全部为小端序，32 字节/条
_DAILY_FMT = struct.Struct("<IIIIIfII")

# 证券类型 → (价格系数, 量系数)
_SECURITY_COEFFICIENTS: dict[str, tuple[float, float]] = {
    "SH_A_STOCK": (0.01, 0.01),
    "SH_B_STOCK": (0.001, 0.01),
    "SH_INDEX": (0.01, 1.0),
    "SH_FUND": (0.001, 1.0),
    "SH_BOND": (0.001, 1.0),
    "SZ_A_STOCK": (0.01, 0.01),
    "SZ_B_STOCK": (0.01, 0.01),
    "SZ_INDEX": (0.01, 1.0),
    "SZ_FUND": (0.001, 0.01),
    "SZ_BOND": (0.001, 1.0),
}


def _detect_security_type(filename: str) -> str:
    """从文件名推断证券类型。

    文件名格式: {exchange}{code}.day，如 sh600000.day、sz000001.day

    依据上交所/深交所《证券代码段分配指南》判定。无法识别的代码段
    返回 "UNKNOWN"（而非默认深市 A 股），避免把基金/ETF/债券误判为股票。
    """
    base = Path(filename).name.lower()
    exchange = base[:2]  # "sh" or "sz"
    code_head = base[2:4]

    if exchange == "sz":
        if code_head in ("00", "30"):
            return "SZ_A_STOCK"
        if code_head == "20":
            return "SZ_B_STOCK"
        if code_head == "39":
            return "SZ_INDEX"
        if code_head in ("15", "16"):
            return "SZ_FUND"
        if code_head in ("17", "18"):  # 封闭式基金 / LOF / ETF
            return "SZ_FUND"
        if code_head in ("10", "11", "12", "13", "14"):
            return "SZ_BOND"
    elif exchange == "sh":
        if code_head == "60":
            return "SH_A_STOCK"
        if code_head == "68":  # 科创板（688 开头）
            return "SH_A_STOCK"
        if code_head == "90":
            return "SH_B_STOCK"
        if code_head in ("00", "88", "99"):
            return "SH_INDEX"
        if code_head in ("50", "51", "52", "53", "55", "56", "58"):
            # 501 LOF / 510-519 ETF / 520-529 ETF / 530-539 ETF
            # 550-556 货币ETF / 560-563 LOF / 588-589 科创板ETF
            return "SH_FUND"
        if code_head in ("01", "10", "11", "12", "13", "14"):
            return "SH_BOND"
        if code_head == "20":  # 国债逆回购（204xxx）
            return "SH_BOND"

    return "UNKNOWN"


def read_daily_bars(filepath: str | Path) -> list[SecurityBar]:
    """从本地 .day 文件读取日线 K 线数据。

    Args:
        filepath: .day 文件路径。

    Returns:
        SecurityBar 列表（按时间升序）。
    """
    filepath = Path(filepath)
    if not filepath.is_file():
        raise TdxFileNotFoundError(f"日线数据文件不存在: {filepath}")

    sec_type = _detect_security_type(filepath.name)
    price_coeff, vol_coeff = _SECURITY_COEFFICIENTS.get(sec_type, (0.01, 0.01))

    data = filepath.read_bytes()
    if len(data) < _DAILY_FMT.size:
        return []

    results: list[SecurityBar] = []
    record_size = _DAILY_FMT.size
    for offset in range(0, len(data) - record_size + 1, record_size):
        raw = data[offset : offset + record_size]
        date_int, op, hi, lo, cl, amount, vol, _res = _DAILY_FMT.unpack(raw)

        year = date_int // 10000
        month = (date_int % 10000) // 100
        day = date_int % 100

        results.append(
            SecurityBar(
                open=op * price_coeff,
                close=cl * price_coeff,
                high=hi * price_coeff,
                low=lo * price_coeff,
                vol=vol * vol_coeff,
                amount=amount,
                year=year,
                month=month,
                day=day,
                hour=0,
                minute=0,
                _raw=raw,
            )
        )

    return results


def find_daily_bar_file(
    market: int,
    code: str,
    vipdoc: str | Path | None = None,
) -> Path:
    """根据市场和代码定位日线文件路径。

    Args:
        market: 市场代码（Market.SZ=0, Market.SH=1）。
        code: 6 位股票代码。
        vipdoc: vipdoc 目录路径，None 则自动检测。

    Returns:
        .day 文件的 Path。
    """
    vipdoc_path = resolve_vipdoc(vipdoc)
    exchange = _market_to_exchange(market)
    return vipdoc_path / exchange / "lday" / f"{exchange}{code}.day"
