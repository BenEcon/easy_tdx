"""服务器交易时段查询（0x120F）。"""

from ..._binary import unpack_from
from ...codec.mac_frame import build_mac_request
from ...commands.base import BaseCommand
from ..models import ServerSession


class ServerInfoCmd(BaseCommand[ServerSession]):
    """查询服务器交易时段信息。"""

    def build_request(self) -> bytes:
        # 固定 68 字节请求体
        header = bytes.fromhex("04002d31")
        body = header + b"\x00" * 8 + b"\x00\x27\x06\x0e" + b"\x00" * 52
        return build_mac_request(0x120F, body)

    def parse_response(self, body: bytes) -> ServerSession:
        if len(body) < 87:
            return ServerSession(today="", last_trading_day="")

        pos = 0
        _count = unpack_from("<H", body, pos, "server_info count")[0]
        pos += 2
        # 8 bytes flags
        pos += 8
        # 3 bytes tag ("-1")
        pos += 3
        # 9 bytes reserved
        pos += 9

        def _parse_date(p: int) -> tuple[str, int]:
            d = unpack_from("<I", body, p, "server_info date")[0]
            return f"{d // 10000}-{d % 10000 // 100:02d}-{d % 100:02d}", p + 4

        def _parse_session(p: int) -> tuple[list[dict[str, object]], int]:
            vals = unpack_from("<8H", body, p, "server_info session")
            sessions: list[dict[str, object]] = []
            for i in range(0, 8, 2):
                sessions.append(
                    {
                        "open": f"{vals[i] // 60}:{vals[i] % 60:02d}",
                        "close": f"{vals[i + 1] // 60}:{vals[i + 1] % 60:02d}",
                    }
                )
            return sessions, p + 16

        today, pos = _parse_date(pos)
        pos += 4  # ts1

        sessions_1, pos = _parse_session(pos)
        sessions_2, pos = _parse_session(pos)

        pos += 1  # flag byte

        last_trading_day, pos = _parse_date(pos)
        pos += 4  # ts2

        # Skip remaining fields
        market_param_1 = 0
        market_param_2 = 0
        if pos + 8 <= len(body):
            market_param_1 = unpack_from("<I", body, pos, "server_info param1")[0]
            pos += 4
            market_param_2 = unpack_from("<I", body, pos, "server_info param2")[0]

        return ServerSession(
            today=today,
            last_trading_day=last_trading_day,
            sessions_1=sessions_1,
            sessions_2=sessions_2,
            market_param_1=market_param_1,
            market_param_2=market_param_2,
        )
