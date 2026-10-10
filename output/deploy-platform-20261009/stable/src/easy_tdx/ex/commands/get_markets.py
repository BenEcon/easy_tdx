"""获取扩展行情市场列表。"""

import struct

from ..._binary import unpack_from
from ...commands.base import BaseCommand
from ..models import ExMarketInfo


class GetExMarketsCmd(BaseCommand[list[ExMarketInfo]]):
    """获取扩展行情支持的市场列表。"""

    def build_request(self) -> bytes:
        return bytes.fromhex("01 02 48 69 00 01 02 00 02 00 f4 23")

    def parse_response(self, body: bytes) -> list[ExMarketInfo]:
        if len(body) < 2:
            return []
        (count,) = unpack_from("<H", body, 0, "ex markets count")
        pos = 2
        results: list[ExMarketInfo] = []
        for _ in range(count):
            if pos + 64 > len(body):
                break
            raw = body[pos : pos + 64]
            (category, raw_name, market, raw_short_name) = struct.unpack("<B32sB2s", raw[:36])
            pos += 64
            if category == 0 and market == 0:
                continue
            name = raw_name.decode("gbk", errors="replace").rstrip("\x00")
            short_name = raw_short_name.decode("gbk", errors="replace").rstrip("\x00")
            results.append(
                ExMarketInfo(
                    market=market,
                    category=category,
                    name=name,
                    short_name=short_name,
                    _raw=raw,
                )
            )
        return results
