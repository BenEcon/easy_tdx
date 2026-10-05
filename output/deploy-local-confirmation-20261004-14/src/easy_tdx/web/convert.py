"""共享参数转换工具（字符串 → 枚举）。"""

from __future__ import annotations

from typing import Any

from easy_tdx.web.schemas import KlineCategoryEnum, MarketEnum


def market_from_str(s: str) -> Any:
    """将字符串转为 Market 枚举，支持大小写，非法值抛 ValueError。

    >>> market_from_str("SZ")  # 正常
    >>> market_from_str("sz")  # 也正常（自动转大写）
    >>> market_from_str("ZZZ")  # ValueError
    """
    from easy_tdx.models.enums import Market

    key = s.upper()
    try:
        return Market[MarketEnum[key].name]
    except KeyError:
        valid = ", ".join(m.name for m in MarketEnum)
        raise ValueError(f"无效市场代码 '{s}'，可选值: {valid}") from None


def market_value_from_str(s: str) -> int:
    """将市场字符串转为 int 值（MAC 客户端使用 int 而非枚举）。"""
    return int(market_from_str(s).value)


def category_from_str(s: str) -> Any:
    """将字符串转为 KlineCategory 枚举，支持大小写和数字字符串。"""
    from easy_tdx.models.enums import KlineCategory

    key = s.upper()
    # 支持纯数字（如 "4" 表示日线）
    try:
        return KlineCategory(int(key))
    except (ValueError, TypeError):
        pass
    try:
        return KlineCategory[KlineCategoryEnum[key].name]
    except KeyError:
        valid = ", ".join(c.name for c in KlineCategoryEnum)
        raise ValueError(f"无效K线周期 '{s}'，可选值: {valid}") from None


# ---------------------------------------------------------------------------
# MAC 枚举转换器
# ---------------------------------------------------------------------------


def board_type_from_str(s: str) -> Any:
    """将字符串转为 BoardType 枚举（ALL/HY/HY2/GN/FG/DQ/...）。"""
    from easy_tdx.mac.enums import BoardType

    key = s.upper()
    try:
        return BoardType[key]
    except KeyError:
        pass
    try:
        return BoardType(int(key))
    except (ValueError, TypeError):
        pass
    valid = ", ".join(m.name for m in BoardType)
    raise ValueError(f"无效板块类型 '{s}'，可选值: {valid}") from None


def board_sort_from_str(s: str) -> Any:
    """将字符串转为 BoardSortColumn 枚举（CHANGE_PCT/SPEED/CHANGE_3D/...）。"""
    from easy_tdx.mac.enums import BoardSortColumn

    key = s.upper()
    try:
        return BoardSortColumn[key]
    except KeyError:
        pass
    try:
        return BoardSortColumn(int(key))
    except (ValueError, TypeError):
        pass
    valid = ", ".join(m.name for m in BoardSortColumn)
    raise ValueError(f"无效板块排序键 '{s}'，可选值: {valid}") from None


def sort_type_from_str(s: str) -> Any:
    """将字符串转为 SortType 枚举（CHANGE_PCT/VOLUME/... 或 hex 数字）。"""
    from easy_tdx.mac.enums import SortType

    key = s.upper()
    try:
        return SortType[key]
    except KeyError:
        pass
    try:
        return SortType(int(key, 0))  # 支持 hex 如 "0x0E"
    except (ValueError, TypeError):
        pass
    valid = ", ".join(m.name for m in SortType)
    raise ValueError(f"无效排序字段 '{s}'，可选值: {valid}") from None


def sort_order_from_str(s: str) -> Any:
    """将字符串转为 SortOrder 枚举（ASC/DESC）。"""
    from easy_tdx.mac.enums import SortOrder

    key = s.upper()
    try:
        return SortOrder[key]
    except KeyError:
        pass
    try:
        return SortOrder(int(key))
    except (ValueError, TypeError):
        pass
    valid = ", ".join(m.name for m in SortOrder)
    raise ValueError(f"无效排序方向 '{s}'，可选值: {valid}") from None


