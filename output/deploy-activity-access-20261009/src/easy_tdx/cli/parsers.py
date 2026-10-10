"""CLI 参数解析工具。"""

from __future__ import annotations

import click

from ..mac.enums import (
    Adjust,
    BoardType,
    Category,
    ExMarket,
    Period,
    SortOrder,
    SortType,
)
from ..models.enums import Market

_MARKET_MAP: dict[str, Market] = {
    "SZ": Market.SZ,
    "SH": Market.SH,
    "BJ": Market.BJ,
    "0": Market.SZ,
    "1": Market.SH,
    "2": Market.BJ,
}


def parse_market(s: str) -> int:
    """Parse market string to int value. Accepts 'SZ', 'SH', 'BJ', '0', '1', '2'."""
    s_upper = s.upper()
    if s_upper in _MARKET_MAP:
        return _MARKET_MAP[s_upper]
    return int(s)


_PERIOD_MAP: dict[str, Period] = {
    "1MIN": Period.MIN_1,
    "1": Period.MIN_1,
    "5MIN": Period.MIN_5,
    "5": Period.MIN_5,
    "15MIN": Period.MIN_15,
    "15": Period.MIN_15,
    "30MIN": Period.MIN_30,
    "30": Period.MIN_30,
    "60MIN": Period.MIN_60,
    "60": Period.MIN_60,
    "DAILY": Period.DAILY,
    "D": Period.DAILY,
    "WEEKLY": Period.WEEKLY,
    "W": Period.WEEKLY,
    "MONTHLY": Period.MONTHLY,
    "M": Period.MONTHLY,
    "YEARLY": Period.YEARLY,
    "Y": Period.YEARLY,
}


def parse_period(s: str) -> Period:
    """Parse period string."""
    s_upper = s.upper()
    if s_upper in _PERIOD_MAP:
        return _PERIOD_MAP[s_upper]
    return Period(int(s))


_ADJUST_MAP: dict[str, Adjust] = {
    "NONE": Adjust.NONE,
    "0": Adjust.NONE,
    "QFQ": Adjust.QFQ,
    "1": Adjust.QFQ,
    "FQ": Adjust.QFQ,
    "HFQ": Adjust.HFQ,
    "2": Adjust.HFQ,
}


def parse_adjust(s: str) -> Adjust:
    """Parse adjust string."""
    s_upper = s.upper()
    if s_upper in _ADJUST_MAP:
        return _ADJUST_MAP[s_upper]
    return Adjust(int(s))


_BOARD_TYPE_MAP: dict[str, BoardType] = {
    "HY": BoardType.HY,
    "INDUSTRY": BoardType.HY,
    "GN": BoardType.GN,
    "CONCEPT": BoardType.GN,
    "FG": BoardType.FG,
    "STYLE": BoardType.FG,
    "DQ": BoardType.DQ,
    "REGION": BoardType.DQ,
    "ALL": BoardType.ALL,
}


def parse_board_type(s: str) -> BoardType:
    """Parse board type string."""
    s_upper = s.upper()
    if s_upper in _BOARD_TYPE_MAP:
        return _BOARD_TYPE_MAP[s_upper]
    return BoardType(int(s))


def parse_ex_market(s: str) -> int:
    """Parse extended market string to int value."""
    s_upper = s.upper()
    for member in ExMarket:
        if member.name == s_upper:
            return member.value
    _EX_MAP: dict[str, ExMarket] = {
        "HK": ExMarket.HK_MAIN_BOARD,
        "HK_MAIN_BOARD": ExMarket.HK_MAIN_BOARD,
        "US": ExMarket.US_STOCK,
        "US_STOCK": ExMarket.US_STOCK,
        "SH_FUTURES": ExMarket.SH_FUTURES,
        "DCE": ExMarket.DL_FUTURES,
        "CZCE": ExMarket.ZZ_FUTURES,
        "CFFEX": ExMarket.CFFEX_FUTURES,
        "INE": ExMarket.SH_GOLD,
        "GFEX": ExMarket.GZ_FUTURES,
    }
    if s_upper in _EX_MAP:
        return _EX_MAP[s_upper].value
    return int(s)


_CATEGORY_MAP: dict[str, Category] = {
    "A": Category.A,
    "全A": Category.A,
    "B": Category.B,
    "KCB": Category.KCB,
    "CYB": Category.CYB,
    "BJ": Category.BJ,
    "SH": Category.SH,
    "SZ": Category.SZ,
}


def parse_category(s: str) -> Category:
    """Parse category string to Category enum."""
    s_upper = s.upper()
    for member in Category:
        if member.name == s_upper:
            return member
    if s_upper in _CATEGORY_MAP:
        return _CATEGORY_MAP[s_upper]
    return Category(int(s))


def parse_sort_type(s: str) -> SortType:
    """Parse sort type string."""
    s_upper = s.upper()
    for member in SortType:
        if member.name == s_upper:
            return member
    return SortType(int(s))


_SORT_ORDER_MAP: dict[str, SortOrder] = {
    "ASC": SortOrder.ASC,
    "DESC": SortOrder.DESC,
    "NONE": SortOrder.NONE,
}


def parse_sort_order(s: str) -> SortOrder:
    """Parse sort order string."""
    s_upper = s.upper()
    if s_upper in _SORT_ORDER_MAP:
        return _SORT_ORDER_MAP[s_upper]
    return SortOrder(int(s))


def parse_stocks(s: str) -> list[tuple[int, str]]:
    """Parse stock list like 'SZ 000001,SH 600000' into [(0, '000001'), (1, '600000')]."""
    result: list[tuple[int, str]] = []
    for pair in s.split(","):
        pair = pair.strip()
        parts = pair.split()
        if len(parts) == 2:
            market = parse_market(parts[0])
            code = parts[1]
            result.append((market, code))
        elif len(parts) == 1:
            click.echo(f"Warning: skipping ambiguous stock spec '{pair}'", err=True)
    return result
