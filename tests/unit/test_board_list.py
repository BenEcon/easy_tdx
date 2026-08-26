"""板块列表（0x1231）排序键语义测试（Issue #53）。

背景实测（2026-08-26）：响应中 price 与 pre_close 之间的值槽是
"当前排序列的值"，板块与领涨股各一份；sort_column=0（涨跌幅）时
值槽恒 0，此前被误标为固定"涨速"且硬编码 0，导致整列恒 0。
"""

import struct
from unittest.mock import patch

import pytest

from easy_tdx.mac.client import MacClient
from easy_tdx.mac.commands.board_list import _RECORD_SIZE, BoardListCmd
from easy_tdx.mac.enums import BoardSortColumn, BoardType
from easy_tdx.mac.models import BoardInfo

# <HHBBHH8x> body: page_size(H), board_type(H), sort_col(B), order(B), start(H), flag(H)
# 帧 = 10 字节头 + 2 字节 msg_id + body → sort_col 位于 body[4] = 帧偏移 16。
_SORT_COL_POS = 10 + 2 + 4


class TestBoardListRequest:
    def test_sort_column_packed_into_request(self):
        """sort_column 应写入请求第 3 个 body 字节（帧内偏移 15）。"""
        req_default = BoardListCmd(BoardType.ALL, 0, 10).build_request()
        assert req_default[_SORT_COL_POS] == int(BoardSortColumn.CHANGE_PCT)

        req_speed = BoardListCmd(BoardType.ALL, 0, 10, BoardSortColumn.SPEED).build_request()
        assert req_speed[_SORT_COL_POS] == int(BoardSortColumn.SPEED) == 1

        req_ytd = BoardListCmd(BoardType.ALL, 0, 10, BoardSortColumn.YTD).build_request()
        assert req_ytd[_SORT_COL_POS] == int(BoardSortColumn.YTD) == 5

        # 只差 sort_col 一个字节，其余请求布局不变
        assert len(req_default) == len(req_speed) == len(req_ytd)

    def test_sort_column_enum_values(self):
        """实测锚定的排序列映射。"""
        assert [c.value for c in BoardSortColumn] == [0, 1, 2, 3, 4, 5, 6, 7]


def _build_body(board_mid: float, symbol_mid: float) -> bytes:
    """构造一条"板块 + 领涨股"记录的响应 body。"""
    board_half = struct.pack(
        "<H6s16s44sfff",
        1,
        b"881247",
        b"",
        "医疗服务".encode("gbk"),
        645.06,  # price
        board_mid,  # sort_value（涨速等，语义随排序列）
        653.76,  # pre_close
    )
    symbol_half = struct.pack(
        "<H6s16s44sfff",
        0,
        b"301235",
        b"",
        "领涨股".encode("gbk"),
        12.34,
        symbol_mid,
        11.11,
    )
    return struct.pack("<HH", 2, 128) + board_half + symbol_half


class TestBoardListParse:
    def test_parse_populates_sort_value(self):
        cmd = BoardListCmd(BoardType.ALL, 0, 1, BoardSortColumn.SPEED)
        rows = cmd.parse_response(_build_body(0.0791, 0.1587))
        assert len(rows) == 1
        r = rows[0]
        assert isinstance(r, BoardInfo)
        assert r.code == "881247"
        assert r.name == "医疗服务"
        assert r.price == pytest.approx(645.06)
        assert r.pre_close == pytest.approx(653.76)
        assert r.sort_value == pytest.approx(0.0791)
        assert r.symbol_sort_value == pytest.approx(0.1587)
        assert r.symbol_code == "301235"

    def test_model_has_no_legacy_rise_speed_field(self):
        """旧字段名已移除（语义错误：值槽并非恒为涨速）。"""
        assert not hasattr(
            BoardInfo(
                market=1,
                code="1",
                name="n",
                price=0.0,
                sort_value=0.0,
                pre_close=0.0,
                symbol_market=1,
                symbol_code="2",
                symbol_name="s",
                symbol_price=0.0,
                symbol_sort_value=0.0,
                symbol_pre_close=0.0,
            ),
            "rise_speed",
        )


class TestGetBoardListPassThrough:
    def test_client_forwards_sort_column(self):
        """get_board_list 应把 sort_column 透传给 BoardListCmd。"""
        client = MacClient.__new__(MacClient)
        seen: list[BoardListCmd] = []

        def fake_execute(cmd):
            seen.append(cmd)
            return []

        with patch.object(client, "_execute", side_effect=fake_execute):
            df = client.get_board_list(BoardType.ALL, 10, BoardSortColumn.SPEED)

        assert df.empty
        assert seen and seen[0]._sort_column == BoardSortColumn.SPEED

    def test_web_converter(self):
        from easy_tdx.web.convert import board_sort_from_str

        assert board_sort_from_str("speed") == BoardSortColumn.SPEED
        assert board_sort_from_str("CHANGE_3D") == BoardSortColumn.CHANGE_3D
        with pytest.raises(ValueError, match="无效板块排序键"):
            board_sort_from_str("NOPE")

    def test_record_size_unchanged(self):
        """响应记录仍为 160 字节（板块 + 领涨股各 80）。"""
        assert _RECORD_SIZE == 160


class TestAsyncPassThrough:
    def test_async_client_forwards_sort_column(self):
        from easy_tdx.mac.client import AsyncMacClient

        client = AsyncMacClient.__new__(AsyncMacClient)
        seen: list[BoardListCmd] = []

        async def fake_execute(cmd):
            seen.append(cmd)
            return []

        with patch.object(client, "_execute", side_effect=fake_execute):
            import asyncio

            df = asyncio.run(client.get_board_list(BoardType.ALL, 10, BoardSortColumn.SPEED))

        assert df.empty
        assert seen and seen[0]._sort_column == BoardSortColumn.SPEED


class TestWebEndpoint:
    def test_board_list_endpoint_accepts_sort_column(self):
        """Web /board-mac/list 端点应接受 sort_column 参数并透传。"""
        pytest.importorskip("fastapi")
        import pandas as pd
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from easy_tdx.web.routers import board_mac

        app = FastAPI()
        app.include_router(board_mac.router, prefix="/api/v1")

        captured: dict = {}

        class _FakeMacClient:
            async def get_board_list(self, **kwargs):
                captured.update(kwargs)
                return pd.DataFrame()

        app.state.mac_client = _FakeMacClient()
        app.state.tdx_client = object()

        with TestClient(app) as tc:
            resp = tc.get("/api/v1/board-mac/list", params={"sort_column": "SPEED", "count": 5})

        assert resp.status_code == 200
        assert captured["sort_column"] == BoardSortColumn.SPEED
