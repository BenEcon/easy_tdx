"""MAC 批量报价命令（0x122B）。

根据字段位图请求多只股票的自定义字段报价。
"""

from __future__ import annotations

import struct
from typing import Any

from ..._binary import unpack_from
from ...codec.bitmap import (
    FIELD_POSTPROCESS,
    Fields,
    build_bitmap,
    get_active_fields,
)
from ...codec.mac_frame import build_mac_request
from ...commands.base import BaseCommand
from ..models import MacQuoteField

_MSG_ID = 0x122B


class SymbolQuotesCmd(BaseCommand[list[MacQuoteField]]):
    """批量获取自定义字段报价。

    Args:
        stocks: [(market, code), ...] 列表。
        fields: 字段选择，默认 PresetField.COMMON。
    """

    def __init__(self, stocks: list[tuple[int, str]], fields: Fields | None = None) -> None:
        if not stocks:
            raise ValueError("stocks 不能为空")
        self._stocks = stocks
        # 默认不请求任何字段时使用 COMMON 需要导入 PresetField，
        # 这里延迟导入避免循环。
        if fields is None:
            from ...codec.bitmap import PresetField

            fields = PresetField.COMMON
        self._fields = fields
        self._bitmap = bytes(build_bitmap(fields))

    def build_request(self) -> bytes:
        body = bytearray(self._bitmap)
        body += struct.pack("<H", len(self._stocks))
        for market, code in self._stocks:
            body += struct.pack("<H22s", market, code.encode("gbk"))
        return build_mac_request(_MSG_ID, bytes(body))

    def parse_response(self, body: bytes) -> list[MacQuoteField]:
        pos = 0
        field_bitmap = body[pos : pos + 20]
        pos += 20

        (total_stocks, row_count) = unpack_from("<IH", body, pos, "symbol_quotes header")
        pos += 6

        active = get_active_fields(field_bitmap[:16])
        field_count = len(active)
        row_len = 68 + 4 * field_count

        results: list[MacQuoteField] = []
        for _ in range(row_count):
            row_end = pos + row_len
            if row_end > len(body):
                break
            row_data = body[pos:row_end]
            pos = row_end

            (market, code_raw, name_raw) = unpack_from("<H22s44s", row_data, 0, "symbol_quotes row")
            code = code_raw.decode("gbk", errors="ignore").replace("\x00", "")
            name = name_raw.decode("gbk", errors="ignore").replace("\x00", "")

            fields_dict: dict[str, Any] = {}
            if field_count:
                for idx, (field_bit, fmt) in enumerate(active):
                    value_bytes = row_data[68 + idx * 4 : 68 + (idx + 1) * 4]
                    (value,) = struct.unpack(fmt, value_bytes)

                    # 后处理钩子
                    post_fn = FIELD_POSTPROCESS.get(field_bit.value)
                    if post_fn is not None:
                        value = post_fn(value, market)  # type: ignore[operator]

                    fields_dict[field_bit.field_name] = value

            results.append(
                MacQuoteField(
                    market=market,
                    code=code,
                    name=name,
                    fields=fields_dict,
                )
            )

        return results
