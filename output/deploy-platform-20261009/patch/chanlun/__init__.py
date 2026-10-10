"""缠论（ChanLun）技术分析模块。

基于缠论理论实现 K 线合并、分型识别、笔/线段/中枢/买卖点/背驰计算。

核心 API::

    from easy_tdx.chanlun import ChanlunAnalyser, ChanlunConfig

    analyser = ChanlunAnalyser("SZ000001", "DAILY")
    result = analyser.process_klines(df)
    print(result.to_dict())
"""

from easy_tdx.chanlun.analyser import ChanlunAnalyser, ChanlunResult  # noqa: F401
from easy_tdx.chanlun.config import ChanlunConfig  # noqa: F401
from easy_tdx.chanlun.types import (  # noqa: F401
    BC,
    BI,
    FX,
    MMD,
    XD,
    ZS,
    BCType,
    CLKline,
    Direction,
    FXType,
    Kline,
    MMDType,
)

__all__ = [
    "ChanlunAnalyser",
    "ChanlunConfig",
    "ChanlunResult",
    "BC",
    "BCType",
    "BI",
    "CLKline",
    "Direction",
    "FX",
    "FXType",
    "Kline",
    "MMD",
    "MMDType",
    "XD",
    "ZS",
]
