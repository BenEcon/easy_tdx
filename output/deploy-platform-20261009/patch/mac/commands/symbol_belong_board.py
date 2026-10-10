"""个股所属板块查询（0x1218 head=1）。"""

import json
import struct

from ...codec.mac_frame import build_mac_request
from ...commands.base import BaseCommand
from ..models import BelongBoardInfo

# head=1 用于区分 symbol_belong_board 与 symbol_capital_flow (head=2)
_HEAD_FLAG = 1


def _to_float(value: object) -> float:
    """Safely convert JSON value to float."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return 0.0


def _to_int(value: object) -> int:
    """Safely convert JSON value to int."""
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return 0


class SymbolBelongBoardCmd(BaseCommand[list[BelongBoardInfo]]):
    """查询个股所属板块。

    Parameters
    ----------
    market : int
        市场代码。
    code : str
        证券代码。
    """

    def __init__(self, market: int, code: str) -> None:
        self._market = market
        self._code = code

    def build_request(self) -> bytes:
        # H:market, 8s:code padded with spaces, 16s:padding, 21s:"Stock_GLHQ"
        body = struct.pack(
            "<H8s16x21s",
            self._market,
            self._code.encode("gbk"),
            b"Stock_GLHQ",
        )
        return build_mac_request(0x1218, body, head_flag=_HEAD_FLAG)

    def parse_response(self, body: bytes) -> list[BelongBoardInfo]:
        # 响应头: H:market, 12s:query_info, 5x padding, 8s:ext = 27 bytes
        if len(body) < 27:
            return []

        json_bytes = body[27:]
        python_list: list[list[object]] = json.loads(json_bytes.decode("gbk", errors="replace"))

        results: list[BelongBoardInfo] = []
        if not python_list:
            return results

        for row in python_list:
            n = len(row)
            if n not in (9, 13):
                continue

            bt = _to_int(row[0])
            mkt = _to_int(row[1])
            board_code = str(row[2])
            board_name = str(row[3])
            close = _to_float(row[4]) if n > 4 and row[4] else 0.0
            pre_close = _to_float(row[5]) if n > 5 and row[5] else 0.0

            results.append(
                BelongBoardInfo(
                    board_type=bt,
                    market=mkt,
                    board_code=board_code,
                    board_name=board_name,
                    close=close,
                    pre_close=pre_close,
                )
            )

        return results
