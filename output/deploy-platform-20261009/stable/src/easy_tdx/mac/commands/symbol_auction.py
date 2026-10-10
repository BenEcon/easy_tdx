"""集合竞价数据查询（0x123D）。"""

import struct
from datetime import time

from ..._binary import unpack_from
from ...codec.mac_frame import build_mac_request
from ...commands.base import BaseCommand
from ..models import AuctionItem


class SymbolAuctionCmd(BaseCommand[list[AuctionItem]]):
    """查询集合竞价数据。

    Parameters
    ----------
    market : int
        市场代码。
    code : str
        证券代码。
    start : int
        起始偏移量。
    count : int
        请求数量。
    """

    def __init__(self, market: int, code: str, start: int = 0, count: int = 500) -> None:
        self._market = market
        self._code = code
        self._start = start
        self._count = count

    def build_request(self) -> bytes:
        # H: market, 22s: code in GBK, I: start, I: count, 10 bytes padding
        body = struct.pack(
            "<H22sII10x",
            self._market,
            self._code.encode("gbk"),
            self._start,
            self._count,
        )
        return build_mac_request(0x123D, body)

    def parse_response(self, body: bytes) -> list[AuctionItem]:
        # 响应头: H:market, 22s:code, I:count, 8 bytes padding (zeros)
        _market, _code, count = unpack_from("<H22sI", body, 0, "auction header")

        items: list[AuctionItem] = []
        for i in range(count):
            offset = 36 + i * 16
            if offset + 16 > len(body):
                break
            time_sec, price, matched, unmatched = unpack_from(
                "<IfIi", body, offset, f"auction item[{i}]"
            )

            items.append(
                AuctionItem(
                    time=time(time_sec // 3600, (time_sec % 3600) // 60, time_sec % 60),
                    price=price,
                    matched=matched,
                    unmatched=unmatched,
                )
            )

        return items
