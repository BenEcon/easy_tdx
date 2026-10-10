"""K线偏移查询（0x124A）。"""

import struct

from ...codec.mac_frame import build_mac_request
from ...commands.base import BaseCommand
from ..models import KlineOffsetInfo


class KlineOffsetCmd(BaseCommand[KlineOffsetInfo]):
    """查询K线数据偏移。

    Parameters
    ----------
    offset : int
        偏移量（必须为 0）。
    count : int
        请求数量。
    """

    def __init__(self, offset: int = 0, count: int = 128000) -> None:
        self._offset = offset
        self._count = count

    def build_request(self) -> bytes:
        # I:offset, I:count, 5 bytes padding
        body = struct.pack("<II5x", self._offset, self._count)
        return build_mac_request(0x124A, body)

    def parse_response(self, body: bytes) -> KlineOffsetInfo:
        if len(body) < 8:
            return KlineOffsetInfo(total=0, returned=0)

        # total 字段为大端序!
        total = struct.unpack(">I", body[:4])[0]
        returned = struct.unpack("<I", body[4:8])[0]

        return KlineOffsetInfo(total=total, returned=returned)
