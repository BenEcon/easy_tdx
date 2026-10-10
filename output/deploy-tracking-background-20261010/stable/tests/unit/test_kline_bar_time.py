"""分钟级 K 线时间戳 bar_time（开始/结束时间）对齐的单元测试。

通达信协议用 bar 开始时间打时间戳（上午最后一根 5min 标 11:25、下午第一根标 13:00）；
bar_time="end" 切换为右端点（标 11:30/13:05），对齐 Tushare / 同花顺。
"""

from __future__ import annotations

import pandas as pd

from easy_tdx._df import (
    _apply_bar_time_align_bars,
    _apply_bar_time_align_df,
    _category_to_minutes,
)
from easy_tdx.ex.models import ExInstrumentBar
from easy_tdx.models.bar import SecurityBar

# --------------------------------------------------------------------------- #
# DataFrame 路径（A 股 security/index bars，含 hour/minute 列）
# --------------------------------------------------------------------------- #


def _bars_df(rows: list[tuple[int, int]]) -> pd.DataFrame:
    """构造含 year/month/day/hour/minute 的 K 线 DataFrame（模拟 _to_df 输出）。"""
    return pd.DataFrame(
        [
            {
                "open": 10.0,
                "close": 10.0,
                "high": 10.0,
                "low": 10.0,
                "vol": 100.0,
                "amount": 1000.0,
                "year": 2026,
                "month": 6,
                "day": 30,
                "hour": h,
                "minute": m,
            }
            for h, m in rows
        ]
    )


class TestAlignDfTimeColumns:
    def test_start_default_is_noop(self):
        df = _bars_df([(11, 25), (13, 0)])
        out = _apply_bar_time_align_df(
            df, is_intraday=True, delta_minutes=5, bar_time="start", has_time_columns=True
        )
        assert list(out["hour"]) == [11, 13]
        assert list(out["minute"]) == [25, 0]

    def test_end_aligns_to_right_endpoint(self):
        # 11:25 -> 11:30, 13:00 -> 13:05（5min 线右端点）
        df = _bars_df([(11, 25), (13, 0)])
        out = _apply_bar_time_align_df(
            df, is_intraday=True, delta_minutes=5, bar_time="end", has_time_columns=True
        )
        assert list(out["hour"]) == [11, 13]
        assert list(out["minute"]) == [30, 5]

    def test_end_cross_hour(self):
        # 9:58 + 5 = 10:03（跨小时进位）
        df = _bars_df([(9, 58)])
        out = _apply_bar_time_align_df(
            df, is_intraday=True, delta_minutes=5, bar_time="end", has_time_columns=True
        )
        assert out["hour"].iloc[0] == 10
        assert out["minute"].iloc[0] == 3

    def test_end_close_bar_15min(self):
        # 60min 线下午最后一根开始时间 14:00，右端点 15:00（跨小时但不跨日）
        df = _bars_df([(14, 0)])
        out = _apply_bar_time_align_df(
            df, is_intraday=True, delta_minutes=60, bar_time="end", has_time_columns=True
        )
        assert out["hour"].iloc[0] == 15
        assert out["minute"].iloc[0] == 0

    def test_daily_plus_not_aligned_even_with_end(self):
        # 日线及以上周期：is_intraday=False，即便 bar_time="end" 也不偏移
        df = _bars_df([(0, 0)])
        out = _apply_bar_time_align_df(
            df, is_intraday=False, delta_minutes=None, bar_time="end", has_time_columns=True
        )
        assert out["hour"].iloc[0] == 0
        assert out["minute"].iloc[0] == 0

    def test_does_not_mutate_input(self):
        df = _bars_df([(11, 25)])
        _apply_bar_time_align_df(
            df, is_intraday=True, delta_minutes=5, bar_time="end", has_time_columns=True
        )
        # 原 DataFrame 不被修改
        assert df["minute"].iloc[0] == 25

    def test_empty_df(self):
        df = pd.DataFrame()
        out = _apply_bar_time_align_df(
            df, is_intraday=True, delta_minutes=5, bar_time="end", has_time_columns=True
        )
        assert out.empty


