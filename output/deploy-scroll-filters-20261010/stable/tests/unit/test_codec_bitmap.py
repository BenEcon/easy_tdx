"""codec/bitmap.py 单元测试 —— MAC 协议字段位图编解码。

之前 bitmap.py（~490 行）零测试（审计报告 #9）。本文件覆盖：
FieldBit 字段属性、PresetField 组合、FieldSelection 去重、
build_bitmap 20 字节输出、get_active_fields 往返解析。

风格参照 test_codec_frame.py：纯函数式、无 mock、struct 构造输入。
"""

from __future__ import annotations

from easy_tdx.codec.bitmap import (
    FieldBit,
    FieldSelection,
    PresetField,
    build_bitmap,
    build_exclude_flags,
    get_active_fields,
    normalize_fields,
)


class TestFieldBit:
    def test_field_name_is_lower(self) -> None:
        assert FieldBit.PRE_CLOSE.field_name == "pre_close"
        assert FieldBit.OPEN.field_name == "open"

    def test_fmt_and_desc_attached(self) -> None:
        assert FieldBit.OPEN.fmt == "<f"
        assert FieldBit.OPEN.desc == "开盘价"
        assert FieldBit.VOL.fmt == "<I"

    def test_value_is_bit_position(self) -> None:
        assert FieldBit.PRE_CLOSE == 0x00
        assert FieldBit.OPEN == 0x01


class TestPresetField:
    def test_ohlc_contains_four_fields(self) -> None:
        names = {f.name for f in PresetField.OHLC.value}
        assert names == {"OPEN", "HIGH", "LOW", "CLOSE"}

    def test_chain_plus_combines(self) -> None:
        combined = PresetField.OHLC + FieldBit.VOL
        sel = normalize_fields(combined)
        bits = {b for b in sel}
        assert FieldBit.VOL in bits
        assert FieldBit.OPEN in bits

    def test_chain_or_combines(self) -> None:
        combined = PresetField.OHLC | PresetField.VOLUME
        sel = normalize_fields(combined)
        bits = {b for b in sel}
        assert FieldBit.VOL in bits
        assert FieldBit.AMOUNT in bits


class TestFieldSelection:
    def test_dedup_preserves_order(self) -> None:
        sel = FieldSelection(FieldBit.OPEN, FieldBit.OPEN, FieldBit.HIGH)
        bits = list(sel)
        assert bits == [FieldBit.OPEN, FieldBit.HIGH]

    def test_empty_selection(self) -> None:
        assert list(FieldSelection()) == []


class TestBuildBitmap:
    def test_single_field_sets_correct_bit(self) -> None:
        # FieldBit.OPEN == 0x01，bit 1 应被置位
        ba = build_bitmap(FieldBit.OPEN)
        assert len(ba) == 20
        assert ba[0] == 0b0000_0010  # bit 1
        # 控制区 4 字节默认 0
        assert bytes(ba[16:20]) == b"\x00\x00\x00\x00"

    def test_multiple_fields_or(self) -> None:
        ba = build_bitmap(PresetField.OHLC)
        assert len(ba) == 20
        # OPEN(1)+HIGH(2)+LOW(3)+CLOSE(4) → bit 1,2,3,4 → 0b11110 = 30
        assert ba[0] == 0b0001_1110

    def test_exclude_flags_appended(self) -> None:
        ba = build_bitmap(FieldBit.OPEN, exclude_flags=0x1234)
        assert len(ba) == 20
        assert bytes(ba[16:20]) == b"\x34\x12\x00\x00"

    def test_debug_preset_all_ff(self) -> None:
        ba = build_bitmap(PresetField.DEBUG)
        assert ba == bytearray(b"\xff" * 20)


class TestGetActiveFields:
    def test_roundtrip(self) -> None:
        original = PresetField.OHLC
        ba = build_bitmap(original)
        active = get_active_fields(bytes(ba[:16]))
        active_names = {f.name for f, _ in active}
        assert active_names == {"OPEN", "HIGH", "LOW", "CLOSE"}

    def test_empty_bitmap(self) -> None:
        active = get_active_fields(b"\x00" * 16)
        assert active == []

    def test_fmt_returned(self) -> None:
        ba = build_bitmap(FieldBit.VOL)
        active = get_active_fields(bytes(ba[:16]))
        assert len(active) == 1
        field, fmt = active[0]
        assert field == FieldBit.VOL
        assert fmt == "<I"

    def test_sorted_by_bit_position(self) -> None:
        # 故意逆序传入
        ba = build_bitmap([FieldBit.CLOSE, FieldBit.OPEN, FieldBit.HIGH])
        active = get_active_fields(bytes(ba[:16]))
        positions = [f.value for f, _ in active]
        assert positions == sorted(positions)


class TestBuildExcludeFlags:
    def test_zero(self) -> None:
        assert build_exclude_flags(0) == b"\x00\x00\x00\x00"

    def test_value(self) -> None:
        assert build_exclude_flags(0xFF) == b"\xff\x00\x00\x00"
