"""MAC 协议请求帧构建。

MAC 协议请求帧格式（10 字节头 + body）：
  struct "<BIBHH"
  偏移 0: B (1字节) — head_flag (MAC=0x1c, 标准=0x0c)
  偏移 1: I (4字节) — customize（通常为 0）
  偏移 5: B (1字节) — version（通常为 1）
  偏移 6: H (2字节) — zipsize（body 长度）
  偏移 8: H (2字节) — unzipsize（同 zipsize，MAC 不压缩请求）

MAC 响应复用标准 16 字节帧头（<IIIHH），直接使用 frame.py 的 parse_header/decompress_body。
"""

import struct

_MAC_HEADER_FMT = "<BIBHH"
_MAC_HEADER_SIZE = 10
_MAC_HEAD_FLAG = 0x1C
_MAC_CUSTOMIZE = 0
_MAC_VERSION = 1


def build_mac_request(msg_id: int, body: bytes, *, head_flag: int = _MAC_HEAD_FLAG) -> bytes:
    """构建 MAC 协议请求帧。

    Parameters
    ----------
    msg_id : int
        MAC 命令 ID（如 0x122B）。
    body : bytes
        命令特有的请求体（不含 msg_id 前缀）。
    head_flag : int
        帧头标识字节，默认 0x1C（标准 MAC）。部分命令（如 0x1218）
        使用不同的 head_flag 区分子协议。

    Returns
    -------
    bytes
        完整的请求帧（10 字节头 + 2 字节 msg_id + body）。
    """
    inner = struct.pack("<H", msg_id) + body
    header = struct.pack(
        _MAC_HEADER_FMT,
        head_flag,
        _MAC_CUSTOMIZE,
        _MAC_VERSION,
        len(inner),
        len(inner),
    )
    return header + inner
