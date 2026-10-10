"""日期时间解码单元测试。"""

import struct

from easy_tdx.codec.datetime_ import get_datetime, get_datetime_day, get_datetime_minute, get_time


def _pack_minute(year: int, month: int, day: int, hour: int, minute: int) -> bytes:
    zipday = ((year - 2004) << 11) | (month * 100 + day)
    tminutes = hour * 60 + minute
    return struct.pack("<HH", zipday, tminutes)


def _pack_day(year: int, month: int, day: int) -> bytes:
    return struct.pack("<I", year * 10000 + month * 100 + day)


class TestGetDatetimeMinute:
    def test_basic(self):
        data = _pack_minute(2024, 4, 10, 14, 30)
        y, mo, d, h, mi, pos = get_datetime_minute(data, 0)
        assert (y, mo, d, h, mi) == (2024, 4, 10, 14, 30)
        assert pos == 4

    def test_open_time(self):
        data = _pack_minute(2026, 1, 5, 9, 30)
        y, mo, d, h, mi, pos = get_datetime_minute(data, 0)
        assert h == 9 and mi == 30

    def test_close_time(self):
        data = _pack_minute(2026, 1, 5, 15, 0)
        y, mo, d, h, mi, _ = get_datetime_minute(data, 0)
        assert h == 15 and mi == 0


class TestGetDatetimeDay:
    def test_basic(self):
        data = _pack_day(2026, 4, 10)
        y, mo, d, pos = get_datetime_day(data, 0)
        assert (y, mo, d) == (2026, 4, 10)
        assert pos == 4


class TestGetDatetime:
    def test_minute_category(self):
        data = _pack_minute(2026, 3, 15, 10, 0)
        for cat in (0, 1, 2, 3, 7, 8):
            y, mo, d, h, mi, _ = get_datetime(cat, data, 0)
            assert h == 10 and mi == 0

    def test_day_category(self):
        data = _pack_day(2026, 3, 15)
        for cat in (4, 5, 6, 9):
            y, mo, d, h, mi, _ = get_datetime(cat, data, 0)
            assert (y, mo, d) == (2026, 3, 15)
            assert h == 15 and mi == 0


class TestGetTime:
    def test_basic(self):
        data = struct.pack("<H", 14 * 60 + 30)  # 14:30
        h, mi, pos = get_time(data, 0)
        assert h == 14 and mi == 30
        assert pos == 2


class TestCategoryToMinutes:
    """分钟级 KlineCategory → 每根 bar 的分钟数；日线及以上返回 None。"""

    def test_minute_categories(self):
        from easy_tdx._df import _category_to_minutes

        # MIN_5/15/30/60/1/3
        assert _category_to_minutes(0) == 5
        assert _category_to_minutes(1) == 15
        assert _category_to_minutes(2) == 30
        assert _category_to_minutes(3) == 60
        assert _category_to_minutes(7) == 1
        assert _category_to_minutes(8) == 3

    def test_daily_plus_returns_none(self):
        from easy_tdx._df import _category_to_minutes

        for cat in (4, 5, 6, 9, 10, 11):  # DAY/WEEK/MONTH/YEAR/SEASON/YEAR_ALT
            assert _category_to_minutes(cat) is None


class TestPeriodToMinutes:
    """MAC 协议 Period → 每根 bar 的分钟数。"""

    def test_basic_periods(self):
        from easy_tdx._df import _period_to_minutes

        assert _period_to_minutes(0) == 5  # MIN_5
        assert _period_to_minutes(1) == 15  # MIN_15
        assert _period_to_minutes(2) == 30  # MIN_30
        assert _period_to_minutes(3) == 60  # MIN_60
        assert _period_to_minutes(7) == 1  # MIN_1

    def test_mins_multiplied_by_times(self):
        from easy_tdx._df import _period_to_minutes

        assert _period_to_minutes(8, 1) == 5  # MINS ×1
        assert _period_to_minutes(8, 3) == 15  # MINS ×3 = 15 分钟线

    def test_daily_plus_and_seconds_return_none(self):
        from easy_tdx._df import _period_to_minutes

        for p in (4, 5, 6, 9, 10, 11, 13):  # DAILY/WEEKLY/MONTHLY/DAYS/QUARTERLY/YEARLY/SECONDS
            assert _period_to_minutes(p) is None