# --------------------------------------------------------------------------- #
# DataFrame 路径（MAC，已合并为 datetime 列）
# --------------------------------------------------------------------------- #


def _mac_df(times: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"datetime": pd.to_datetime(["2026-06-30 " + t for t in times])})


class TestAlignDfDatetimeColumn:
    def test_mac_end_aligns(self):
        df = _mac_df(["11:25:00", "13:00:00"])
        out = _apply_bar_time_align_df(
            df, is_intraday=True, delta_minutes=5, bar_time="end", has_time_columns=False
        )
        assert out["datetime"].iloc[0] == pd.Timestamp("2026-06-30 11:30:00")
        assert out["datetime"].iloc[1] == pd.Timestamp("2026-06-30 13:05:00")

    def test_mac_daily_not_aligned(self):
        df = _mac_df(["00:00:00"])
        out = _apply_bar_time_align_df(
            df, is_intraday=False, delta_minutes=None, bar_time="end", has_time_columns=False
        )
        assert out["datetime"].iloc[0] == pd.Timestamp("2026-06-30 00:00:00")


# --------------------------------------------------------------------------- #
# dataclass 列表路径（扩展行情 ex client）
# --------------------------------------------------------------------------- #


def _make_ex_bar(hour: int, minute: int) -> ExInstrumentBar:
    return ExInstrumentBar(
        open=10.0,
        high=10.0,
        low=10.0,
        close=10.0,
        position=0,
        trade=0,
        amount=0.0,
        year=2026,
        month=6,
        day=30,
        hour=hour,
        minute=minute,
    )


class TestAlignBars:
    def test_end_aligns_ex_bars(self):
        bars = [_make_ex_bar(11, 25), _make_ex_bar(13, 0)]
        out = _apply_bar_time_align_bars(bars, is_intraday=True, delta_minutes=5, bar_time="end")
        assert (out[0].hour, out[0].minute) == (11, 30)
        assert (out[1].hour, out[1].minute) == (13, 5)

    def test_start_is_noop(self):
        bars = [_make_ex_bar(11, 25)]
        out = _apply_bar_time_align_bars(bars, is_intraday=True, delta_minutes=5, bar_time="start")
        assert (out[0].hour, out[0].minute) == (11, 25)

    def test_end_cross_hour(self):
        bars = [_make_ex_bar(9, 58)]
        out = _apply_bar_time_align_bars(bars, is_intraday=True, delta_minutes=5, bar_time="end")
        assert (out[0].hour, out[0].minute) == (10, 3)

    def test_does_not_mutate_input_bars(self):
        bars = [_make_ex_bar(11, 25)]
        _apply_bar_time_align_bars(bars, is_intraday=True, delta_minutes=5, bar_time="end")
        assert bars[0].hour == 11 and bars[0].minute == 25

    def test_security_bar_datetime_str(self):
        """SecurityBar 的 datetime_str 在 bar_time='end' 后应反映右端点。"""
        bar = SecurityBar(
            open=10.0,
            close=10.0,
            high=10.0,
            low=10.0,
            vol=100.0,
            amount=1000.0,
            year=2026,
            month=6,
            day=30,
            hour=11,
            minute=25,
        )
        assert bar.datetime_str == "2026-06-30 11:25"


# --------------------------------------------------------------------------- #
# 集成：category → 偏移链路
# --------------------------------------------------------------------------- #


class TestCategoryChain:
    def test_min5_end_alignment(self):
        """模拟 5min 线上午最后一根：category=0 → delta=5 → 11:25 右端点 11:30。"""
        delta = _category_to_minutes(0)
        df = _bars_df([(11, 25)])
        out = _apply_bar_time_align_df(
            df,
            is_intraday=delta is not None,
            delta_minutes=delta,
            bar_time="end",
            has_time_columns=True,
        )
        assert out["hour"].iloc[0] == 11
        assert out["minute"].iloc[0] == 30
