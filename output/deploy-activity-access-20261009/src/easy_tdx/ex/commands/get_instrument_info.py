"""获取扩展行情商品信息。"""

import struct

from ...commands.base import BaseCommand
from ..models import ExInstrumentInfo


class GetExInstrumentInfoCmd(BaseCommand[list[ExInstrumentInfo]]):
    """获取扩展行情市场中的商品信息列表。"""

    def __init__(self, start: int, count: int = 100) -> None:
        self.start = start
        self.count = count

    def build_request(self) -> bytes:
        header = bytes.fromhex("01 04 48 67 00 01 08 00 08 00 f5 23")
        return header + struct.pack("<IH", self.start, self.count)

    def parse_response(self, body: bytes) -> list[ExInstrumentInfo]:
        if len(body) < 6:
            return []
        pos = 0
        (_start, _count) = struct.unpack("<IH", body[pos : pos + 6])
        count = _count
        pos += 6
        results: list[ExInstrumentInfo] = []
        for _ in range(count):
            if pos + 64 > len(body):
                break
            raw = body[pos : pos + 64]
            (category, market, _unused, raw_code, raw_name, raw_desc) = struct.unpack(
                "<BB3s9s17s9s",
                raw[:40],
            )
            pos += 64
            code = raw_code.decode("gbk", errors="replace").rstrip("\x00")
            name = raw_name.decode("gbk", errors="replace").rstrip("\x00")
            desc = raw_desc.decode("gbk", errors="replace").rstrip("\x00")
            results.append(
                ExInstrumentInfo(
                    category=category,
                    market=market,
                    code=code,
                    name=name,
                    desc=desc,
                    _raw=raw,
                )
            )
        return results
