"""获取 K 线数据命令（支持全部周期）。"""

import logging
import struct

from .._binary import unpack_from
from ..codec.datetime_ import get_datetime
from ..codec.price import get_price
from ..codec.volume import get_volume
from ..exceptions import TdxDecodeError
from ..models.bar import SecurityBar
from ..models.enums import KlineCategory, Market
from .base import BaseCommand

_log = logging.getLogger(__name__)


class GetSecurityBarsCmd(BaseCommand[list[SecurityBar]]):
    """获取指定股票的 K 线数据。

    Args:
        market:   市场（SH/SZ）
        code:     6位股票代码（字符串）
        category: K线周期
        start:    起始行（0 = 最新；分页时递增）
        count:    返回条数（最多 800）
    """

    def __init__(
        self,
        market: Market,
        code: str,
        category: KlineCategory,
        start: int,
        count: int = 800,
    ) -> None:
        self.market = market
        self.code = code.encode("utf-8")
        self.category = category
        self.start = start
        self.count = count

    def build_request(self) -> bytes:
        # Header (12 bytes) + Payload (28 bytes) = 40 bytes
        return struct.pack(
            "<HIHHHH6sHHHHIIH",
            0x010C,
            0x01016408,
            0x001C,
            0x001C,
            0x052D,
            int(self.market),
            self.code,
            int(self.category),
            1,
            self.start,
            self.count,
            0,
            0,
            0,
        )

    def parse_response(self, body: bytes) -> list[SecurityBar]:
        (ret_count,) = unpack_from("<H", body, 0, "security_bars header")
        pos = 2
        bars: list[SecurityBar] = []
        pre_diff_base = 0
        cat = int(self.category)

        for i in range(ret_count):
            record_start = pos
            try:
                year, month, day, hour, minute, pos = get_datetime(cat, body, pos)

                open_diff, pos = get_price(body, pos)
                close_diff, pos = get_price(body, pos)
                high_diff, pos = get_price(body, pos)
                low_diff, pos = get_price(body, pos)

                vol, pos = get_volume(body, pos)
                amount, pos = get_volume(body, pos)
            except TdxDecodeError as e:
                # TDX 服务端偶发截断或空响应：响应头声称有 N 条，但 body
                # 末尾若干条被切掉，甚至整条 body 除了 ret_count 头外为空。
                # 两种情况都丢弃残缺部分，返回已成功解析的前若干条，避免
                # 一条坏数据让整页 500。
                # 注意：即使 bars 为空（第 1 条就崩）也 return 而非 raise ——
                # 服务器返回 0 条数据但 ret_count 撒谎是已知现象，返回空列表
                # 让调用方分页重试比直接 500 更友好。
                if i == 0 and not bars:
                    # 第 1 条即崩且无任何已解析记录：典型"服务器空响应"
                    # （ret_count 撒谎）。用更明确的措辞，便于上层故障转移逻辑
                    # 与人工排查识别"这是该服务器没数据，该换台"。
                    _log.warning(
                        "K线响应为空（声称 %d 条但首条即解析失败：%s），"
                        "该服务器可能未提供此标的，返回空列表",
                        ret_count,
                        e,
                    )
                else:
                    _log.warning(
                        "K线响应在第 %d/%d 条处被截断（%s），已丢弃末尾残缺记录，返回前 %d 条",
                        i + 1,
                        ret_count,
                        e,
                        len(bars),
                    )
                return bars

            # 差分还原（与 pytdx 完全一致）
            open_abs = open_diff + pre_diff_base
            close_abs = open_abs + close_diff
            high_abs = open_abs + high_diff
            low_abs = open_abs + low_diff
            pre_diff_base = open_abs + close_diff

            bars.append(
                SecurityBar(
                    open=open_abs / 1000.0,
                    close=close_abs / 1000.0,
                    high=high_abs / 1000.0,
                    low=low_abs / 1000.0,
                    vol=vol,
                    amount=amount,
                    year=year,
                    month=month,
                    day=day,
                    hour=hour,
                    minute=minute,
                    _raw=body[record_start:pos],
                )
            )

        return bars


class GetIndexBarsCmd(GetSecurityBarsCmd):
    """获取指数 K 线。

    请求格式与股票 K 线相同，但响应每条记录在 vol+amt 后多 4 字节
    （上涨家数 uint16 + 下跌家数 uint16），必须跳过否则后续记录错位。
    """

    def parse_response(self, body: bytes) -> list[SecurityBar]:
        (ret_count,) = unpack_from("<H", body, 0, "security_bars header")
        pos = 2
        bars: list[SecurityBar] = []
        pre_diff_base = 0
        cat = int(self.category)

        for i in range(ret_count):
            record_start = pos
            try:
                year, month, day, hour, minute, pos = get_datetime(cat, body, pos)

                open_diff, pos = get_price(body, pos)
                close_diff, pos = get_price(body, pos)
                high_diff, pos = get_price(body, pos)
                low_diff, pos = get_price(body, pos)

                vol, pos = get_volume(body, pos)
                amount, pos = get_volume(body, pos)

                # 指数记录额外 4 字节：上涨家数 + 下跌家数（各 uint16 LE）
                pos += 4
            except TdxDecodeError as e:
                if i == 0 and not bars:
                    _log.warning(
                        "指数K线响应为空（声称 %d 条但首条即解析失败：%s），"
                        "该服务器可能未提供此指数，返回空列表",
                        ret_count,
                        e,
                    )
                else:
                    _log.warning(
                        "指数K线响应在第 %d/%d 条处被截断（%s），已丢弃末尾残缺记录，返回前 %d 条",
                        i + 1,
                        ret_count,
                        e,
                        len(bars),
                    )
                return bars

            # 差分还原（与 pytdx 完全一致）
            open_abs = open_diff + pre_diff_base
            close_abs = open_abs + close_diff
            high_abs = open_abs + high_diff
            low_abs = open_abs + low_diff
            pre_diff_base = open_abs + close_diff

            bars.append(
                SecurityBar(
                    open=open_abs / 1000.0,
                    close=close_abs / 1000.0,
                    high=high_abs / 1000.0,
                    low=low_abs / 1000.0,
                    vol=vol,
                    amount=amount,
                    year=year,
                    month=month,
                    day=day,
                    hour=hour,
                    minute=minute,
                    _raw=body[record_start:pos],
                )
            )

        return bars
