"""获取扩展行情商品数量。"""

from ..._binary import unpack_from
from ...commands.base import BaseCommand


class GetExInstrumentCountCmd(BaseCommand[int]):
    """获取扩展行情市场中商品总数。"""

    def build_request(self) -> bytes:
        return bytes.fromhex("01 03 48 66 00 01 02 00 02 00 f0 23")

    def parse_response(self, body: bytes) -> int:
        if len(body) < 23:
            return 0
        (count,) = unpack_from("<I", body, 19, "ex instrument count")
        return int(count)