def period_times_from_category(category: Any) -> tuple[Any, int]:
    """将标准 KlineCategory 映射到 MAC 的 (Period, times)。

    标准协议的 KlineCategory 与 MAC 协议的 Period 枚举值并非一一对应
    （如 YEAR=9 而 YEARLY=11），且 MAC 用 Period+times 表达多周期。这里做
    显式查表，times 一律为 1（KlineCategory 无多周期概念）。

    Args:
        category: ``KlineCategory`` 枚举值（或其 int）。

    Returns:
        ``(Period, times)`` 元组。

    Raises:
        ValueError: 无法映射的 KlineCategory 值。
    """
    from easy_tdx.mac.enums import Period

    # 显式查表：标准 KlineCategory 值 → (Period, times)
    # 注意 YEAR(9)→YEARLY(11)、SEASON(10)→QUARTERLY(10) 值/名不同
    mapping = {
        0: (Period.MIN_5, 1),  # KlineCategory.MIN_5
        1: (Period.MIN_15, 1),  # KlineCategory.MIN_15
        2: (Period.MIN_30, 1),  # KlineCategory.MIN_30
        3: (Period.MIN_60, 1),  # KlineCategory.MIN_60
        4: (Period.DAILY, 1),  # KlineCategory.DAY
        5: (Period.WEEKLY, 1),  # KlineCategory.WEEK
        6: (Period.MONTHLY, 1),  # KlineCategory.MONTH
        7: (Period.MIN_1, 1),  # KlineCategory.MIN_1
        9: (Period.YEARLY, 1),  # KlineCategory.YEAR（值 9→Period.YEARLY 值 11）
        10: (Period.QUARTERLY, 1),  # KlineCategory.SEASON → Period.QUARTERLY
    }
    key = int(category)
    if key not in mapping:
        valid = "MIN_1/5/15/30/60, DAY, WEEK, MONTH, SEASON, YEAR"
        raise ValueError(f"无法映射的 K线周期值 {key}，/bars 仅支持 {valid}")
    return mapping[key]


def adjust_from_str(s: str) -> Any:
    """将字符串转为 Adjust 枚举（NONE/QFQ/HFQ），支持大小写和数字字符串。

    >>> adjust_from_str("QFQ")   # 前复权
    >>> adjust_from_str("qfq")   # 也正常（自动转大写）
    >>> adjust_from_str("1")     # 数字字符串也行（= QFQ）
    >>> adjust_from_str("XXX")   # ValueError
    """
    from easy_tdx.mac.enums import Adjust

    key = s.upper()
    try:
        return Adjust[key]
    except KeyError:
        pass
    try:
        return Adjust(int(key))
    except (ValueError, TypeError):
        pass
    valid = ", ".join(a.name for a in Adjust)
    raise ValueError(f"无效复权类型 '{s}'，可选值: {valid}") from None


def category_mac_from_str(s: str) -> Any:
    """将字符串转为 MAC Category 枚举（A/SH/SZ/KCB/BJ/CYB/...）。"""
    from easy_tdx.mac.enums import Category

    key = s.upper()
    try:
        return Category[key]
    except KeyError:
        pass
    try:
        return Category(int(key))
    except (ValueError, TypeError):
        pass
    valid = ", ".join(m.name for m in Category if m < 10000)
    raise ValueError(f"无效市场分类 '{s}'，可选值: {valid}") from None


def ex_market_from_str(s: str) -> int:
    """将字符串转为 ExMarket 整数值（HK_MAIN_BOARD/COMEX_FUTURES/... 或数字）。"""
    from easy_tdx.mac.enums import ExMarket

    try:
        return int(ExMarket[s.upper()])
    except KeyError:
        pass
    try:
        return int(s)
    except (ValueError, TypeError):
        pass
    valid = ", ".join(m.name for m in ExMarket)
    raise ValueError(f"无效扩展市场代码 '{s}'，可选值: {valid}") from None


def filter_types_from_str(s: str) -> list[Any]:
    """将逗号分隔字符串转为 FilterType 列表（ST,KC,BJ,...）。"""
    from easy_tdx.mac.enums import FilterType

    if not s:
        return []
    result: list[Any] = []
    for part in s.split(","):
        key = part.strip().upper()
        try:
            result.append(FilterType[key])
        except KeyError:
            try:
                result.append(FilterType(int(key)))
            except (ValueError, TypeError):
                valid = ", ".join(m.name for m in FilterType)
                raise ValueError(f"无效过滤标志 '{part}'，可选值: {valid}") from None
    return result
