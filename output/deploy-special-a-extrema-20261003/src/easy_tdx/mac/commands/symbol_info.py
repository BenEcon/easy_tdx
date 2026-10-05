"""MAC 个股简要特征命令（0x122A）。

获取单只股票的实时快照信息。
"""

import struct
from datetime import datetime

from ..._binary import unpack_from
from ...codec.mac_frame import build_mac_request
from ...commands.base import BaseCommand
from ..models import MacSymbolInfo

_MSG_ID = 0x122A


class SymbolInfoCmd(BaseCommand[MacSymbolInfo]):
    """获取个股简要特征。

    Args:
        market: 市场代码。
        code:   6 位股票代码。
    """

    def __init__(self, market: int, code: str) -> None:
        self._market = market
        self._code = code

    def build_request(self) -> bytes:
        body = struct.pack("<H22sI12x", self._market, self._code.encode("gbk"), 1)
        return build_mac_request(_MSG_ID, body)

    def parse_response(self, body: bytes) -> MacSymbolInfo:
        # data[0:8]  padding (zeros)
        # data[8:74] market(2) + code(22) + name(44)
        (market, code_raw, name_raw) = unpack_from("<H22s44s", body, 8, "symbol_info identity")

        # data[76:96] padding (zeros)
        # data[96:..] core fields
        (
            date_raw,
            time_raw,
            activity,
            pre_close,
            open,
            high,
            low,
            close,
            momentum,
            vol,
            amount,
            inside_volume,
            outside_volume,
        ) = unpack_from("<III5ffIfII", body, 96, "symbol_info core")

        # data[148:..]
        (_decimal, _a, _b, _c, _vr, turnover, avg) = unpack_from(
            "<HIf20xI3f", body, 148, "symbol_info extra"
        )

        dt = datetime(
            date_raw // 10000,
            (date_raw % 10000) // 100,
            date_raw % 100,
            time_raw // 10000,
            (time_raw % 10000) // 100,
            time_raw % 100,
        )

        return MacSymbolInfo(
            market=market,
            code=code_raw.decode("gbk", errors="ignore").replace("\x00", ""),
            name=name_raw.decode("gbk", errors="ignore").replace("\x00", ""),
            time=dt,
            activity=activity,
            pre_close=pre_close,
            open=open,
            high=high,
            low=low,
            close=close,
            momentum=momentum,
            vol=int(vol),
            amount=amount,
            inside_volume=inside_volume,
            outside_volume=outside_volume,
            turnover=turnover,
            avg=avg,
        )
