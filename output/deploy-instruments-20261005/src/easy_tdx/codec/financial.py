"""专业财务数据解析（tdxfin/gpcw.txt 列表 + .dat 二进制记录）。"""

import struct


def parse_financial_file_list(data: bytes) -> list[tuple[str, str, int]]:
    """解析 tdxfin/gpcw.txt 的内容。

    每行格式: filename,md5hash,filesize

    Returns:
        [(filename, hash, filesize), ...]
    """
    if not data:
        return []
    text = data.decode("utf-8", errors="replace").strip()
    results: list[tuple[str, str, int]] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) >= 3:
            results.append((parts[0], parts[1], int(parts[2])))
    return results


def parse_financial_dat(
    data: bytes,
    report_date: int = 0,
) -> list[tuple[str, int, int, list[float]]]:
    """解析 gpcw*.zip 内的 .dat 二进制文件。

    二进制格式（参考 pytdx.crawler.history_financial_crawler）：
      Header: 20 bytes  <1h I 1H 3L
        - unknown:     int16   (h)
        - report_date: uint32  (I)
        - max_count:   uint16  (H)   -- 股票索引条目数
        - unknown1:    uint32  (L)
        - report_size: uint32  (L)   -- 每条股票数据字节长度
        - unknown2:    uint32  (L)
      Index: max_count 条，每条 11 bytes  <6s 1c 1L
        - code:        6 bytes       -- 股票代码
        - market:      1 byte        -- 市场标识 (0=SZ, 1=SH)
        - file_offset: uint32        -- 绝对偏移（从文件开头算）
      Data: 在 file_offset 位置读取 report_size/4 个 float32

    Args:
        data: .dat 文件的完整字节
        report_date: 报告期 YYYYMMDD（从文件名提取，0 则用 header 中的值）

    Returns:
        [(code, market_byte, report_date, [float, ...]), ...]
    """
    header_fmt = "<1hI1H3L"
    header_size = struct.calcsize(header_fmt)
    if len(data) < header_size:
        return []

    header = struct.unpack(header_fmt, data[:header_size])
    max_count = header[2]
    dat_report_date = header[1]
    report_size = header[4]

    if report_date == 0:
        report_date = dat_report_date

    num_fields = report_size // 4
    if num_fields <= 0:
        return []

    index_fmt = "<6s1c1L"
    index_size = struct.calcsize(index_fmt)
    index_base = header_size

    results: list[tuple[str, int, int, list[float]]] = []
    report_fmt = f"<{num_fields}f"
    report_pack_size = struct.calcsize(report_fmt)

    for i in range(max_count):
        idx_pos = index_base + i * index_size
        if idx_pos + index_size > len(data):
            break

        code_bytes, market_byte, file_offset = struct.unpack(
            index_fmt, data[idx_pos : idx_pos + index_size]
        )
        code = code_bytes.decode("ascii", errors="replace").rstrip("\x00")

        if not code or file_offset == 0:
            continue

        # file_offset 是绝对偏移（从文件开头算）
        data_pos = file_offset
        if data_pos + report_pack_size > len(data):
            continue

        floats = list(struct.unpack(report_fmt, data[data_pos : data_pos + report_pack_size]))
        results.append((code, market_byte, report_date, floats))

    return results
