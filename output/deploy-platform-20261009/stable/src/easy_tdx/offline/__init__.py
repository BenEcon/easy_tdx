"""离线数据读写模块 —— 从本地通达信安装目录读取/写入数据文件。"""

from .block import CustomerBlock, read_block_dat, read_customer_blocks
from .daily_bar import find_daily_bar_file, read_daily_bars
from .ex_daily_bar import ExDailyBar, read_ex_daily_bars
from .finders import find_5min_bar_file, find_lc1_bar_file, find_lc5_bar_file
from .gbbq import GbbqRecord, read_gbbq
from .history_financial import read_history_financial
from .min_bar import read_5min_bars, read_lc_min_bars
from .paths import detect_tdx_home, resolve_vipdoc
from .write_daily import (
    append_daily_bars,
    encode_daily_bar,
    get_last_bar_date,
    sync_daily_bars_from_security_bars,
)
from .write_ex_daily import (
    append_ex_daily_bars,
    encode_ex_daily_bar,
    get_last_ex_bar_date,
    sync_ex_daily_bars,
)
from .write_min_bar import (
    append_5min_bars,
    append_lc_min_bars,
    encode_5min_bar,
    encode_lc_min_bar,
    get_last_5min_bar_datetime,
    get_last_lc_min_bar_datetime,
)

__all__ = [
    # 路径
    "detect_tdx_home",
    "resolve_vipdoc",
    # 日线读取
    "read_daily_bars",
    "find_daily_bar_file",
    # 日线写入
    "encode_daily_bar",
    "append_daily_bars",
    "get_last_bar_date",
    "sync_daily_bars_from_security_bars",
    # 扩展市场日线写入
    "encode_ex_daily_bar",
    "append_ex_daily_bars",
    "get_last_ex_bar_date",
    "sync_ex_daily_bars",
    # 分钟线写入
    "encode_5min_bar",
    "encode_lc_min_bar",
    "append_5min_bars",
    "append_lc_min_bars",
    "get_last_5min_bar_datetime",
    "get_last_lc_min_bar_datetime",
    # 分钟线读取
    "read_5min_bars",
    "read_lc_min_bars",
    "find_5min_bar_file",
    "find_lc1_bar_file",
    "find_lc5_bar_file",
    # 扩展市场读取
    "ExDailyBar",
    "read_ex_daily_bars",
    # 板块
    "CustomerBlock",
    "read_block_dat",
    "read_customer_blocks",
    # 股本变迁
    "GbbqRecord",
    "read_gbbq",
    # 历史财务
    "read_history_financial",
]
