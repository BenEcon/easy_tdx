"""MAC 多日分时图（0x123E）解析测试。

包含 Issue #10 回归：当服务器返回的 minutes ≥ 1440（个别服务器累计或异常值）
时，parse_response 不应抛 ValueError，而应按 % 24 折算为日内时刻。
"""

import struct

from easy_tdx.mac.commands.tick_charts import TickChartsCmd
from easy_tdx.models.enums import Market


def _build_multi_tick_body(
    days: int,
    page_size: int,
    minutes_grid: list[list[int]],
) -> bytes:
    """构造一个多日分时图响应 body。

    Args:
        days:       天数（写入 count）。
        page_size:  每天分时点数。
        minutes_grid: 长度 days 的列表，每个元素是长度 page_size 的 minutes 值列表。
    """
    # 头部: market(2) + code(22)
    body = bytearray(struct.pack("<H22s", int(Market.SH), b"600519" + b"\x00" * 16))
    # 5 dates + 5 pre_closes（不足 5 天用 0 填充）at offset 24
    dates = [20250115, 20250114, 20250113, 20250110, 20250109]
    pre_closes = [1509.0, 1512.0, 1510.0, 1508.0, 1511.0]
    body += struct.pack("<5I", *dates)
    body += struct.pack("<5f", *pre_closes)
    # count(2) + send_last(1) + page_size(2) + total(2) at offset 64
    body += struct.pack("<HBHH", days, 1, page_size, days * page_size)
    # tick records at offset 71, each 14 bytes: <HffHH
    for day in minutes_grid:
        assert len(day) == page_size
        for m in day:
            body += struct.pack("<HffHH", m, 1510.0, 1510.0, 100, 0)
    # 尾部元数据: <44sBHf5x2I5ffIf12s2fI
    body += struct.pack("<44s", "贵州茅台".encode("gbk") + b"\x00" * 32)
    body += struct.pack("<BHf", 2, 0, 1.0)  # decimal, category, vol_unit
    body += b"\x00" * 5
    body += struct.pack("<2I", 20250115, 0)
    body += struct.pack("<5f", 1509.0, 1510.0, 1520.0, 1500.0, 1515.0)
    body += struct.pack("<fI", 0.0, 100000)  # momentum, vol
    body += struct.pack("<f", 1000000.0)  # amount
    body += b"\x00" * 12
    body += struct.pack("<2f", 0.5, 1512.0)  # turnover, avg
    body += struct.pack("<I", 0)  # industry
    return bytes(body)


def test_multi_tick_charts_normal_minutes():
    """常规数据：minutes 每天 570..689, 780..899，解析正常。"""
    page_size = 4
    grid = [
        [570, 571, 572, 573],
        [570, 600, 780, 899],
        [570, 571, 572, 573],
    ]
    body = _build_multi_tick_body(3, page_size, grid)

    chart = TickChartsCmd(int(Market.SH), "600519", None, 3).parse_response(body)

    assert len(chart.charts) == 3
    # 第一天第一个点 09:30:00
    assert str(chart.charts[0].ticks[0].time) == "09:30:00"
    # 最后一个点 14:59:00
    assert str(chart.charts[1].ticks[3].time) == "14:59:00"


def test_multi_tick_charts_oversized_minutes_no_crash():
    """Issue #10 回归：minutes ≥ 1440（如累计/异常值）不应抛 ValueError。

    用户报告 hour must be in 0..23, not 1039（即 minutes // 60 == 1039）。
    修复后应按 % 24 折算为日内时刻，保证不崩溃且结果合理。
    """
    page_size = 4
    # 第一天第 2 个点 minutes=62340（= 报错现场，//60=1039），其余正常
    grid = [
        [570, 62340, 572, 573],
        [570, 600, 780, 899],
    ]
    body = _build_multi_tick_body(2, page_size, grid)

    chart = TickChartsCmd(int(Market.SH), "600519", None, 2).parse_response(body)

    assert len(chart.charts) == 2
    # 折算后 62340 -> 62340//60 % 24 = 1039 % 24 = 7 时, 62340 % 60 = 0 分
    assert str(chart.charts[0].ticks[1].time) == "07:00:00"
    # 正常点不受影响
    assert str(chart.charts[0].ticks[0].time) == "09:30:00"
    assert str(chart.charts[1].ticks[3].time) == "14:59:00"


