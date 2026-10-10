"""路径定位辅助函数。"""

from pathlib import Path

from .paths import _market_to_exchange, resolve_vipdoc


def find_5min_bar_file(
    market: int,
    code: str,
    vipdoc: str | Path | None = None,
) -> Path:
    """根据市场和代码定位 .5 分钟线文件路径。"""
    vipdoc_path = resolve_vipdoc(vipdoc)
    exchange = _market_to_exchange(market)
    return vipdoc_path / exchange / "fzline" / f"{exchange}{code}.5"


def find_lc1_bar_file(
    market: int,
    code: str,
    vipdoc: str | Path | None = None,
) -> Path:
    """根据市场和代码定位 .lc1 分钟线文件路径。"""
    vipdoc_path = resolve_vipdoc(vipdoc)
    exchange = _market_to_exchange(market)
    return vipdoc_path / exchange / "fzline" / f"{exchange}{code}.lc1"


def find_lc5_bar_file(
    market: int,
    code: str,
    vipdoc: str | Path | None = None,
) -> Path:
    """根据市场和代码定位 .lc5 分钟线文件路径。"""
    vipdoc_path = resolve_vipdoc(vipdoc)
    exchange = _market_to_exchange(market)
    return vipdoc_path / exchange / "fzline" / f"{exchange}{code}.lc5"
