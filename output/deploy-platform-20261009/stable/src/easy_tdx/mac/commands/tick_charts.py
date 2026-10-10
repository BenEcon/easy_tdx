"""MAC 多日分时图命令（0x123E）。

获取单只股票多日的分时数据。
"""

import struct
from datetime import date, time

from ..._binary import unpack_from
from ...codec.mac_frame import build_mac_request
from ...commands.base import BaseCommand
from ..models import MacMultiTickChart, MacMultiTickDay, MacTick

_MSG_ID = 0x123E
_TICK_OFFSET = 71
_TICK_SIZE = struct.calcsize("<HffHH")
_TAIL_FMT = "<44sBHf5x2I5ffIf12s2fI"
_TAIL_SIZE = struct.calcsize(_TAIL_FMT)


class TickChartsCmd(BaseCommand[MacMultiTickChart]):
    """获取多日分时图。

    Args:
        market:     市场代码。
        code:       6 位股票代码。
        start_date: 起始日期（None 表示从最新交易日开始）。
        days:       天数（最多 5）。
    """

    def __init__(
        self,
        market: int,
        code: str,
        start_date: date | None = None,
        days: int = 5,
    ) -> None:
        self._market = market
        self._code = code
        if start_date is not None:
            self._start_ymd = start_date.year * 10000 + start_date.month * 100 + start_date.day
        else:
            self._start_ymd = 0
        self._days = days

    def build_request(self) -> bytes:
        body = struct.pack(
            "<H22sIHH6x",
            self._market,
            self._code.encode("gbk"),
            self._start_ymd,
            self._days,
            1,
        )
        return build_mac_request(_MSG_ID, body)

    def parse_response(self, body: bytes) -> MacMultiTickChart:
        # 头部
        (market, code_raw) = unpack_from("<H22s", body, 0, "tick_charts header")

        # 每日日期(5 x I) + 每日前收(5 x f) = 40 bytes
        date_ints = unpack_from("<5I", body, 24, "tick_charts dates")
        pre_close_floats = unpack_from("<5f", body, 44, "tick_charts pre_closes")

        # count(2) + send_last(1) + page_size(2) + total(2)
        (count, send_last, page_size, total) = unpack_from("<HBHH", body, 64, "tick_charts header2")

        max_ticks = max(0, (len(body) - _TICK_OFFSET - _TAIL_SIZE) // _TICK_SIZE)
        actual_total = min(total, max_ticks)
        if actual_total >= count * page_size:
            tick_counts = [page_size] * count
        else:
            # start_date=None returns the latest partial trading day first,
            # followed by complete historical days.
            complete_days = min(count - 1, actual_total // page_size)
            first_day_count = actual_total - complete_days * page_size
            empty_days = count - complete_days - 1
            tick_counts = [first_day_count] + [page_size] * complete_days + [0] * empty_days

        days: list[MacMultiTickDay] = []
        tick_index = 0
        for d, tick_count in enumerate(tick_counts):
            ticks: list[MacTick] = []
            for t in range(tick_count):
                offset = _TICK_OFFSET + tick_index * _TICK_SIZE
                (minutes, price, avg, vol, tick_reserved) = unpack_from(
                    "<HffHH", body, offset, f"tick_charts tick[{d}][{t}]"
                )
                tick_index += 1
                ticks.append(
                    MacTick(
                        # 多日分时里 minutes 在个别服务器/数据状态下可能 ≥ 1440
                        # （累计或异常值），对 24 取模折算成日内时刻，避免 ValueError。
                        # 与单日分时 SymbolTickChartCmd 的处理保持一致（Issue #10）。
                        time=time(minutes // 60 % 24, minutes % 60),
                        price=price,
                        avg=avg,
                        vol=vol,
                    )
                )

            ymd = date_ints[d]
            day_date = date(ymd // 10000, (ymd % 10000) // 100, ymd % 100)
            days.append(
                MacMultiTickDay(
                    date=day_date,
                    pre_close=pre_close_floats[d],
                    ticks=ticks,
                )
            )

        # 尾部元数据
        tail_offset = _TICK_OFFSET + actual_total * _TICK_SIZE
        (
            name_raw,
            _decimal,
            _category,
            _vol_unit,
            _date_raw,
            _time_raw,
            pre_close,
            open,
            high,
            low,
            close,
            _momentum,
            vol,
            amount,
            _tail_pad2,
            turnover,
            avg,
            _industry,
        ) = unpack_from(_TAIL_FMT, body, tail_offset, "tick_charts tail")

        return MacMultiTickChart(
            market=market,
            code=code_raw.decode("gbk", errors="ignore").replace("\x00", ""),
            name=name_raw.decode("gbk", errors="ignore").replace("\x00", ""),
            pre_close=pre_close,
            open=open,
            high=high,
            low=low,
            close=close,
            vol=int(vol),
            amount=amount,
            turnover=turnover,
            avg=avg,
            charts=days,
        )
