"""板块列表查询（0x1231）。"""

import struct

from ..._binary import unpack_from
from ...codec.mac_frame import build_mac_request
from ...commands.base import BaseCommand
from ..enums import BoardSortColumn, BoardType
from ..models import BoardInfo

# 板板信息 + 领涨股信息，每组 160 字节
# fmt: H(2) + 6s(6) + 16s(16) + 44s(44) + f(4) + f(4) + f(4) = 80
# x2 for board + symbol = 160
_RECORD_FMT = "<H6s16s44sfffH6s16s44sfff"
_RECORD_SIZE = struct.calcsize(_RECORD_FMT)  # 160


class BoardListCmd(BaseCommand[list[BoardInfo]]):
    """查询板块列表。

    Parameters
    ----------
    board_type : BoardType
        板块类型（行业、概念、风格等）。
    start : int
        起始偏移量。
    page_size : int
        每页数量。
    sort_column : BoardSortColumn
        排序键。响应中 price 与 pre_close 之间的值槽返回的就是该列的值
        （板块与领涨股各一份）；CHANGE_PCT(0) 仅作排序键，值槽恒 0
        （Issue #53：此前硬编码 0 且把值槽误标为"涨速"，导致永远全 0）。
    """

    def __init__(
        self,
        board_type: BoardType = BoardType.ALL,
        start: int = 0,
        page_size: int = 150,
        sort_column: BoardSortColumn = BoardSortColumn.CHANGE_PCT,
    ) -> None:
        self._board_type = board_type
        self._start = start
        self._page_size = page_size
        self._sort_column = sort_column

    def build_request(self) -> bytes:
        # <HHBBHH8x: page_size, board_type, sort_col, sort_order(0=降序), start, flag(1)
        body = struct.pack(
            "<HHBBHH8x",
            self._page_size,
            int(self._board_type),
            int(self._sort_column),
            0,  # sort_order
            self._start,
            1,  # flag
        )
        return build_mac_request(0x1231, body)

    def parse_response(self, body: bytes) -> list[BoardInfo]:
        count_all, total = unpack_from("<HH", body, 0, "board_list header")
        # 服务器返回 count_all = 2 * actual_count（board_info + symbol_info 各一份）
        count = count_all // 2

        results: list[BoardInfo] = []
        for i in range(count):
            offset = 4 + i * _RECORD_SIZE
            (
                market,
                code_raw,
                _pad1,
                name_raw,
                price,
                sort_value,
                pre_close,
                symbol_market,
                symbol_code_raw,
                _pad2,
                symbol_name_raw,
                symbol_price,
                symbol_sort_value,
                symbol_pre_close,
            ) = unpack_from(_RECORD_FMT, body, offset, f"board_list record[{i}]")

            results.append(
                BoardInfo(
                    market=market,
                    code=code_raw.decode("gbk", errors="replace").rstrip("\x00"),
                    name=name_raw.decode("gbk", errors="replace").rstrip("\x00"),
                    price=price,
                    sort_value=sort_value,
                    pre_close=pre_close,
                    symbol_market=symbol_market,
                    symbol_code=symbol_code_raw.decode("gbk", errors="replace").rstrip("\x00"),
                    symbol_name=symbol_name_raw.decode("gbk", errors="replace").rstrip("\x00"),
                    symbol_price=symbol_price,
                    symbol_sort_value=symbol_sort_value,
                    symbol_pre_close=symbol_pre_close,
                )
            )

        return results
