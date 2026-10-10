"""离线分钟线写入测试（纯离线，无网络）。"""

from __future__ import annotations

import struct
from pathlib import Path

from easy_tdx.models.bar import SecurityBar
from easy_tdx.offline.min_bar import (
    _LC_MIN_FMT,
    _MIN_FMT,
    _decode_tdx_date,
    _decode_tdx_time,
    read_5min_bars,
    read_lc_min_bars,
)
from easy_tdx.offline.write_min_bar import (
    append_5min_bars,
    append_lc_min_bars,
    encode_5min_bar,
    encode_lc_min_bar,
    get_last_5min_bar_datetime,
    get_last_lc_min_bar_datetime,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_min_bar(
    year: int = 2026,
    month: int = 6,
    day: int = 6,
    hour: int = 9,
    minute: int = 30,
    open_: float = 10.25,
    high: float = 10.50,
    low: float = 10.10,
    close: float = 10.30,
    vol: float = 5000.0,
    amount: float = 51250.0,
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
        hour=hour,
        minute=minute,
    )


def _encode_tdx_date(year: int, month: int, day: int) -> int:
    return (year - 2004) * 2048 + month * 100 + day


def _encode_tdx_time(hour: int, minute: int) -> int:
    return hour * 60 + minute


def _make_raw_5min_bar(
    year: int = 2026,
    month: int = 6,
    day: int = 6,
    hour: int = 9,
    minute: int = 30,
    open_int: int = 1025,
    high_int: int = 1050,
    low_int: int = 1010,
    close_int: int = 1030,
    amount: float = 51250.0,
    vol_int: int = 5000,
) -> bytes:
    return _MIN_FMT.pack(
        _encode_tdx_date(year, month, day),
        _encode_tdx_time(hour, minute),
        open_int,
        high_int,
        low_int,
        close_int,
        amount,
        vol_int,
        0,
    )


def _make_raw_lc_min_bar(
    year: int = 2026,
    month: int = 6,
    day: int = 6,
    hour: int = 9,
    minute: int = 30,
    open_: float = 10.25,
    high: float = 10.50,
    low: float = 10.10,
    close: float = 10.30,
    amount: float = 51250.0,
    vol: int = 5000,
) -> bytes:
    return _LC_MIN_FMT.pack(
        _encode_tdx_date(year, month, day),
        _encode_tdx_time(hour, minute),
        open_,
        high,
        low,
        close,
        amount,
        vol,
        0,
    )


# ===========================================================================
# .5 文件 (5 分钟线)
# ===========================================================================


class TestEncode5minBar:
    def test_output_length(self) -> None:
        bar = _make_min_bar()
        result = encode_5min_bar(bar)
        assert len(result) == 32

    def test_date_encoding(self) -> None:
        bar = _make_min_bar(year=2026, month=6, day=5)
        result = encode_5min_bar(bar)
        date_num = struct.unpack_from("<H", result, 0)[0]
        yr, mo, dy = _decode_tdx_date(date_num)
        assert (yr, mo, dy) == (2026, 6, 5)

    def test_time_encoding(self) -> None:
        bar = _make_min_bar(hour=14, minute=30)
        result = encode_5min_bar(bar)
        time_num = struct.unpack_from("<H", result, 2)[0]
        h, m = _decode_tdx_time(time_num)
        assert (h, m) == (14, 30)

    def test_price_encoding(self) -> None:
        """5 分钟线 OHLC 整数 × 100。"""
        bar = _make_min_bar(open_=10.25)
        result = encode_5min_bar(bar)
        open_int = struct.unpack_from("<I", result, 4)[0]
        assert open_int == 1025


class Test5minRoundTrip:
    def test_single_bar_round_trip(self, tmp_path: Path) -> None:
        bar = _make_min_bar(open_=10.25, close=10.30, vol=5000.0, amount=51250.0)
        encoded = encode_5min_bar(bar)

        filepath = tmp_path / "sh600000.5"
        filepath.write_bytes(encoded)

        bars = read_5min_bars(filepath)
        assert len(bars) == 1
        b = bars[0]
        assert abs(b.open - 10.25) < 0.01
        assert abs(b.close - 10.30) < 0.01
        assert abs(b.vol - 5000.0) < 1.0
        assert b.hour == 9 and b.minute == 30

    def test_multiple_bars(self, tmp_path: Path) -> None:
        bars_in = [
            _make_min_bar(hour=9, minute=30),
            _make_min_bar(hour=9, minute=35),
            _make_min_bar(hour=9, minute=40),
        ]
        encoded = b"".join(encode_5min_bar(b) for b in bars_in)

        filepath = tmp_path / "sh600000.5"
        filepath.write_bytes(encoded)

        bars_out = read_5min_bars(filepath)
        assert len(bars_out) == 3
        assert bars_out[0].minute == 30
        assert bars_out[2].minute == 40


class TestGetLast5minBarDatetime:
    def test_returns_last_datetime(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.5"
        filepath.write_bytes(_make_raw_5min_bar(year=2026, month=6, day=5, hour=15, minute=0))
        result = get_last_5min_bar_datetime(filepath)
        assert result == (2026, 6, 5, 15, 0)

    def test_returns_none_for_empty(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.5"
        filepath.write_bytes(b"")
        assert get_last_5min_bar_datetime(filepath) is None


class TestAppend5minBars:
    def test_append_to_existing(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.5"
        filepath.write_bytes(_make_raw_5min_bar(hour=9, minute=30))

        new_bar = _make_min_bar(hour=9, minute=35)
        written = append_5min_bars(filepath, [new_bar])
        assert written == 1

        bars = read_5min_bars(filepath)
        assert len(bars) == 2

    def test_skips_duplicate(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.5"
        filepath.write_bytes(_make_raw_5min_bar(hour=9, minute=30))

        new_bar = _make_min_bar(hour=9, minute=30)  # same datetime
        written = append_5min_bars(filepath, [new_bar])
        assert written == 0


# ===========================================================================
# .lc1 / .lc5 文件
# ===========================================================================


class TestEncodeLcMinBar:
    def test_output_length(self) -> None:
        bar = _make_min_bar()
        result = encode_lc_min_bar(bar)
        assert len(result) == 32

    def test_float_prices_preserved(self) -> None:
        bar = _make_min_bar(open_=10.255)
        result = encode_lc_min_bar(bar)
        (op,) = struct.unpack_from("<f", result, 4)
        assert abs(op - 10.255) < 0.001


class TestLcMinRoundTrip:
    def test_single_bar_round_trip(self, tmp_path: Path) -> None:
        bar = _make_min_bar(open_=10.255, close=10.31, vol=5000.0, amount=51250.0)
        encoded = encode_lc_min_bar(bar)

        filepath = tmp_path / "sh600000.lc1"
        filepath.write_bytes(encoded)

        bars = read_lc_min_bars(filepath)
        assert len(bars) == 1
        b = bars[0]
        assert abs(b.open - 10.255) < 0.001
        assert abs(b.close - 10.31) < 0.001
        assert b.hour == 9 and b.minute == 30


class TestGetLastLcMinBarDatetime:
    def test_returns_last_datetime(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.lc1"
        filepath.write_bytes(_make_raw_lc_min_bar(year=2026, month=6, day=5, hour=14, minute=55))
        result = get_last_lc_min_bar_datetime(filepath)
        assert result == (2026, 6, 5, 14, 55)

    def test_returns_none_for_empty(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.lc1"
        filepath.write_bytes(b"")
        assert get_last_lc_min_bar_datetime(filepath) is None


class TestAppendLcMinBars:
    def test_append_to_existing(self, tmp_path: Path) -> None:
        filepath = tmp_path / "sh600000.lc1"
        filepath.write_bytes(_make_raw_lc_min_bar(hour=9, minute=30))

        new_bar = _make_min_bar(hour=9, minute=31)
        written = append_lc_min_bars(filepath, [new_bar])
        assert written == 1

        bars = read_lc_min_bars(filepath)
        assert len(bars) == 2
