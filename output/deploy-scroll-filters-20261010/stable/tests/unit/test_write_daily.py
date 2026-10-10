"""离线日线写入测试（纯离线，无网络）。"""

from __future__ import annotations

import struct
from pathlib import Path

from easy_tdx.models.bar import SecurityBar
from easy_tdx.offline.daily_bar import (
    _DAILY_FMT,
    read_daily_bars,
)
from easy_tdx.offline.write_daily import (
    append_daily_bars,
    encode_daily_bar,
    get_last_bar_date,
    sync_daily_bars_from_security_bars,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_bar(
    year: int = 2026,
    month: int = 6,
    day: int = 6,
    open_: float = 10.25,
    high: float = 10.50,
    low: float = 10.10,
    close: float = 10.30,
    vol: float = 100000.0,
    amount: float = 1025000.0,
) -> SecurityBar:
    return SecurityBar(
        open=open_,
        close=close,
        high=high,
        low=low,
        vol=vol,
        amount=amount,
        year=year,
        month=month,
        day=day,
        hour=0,
        minute=0,
    )


def _make_raw_bar(
    year: int = 2026,
    month: int = 6,
    day: int = 6,
    open_int: int = 1025,
    high_int: int = 1050,
    low_int: int = 1010,
    close_int: int = 1030,
    amount: float = 1025000.0,
    vol_int: int = 100000,
    reserved: int = 0,
) -> bytes:
    """直接用原始整数构造一条 32 字节 .day 记录。"""
    date_int = year * 10000 + month * 100 + day
    return _DAILY_FMT.pack(
        date_int, open_int, high_int, low_int, close_int, amount, vol_int, reserved
    )


# ---------------------------------------------------------------------------
# encode_daily_bar
# ---------------------------------------------------------------------------


class TestEncodeDailyBar:
    """编码测试：SecurityBar → 32 字节。"""

    def test_output_length(self) -> None:
        bar = _make_bar()
        result = encode_daily_bar(bar, price_coeff=0.01, vol_coeff=0.01)
        assert len(result) == 32

    def test_date_encoding(self) -> None:
        bar = _make_bar(year=2025, month=3, day=15)
        result = encode_daily_bar(bar, price_coeff=0.01, vol_coeff=0.01)
        date_int = struct.unpack_from("<I", result, 0)[0]
        assert date_int == 20250315

    def test_price_encoding_a_stock(self) -> None:
        """A股：系数 0.01，即 float × 100 → 整数。"""
        bar = _make_bar(open_=10.25)
        result = encode_daily_bar(bar, price_coeff=0.01, vol_coeff=0.01)
        open_int = struct.unpack_from("<I", result, 4)[0]
        assert open_int == 1025

    def test_price_encoding_index(self) -> None:
        """指数：系数 0.01。"""
        bar = _make_bar(open_=3250.18)
        result = encode_daily_bar(bar, price_coeff=0.01, vol_coeff=1.0)
        open_int = struct.unpack_from("<I", result, 4)[0]
        assert open_int == 325018

    def test_price_encoding_fund(self) -> None:
        """基金：系数 0.001，即 float × 1000 → 整数。"""
        bar = _make_bar(open_=1.523)
        result = encode_daily_bar(bar, price_coeff=0.001, vol_coeff=1.0)
        open_int = struct.unpack_from("<I", result, 4)[0]
        assert open_int == 1523

    def test_volume_encoding_a_stock(self) -> None:
        """A股量系数 0.01。"""
        bar = _make_bar(vol=12345.67)
        result = encode_daily_bar(bar, price_coeff=0.01, vol_coeff=0.01)
        vol_int = struct.unpack_from("<I", result, 24)[0]
        assert vol_int == 1234567

    def test_volume_encoding_index(self) -> None:
        """指数量系数 1.0。"""
        bar = _make_bar(vol=123456789.0)
        result = encode_daily_bar(bar, price_coeff=0.01, vol_coeff=1.0)
        vol_int = struct.unpack_from("<I", result, 24)[0]
        assert vol_int == 123456789

    def test_amount_as_float32(self) -> None:
        bar = _make_bar(amount=1_025_000.0)
        result = encode_daily_bar(bar, price_coeff=0.01, vol_coeff=0.01)
        (amt_out,) = struct.unpack_from("<f", result, 20)
        assert abs(amt_out - 1_025_000.0) < 1.0

    def test_reserved_is_zero(self) -> None:
        bar = _make_bar()
        result = encode_daily_bar(bar, price_coeff=0.01, vol_coeff=0.01)
        reserved = struct.unpack_from("<I", result, 28)[0]
        assert reserved == 0


# ---------------------------------------------------------------------------
# round-trip: encode → read back
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """编码后写文件，再读回，验证数据一致。"""

    def test_single_bar_round_trip(self, tmp_path: Path) -> None:
        bar = _make_bar(
            open_=10.25, high=10.50, low=10.10, close=10.30, vol=100000.0, amount=1025000.0
        )
        encoded = encode_daily_bar(bar, price_coeff=0.01, vol_coeff=0.01)

        filepath = tmp_path / "sh600000.day"
        filepath.write_bytes(encoded)

        bars = read_daily_bars(filepath)
        assert len(bars) == 1

        b = bars[0]
        assert b.year == 2026 and b.month == 6 and b.day == 6
        assert abs(b.open - 10.25) < 0.01
        assert abs(b.high - 10.50) < 0.01
        assert abs(b.low - 10.10) < 0.01
        assert abs(b.close - 10.30) < 0.01
        assert abs(b.vol - 100000.0) < 1.0
        assert abs(b.amount - 1025000.0) < 1.0

    def test_multiple_bars_round_trip(self, tmp_path: Path) -> None:
        bars_in = [
            _make_bar(year=2026, month=6, day=4, open_=10.0, close=10.1),
            _make_bar(year=2026, month=6, day=5, open_=10.1, close=10.2),
            _make_bar(year=2026, month=6, day=6, open_=10.2, close=10.3),
        ]
        encoded = b"".join(encode_daily_bar(b, price_coeff=0.01, vol_coeff=0.01) for b in bars_in)

        filepath = tmp_path / "sh600000.day"
        filepath.write_bytes(encoded)

        bars_out = read_daily_bars(filepath)
        assert len(bars_out) == 3
        assert bars_out[0].day == 4
        assert bars_out[2].day == 6

    def test_index_round_trip(self, tmp_path: Path) -> None:
        """指数：价格系数 0.01，量系数 1.0。"""
        bar = _make_bar(open_=3250.18, close=3260.5, vol=123456789.0)
        encoded = encode_daily_bar(bar, price_coeff=0.01, vol_coeff=1.0)

        filepath = tmp_path / "sh000001.day"
        filepath.write_bytes(encoded)

        bars = read_daily_bars(filepath)
        assert len(bars) == 1
        assert abs(bars[0].open - 3250.18) < 0.01
        assert abs(bars[0].vol - 123456789.0) < 1.0


# ---------------------------------------------------------------------------
# get_last_bar_date
# ---------------------------------------------------------------------------


class TestGetLastBarDate:
    def test_returns_last_date(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.day"
        filepath.write_bytes(_make_raw_bar(year=2026, month=6, day=5))
        assert get_last_bar_date(filepath) == 20260605

    def test_returns_none_for_empty_file(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.day"
        filepath.write_bytes(b"")
        assert get_last_bar_date(filepath) is None

    def test_returns_none_for_short_file(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.day"
        filepath.write_bytes(b"\x00" * 16)  # < 32 bytes
        assert get_last_bar_date(filepath) is None

    def test_returns_last_of_multiple(self, tmp_path: Path) -> None:
        data = (
            _make_raw_bar(year=2026, month=6, day=3)
            + _make_raw_bar(year=2026, month=6, day=4)
            + _make_raw_bar(year=2026, month=6, day=5)
        )
        filepath = tmp_path / "sh600000.day"
        filepath.write_bytes(data)
        assert get_last_bar_date(filepath) == 20260605


# ---------------------------------------------------------------------------
# append_daily_bars
# ---------------------------------------------------------------------------


class TestAppendDailyBars:
    def test_append_to_existing(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.day"
        filepath.write_bytes(_make_raw_bar(year=2026, month=6, day=5))

        new_bar = _make_bar(year=2026, month=6, day=6, open_=10.3, close=10.4)
        append_daily_bars(filepath, [new_bar], price_coeff=0.01, vol_coeff=0.01)

        bars = read_daily_bars(filepath)
        assert len(bars) == 2
        assert bars[0].day == 5
        assert bars[1].day == 6

    def test_append_to_empty_file(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.day"
        filepath.write_bytes(b"")

        new_bar = _make_bar(year=2026, month=6, day=6)
        append_daily_bars(filepath, [new_bar], price_coeff=0.01, vol_coeff=0.01)

        bars = read_daily_bars(filepath)
        assert len(bars) == 1
        assert bars[0].day == 6

    def test_append_skips_duplicate_date(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.day"
        filepath.write_bytes(_make_raw_bar(year=2026, month=6, day=6))

        new_bar = _make_bar(year=2026, month=6, day=6)  # same date
        written = append_daily_bars(filepath, [new_bar], price_coeff=0.01, vol_coeff=0.01)
        assert written == 0  # skipped

        bars = read_daily_bars(filepath)
        assert len(bars) == 1  # no duplicate

    def test_append_multiple_filters_duplicates(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.day"
        filepath.write_bytes(_make_raw_bar(year=2026, month=6, day=5))

        bars_to_append = [
            _make_bar(year=2026, month=6, day=5),  # dup
            _make_bar(year=2026, month=6, day=6),  # new
            _make_bar(year=2026, month=6, day=7),  # new
        ]
        written = append_daily_bars(filepath, bars_to_append, price_coeff=0.01, vol_coeff=0.01)
        assert written == 2

        bars = read_daily_bars(filepath)
        assert len(bars) == 3


# ---------------------------------------------------------------------------
# sync_daily_bars_from_security_bars
# ---------------------------------------------------------------------------


class TestSyncDailyBars:
    """模拟完整同步流程（不需要真实服务端，手动构造 SecurityBar 列表）。"""

    def test_sync_appends_new_only(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.day"
        # 文件已有 6月4日和6月5日
        filepath.write_bytes(
            _make_raw_bar(year=2026, month=6, day=4) + _make_raw_bar(year=2026, month=6, day=5)
        )

        # 模拟服务端返回的数据：6月3日~6月7日
        server_bars = [
            _make_bar(year=2026, month=6, day=3),
            _make_bar(year=2026, month=6, day=4),
            _make_bar(year=2026, month=6, day=5),
            _make_bar(year=2026, month=6, day=6),
            _make_bar(year=2026, month=6, day=7),
        ]

        written = sync_daily_bars_from_security_bars(
            filepath, server_bars, price_coeff=0.01, vol_coeff=0.01
        )
        assert written == 2  # only 6/6 and 6/7

        bars = read_daily_bars(filepath)
        assert len(bars) == 4  # 6/4, 6/5 (original) + 6/6, 6/7 (new)

    def test_sync_empty_file(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.day"
        filepath.write_bytes(b"")

        server_bars = [
            _make_bar(year=2026, month=6, day=4),
            _make_bar(year=2026, month=6, day=5),
        ]

        written = sync_daily_bars_from_security_bars(
            filepath, server_bars, price_coeff=0.01, vol_coeff=0.01
        )
        assert written == 2

        bars = read_daily_bars(filepath)
        assert len(bars) == 2

    def test_sync_nothing_new(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.day"
        filepath.write_bytes(_make_raw_bar(year=2026, month=6, day=7))

        server_bars = [
            _make_bar(year=2026, month=6, day=6),
            _make_bar(year=2026, month=6, day=7),
        ]

        written = sync_daily_bars_from_security_bars(
            filepath, server_bars, price_coeff=0.01, vol_coeff=0.01
        )
        assert written == 0
