"""响应帧头解析与 zlib 解压。

响应帧格式（16 字节固定头 + body），字节级结构（gotdx 交叉验证）：
  偏移  0: I (4字节) — magic = 7654321 (0x0074CBB1)，协议标识
  偏移  4: B (1字节) — ZipFlag：bit4=1 表示 body 已压缩，0x0C=未压缩, 0x1C=已压缩
  偏移  5: I (4字节) — SeqID：请求 bytes 1-4 的回显（命令标识）
  偏移  9: B (1字节) — 保留（观察到恒为 0x00）
  偏移 10: H (2字节) — Method：请求 bytes 10-11 的回显
  偏移 12: H (2字节) — zipsize（body 实际长度）
  偏移 14: H (2字节) — unzipsize（解压后长度；等于 zipsize 表示未压缩）

兼容说明：使用 IIIHH 解码可正确提取 zipsize/unzipsize。前三个 uint32 中：
  u0 = magic, u1 = ZipFlag(1B) + SeqID(3B 低字节), u2 = SeqID(1B 高字节) + 保留(1B) + Method(2B)
"""

import zlib
from dataclasses import dataclass

from .._binary import unpack_from
from ..exceptions import TdxDecodeError

HEADER_SIZE: int = 16
_HEADER_FMT = "<IIIHH"


@dataclass(frozen=True)
class FrameHeader:
    magic: int  # 协议魔数，恒为 7654321
    seq_id: int  # ZipFlag(1B) + 请求 bytes 1-4 回显(3B)
    method: int  # 请求回显(1B) + 保留(1B) + Method(2B)
    zipsize: int
    unzipsize: int


def parse_header(buf: bytes) -> FrameHeader:
    """解析 16 字节响应帧头。"""
    magic, seq_id, method, zipsize, unzipsize = unpack_from(
        _HEADER_FMT,
        buf,
        0,
        "frame header",
    )
    return FrameHeader(magic, seq_id, method, zipsize, unzipsize)


def decompress_body(header: FrameHeader, raw_body: bytes) -> bytes:
    """按需 zlib 解压 body。

    zipsize == unzipsize 时直接返回原始字节；否则 zlib 解压。
    """
    if len(raw_body) != header.zipsize:
        raise TdxDecodeError(
            f"frame body 长度不符: header={header.zipsize}, actual={len(raw_body)}"
        )
    if header.zipsize == header.unzipsize:
        body = raw_body
    else:
        try:
            body = zlib.decompress(raw_body)
        except zlib.error as e:
            raise TdxDecodeError(f"frame body zlib 解压失败: {e}") from e

    if len(body) != header.unzipsize:
        raise TdxDecodeError(
            f"frame body 解压长度不符: header={header.unzipsize}, actual={len(body)}"
        )
    return body
