"""MAC K 线数据命令（0x122E）。

获取单只股票的 K 线数据（支持复权）。
"""

import struct
from datetime import datetime

from ..._binary import unpack_from
from ...codec.mac_frame import build_mac_request
from ...commands.base import BaseCommand
from ..enums import Adjust, Period
from ..models import MacBar

_MSG_ID = 0x122E


def _combine_datetime(ymd: int, time_num: int, is_intraday: bool) -> datetime:
    """将日期和可选时间组合为 datetime。

    日线及以上周期 time_num 为 0，分时周期 time_num 含 HHMM 信息。
    """
    year = ymd // 10000
    month = (ymd % 10000) // 100
    day = ymd % 100
    if is_intraday and time_num:
        hour = time_num // 3600
        minute = (time_num % 3600) // 60
        return datetime(year, month, day, hour, minute)
    return datetime(year, month, day)


class SymbolBarCmd(BaseCommand[list[MacBar]]):
    """获取单只股票的 K 线数据。

    Args:
        market: 市场代码。
        code:   6 位股票代码。
        period: K 线周期。
        times:  周期倍数（Period.MINS / Period.DAYS 时有效）。
        start:  起始偏移（0 = 最新）。
        count:  返回条数。
        fq:     复权方式。
    """

    def __init__(
        self,
        market: int,
        code: str,
        period: Period = Period.DAILY,
        times: int = 1,
        start: int = 0,
        count: int = 700,
        fq: Adjust = Adjust.NONE,
    ) -> None:
        self._market = market
        self._code = code
        self._period = period
        self._times = times
        self._start = start
        self._count = count
        self._fq = fq

    def build_request(self) -> bytes:
        body = struct.pack(
            "<H22sHH I HH bbb bH4s",
            self._market,
            self._code.encode("gbk"),
            self._period,
            self._times,
            self._start,
            self._count,
            self._fq,
            1,
            1,
            0,
            1,
            0,
            b"",
        )
        return build_mac_request(_MSG_ID, body)

    def parse_response(self, body: bytes) -> list[MacBar]:
        # 头部: market(2) + code(22) + category(2) + flag(1) + count(2) + start(4) = 33
        (category_flag, _flag, count, start) = unpack_from("<HBHI", body, 24, "symbol_bar header")

        # 防止 count 异常导致越界读取
        count = min(count, (len(body) - 33) // 36)
        if count < 0:
            count = 0

        is_intraday = (
            self._period < Period.DAILY
            or self._period == Period.MIN_1
            or self._period == Period.MINS
        )

        results: list[MacBar] = []
        for i in range(count):
            offset = 33 + i * 36
            if offset + 36 > len(body):
                break
            (ymd, time_num, open_, high, low, close, amount, vol, float_shares) = unpack_from(
                "<II7f", body, offset, f"symbol_bar bar[{i}]"
            )
            if ymd < 19900101 or ymd > 20991231:
                continue
            dt = _combine_datetime(ymd, time_num, is_intraday)
            results.append(
                MacBar(
                    datetime=dt,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    vol=vol,
                    amount=amount,
                    float_shares=float_shares,
                )
            )

        return results