def _build_multi_tick_body_partial(
    days: int,
    page_size: int,
    total: int,
    flat_minutes: list[int],
) -> bytes:
    """构造一个 partial-day 多日分时图响应 body（PR #13 修复场景）。

    与 _build_multi_tick_body 的区别：body 里只塞 total 条 tick（而非
    days*page_size），用于模拟 start_date=None 且最新交易日数据不完整时
    服务器实际返回的包。

    Args:
        days:       天数（写入 count）。
        page_size:  每天额定分时点数。
        total:      写入 total 字段的实际 tick 总数（< days*page_size）。
        flat_minutes: 长度 total 的 minutes 值列表（按天连续铺开）。
    """
    body = bytearray(struct.pack("<H22s", int(Market.SH), b"600519" + b"\x00" * 16))
    dates = [20250115, 20250114, 20250113, 20250110, 20250109]
    pre_closes = [1509.0, 1512.0, 1510.0, 1508.0, 1511.0]
    body += struct.pack("<5I", *dates)
    body += struct.pack("<5f", *pre_closes)
    body += struct.pack("<HBHH", days, 1, page_size, total)
    assert len(flat_minutes) == total
    for m in flat_minutes:
        body += struct.pack("<HffHH", m, 1510.0, 1510.0, 100, 0)
    # 尾部元数据（与 _build_multi_tick_body 完全一致）
    body += struct.pack("<44s", "贵州茅台".encode("gbk") + b"\x00" * 32)
    body += struct.pack("<BHf", 2, 0, 1.0)
    body += b"\x00" * 5
    body += struct.pack("<2I", 20250115, 0)
    body += struct.pack("<5f", 1509.0, 1510.0, 1520.0, 1500.0, 1515.0)
    body += struct.pack("<fI", 0.0, 100000)
    body += struct.pack("<f", 1000000.0)
    body += b"\x00" * 12
    body += struct.pack("<2f", 0.5, 1512.0)
    body += struct.pack("<I", 0)
    return bytes(body)


def test_multi_tick_charts_partial_day():
    """PR #13 回归：total < count*page_size 时不应崩溃，tick 按天正确分配。

    模拟 start_date=None 且最新交易日数据不完整的场景。修复前，
    tail_offset = 71 + count*page_size*14 会偏大导致越界/尾部读错位。
    修复后应按 actual_total 反推尾部偏移，并把首日分配为部分 tick。

    构造：days=3, page_size=4, total=6
        修复逻辑（tick_charts.py 的 partial 分支）：
            complete_days = min(count-1, total//page_size) = min(2, 1) = 1
            first_day_count = total - complete_days*page_size = 6 - 4 = 2
            empty_days = count - complete_days - 1 = 1
            => tick_counts = [2, 4, 0]
    """
    body = _build_multi_tick_body_partial(
        days=3, page_size=4, total=6, flat_minutes=[570, 571, 570, 571, 572, 573]
    )

    chart = TickChartsCmd(int(Market.SH), "600519", None, 3).parse_response(body)

    assert len(chart.charts) == 3
    # 首日（最新交易日）部分数据：2 条 tick
    assert len(chart.charts[0].ticks) == 2
    assert str(chart.charts[0].ticks[0].time) == "09:30:00"
    assert str(chart.charts[0].ticks[1].time) == "09:31:00"
    # 第二天完整：4 条 tick
    assert len(chart.charts[1].ticks) == 4
    assert str(chart.charts[1].ticks[0].time) == "09:30:00"
    # 第三天无数据（盘前/非交易日）
    assert len(chart.charts[2].ticks) == 0
    # 尾部元数据解析正确（未因偏移错误而乱码/越界）
    assert chart.name == "贵州茅台"
    assert chart.pre_close == 1509.0
    assert chart.open == 1510.0


def test_multi_tick_charts_request_layout():
    """验证请求包布局与文档一致：market + code(22) + start_ymd + days + 1。"""
    from datetime import date as date_cls

    cmd = TickChartsCmd(int(Market.SH), "600519", date_cls(2025, 1, 15), 5)
    req = cmd.build_request()
    # MAC 帧前缀由 build_mac_request 生成，body 在其后；校验 body 嵌入其中
    expected_body = struct.pack(
        "<H22sIHH6x",
        int(Market.SH),
        b"600519" + b"\x00" * 16,
        20250115,
        5,
        1,
    )
    assert expected_body in req
