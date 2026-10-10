"""Index acquisition shared by future benchmark-dependent factor requests.

Calls the existing index service in process; no HTTP request or user-query audit
is generated for this auxiliary input. A pool caller should acquire once and
attach the same frozen benchmark independently to each equity frame.
"""

from typing import Any, Literal, cast

import pandas as pd

from easy_tdx.factor.benchmark import BENCHMARKS, validate_index
from easy_tdx.web.market_data import closed_frame
from easy_tdx.web.routers.bars import research_bars

BenchmarkCategory = Literal[
    "DAY", "WEEK", "MONTH", "MIN_1", "MIN_5", "MIN_15", "MIN_30", "MIN_60"
]
_CATEGORIES = {"DAY", "WEEK", "MONTH", "MIN_1", "MIN_5", "MIN_15", "MIN_30", "MIN_60"}


async def load_factor_benchmark(
    symbol: str, category: str, count: int, client: Any, mac_client: Any | None
) -> pd.DataFrame:
    if symbol not in BENCHMARKS or category not in _CATEGORIES:
        raise ValueError("基准指数或周期不受支持，未自动替换")
    if type(count) is not int or not 1 <= count <= 800:
        raise ValueError("基准历史长度必须为 1–800，未截断")
    market, code = symbol.split(":")
    snapshot = await research_bars(
        kind="index",
        code=code,
        market=cast(Literal["SH", "SZ"], market),
        category=cast(BenchmarkCategory, category),
        count=count,
        client=client,
        mac_client=mac_client,
    )
    frame = pd.DataFrame(snapshot["data"])
    frame.attrs["snapshot_metadata"] = snapshot["metadata"]
    received_count = len(frame)
    frame = closed_frame(frame)
    frame.attrs["snapshot_metadata"] = {
        **frame.attrs["snapshot_metadata"],
        "excluded_open_count": received_count - len(frame),
        "input_count": len(frame),
    }
    validate_index(frame, symbol)
    if len(frame) > count:
        raise ValueError("指数服务返回行数超出请求，未静默截断")
    return frame
