import math

import pytest

from fch_editor.reader import RawF32, Reader
from fch_editor.writer import Writer
from fch_editor.errors import FormatError


def roundtrip(write, read):
    w = Writer()
    write(w)
    data = w.to_bytes()
    r = Reader(data)
    value = read(r)
    assert r.at_end()
    return value, data


@pytest.mark.parametrize("v", [0, 1, -1, 2**31 - 1, -(2**31)])
def test_i32_roundtrip(v):
    assert roundtrip(lambda w: w.i32(v), Reader.i32)[0] == v


def test_fixed_width_primitives():
    assert roundtrip(lambda w: w.i64(-(2**63)), Reader.i64)[0] == -(2**63)
    assert roundtrip(lambda w: w.u16(65535), Reader.u16)[0] == 65535
    assert roundtrip(lambda w: w.u8(255), Reader.u8)[0] == 255
    value, data = roundtrip(lambda w: w.vec3((1.5, -0.0, 3.25)), Reader.vec3)
    assert value == (1.5, -0.0, 3.25)
    assert data[4:8] == b"\x00\x00\x00\x80"  # sign of -0.0 survives, not just its value
    assert math.copysign(1.0, value[1]) == -1.0


def test_writer_rejects_out_of_range():
    with pytest.raises(ValueError):
        Writer().u16(65536)
    with pytest.raises(ValueError):
        Writer().i32(2**31)
    with pytest.raises(ValueError):
        Writer().u8(-1)
    with pytest.raises(ValueError):
        Writer().f32(1e40)  # struct raises OverflowError, not struct.error
    with pytest.raises(ValueError):
        Writer().num_items(32768)
    with pytest.raises(ValueError):
        Writer().string("\ud800")  # lone surrogate cannot be UTF-8 encoded


def test_u8_and_num_items_reject_non_int_with_a_clean_valueerror():
    """u8/num_items are hand-rolled (no struct.Struct backing them), unlike
    u16/i32/i64/f32, whose struct.pack already turns a wrong type into a
    caught struct.error. Without their own explicit type check, a float in
    range (e.g. 5.0) would pass the bounds check and only fail inside
    bytearray.append()/a bit-shift, as a raw, uncaught TypeError -- exactly
    what let a float item slot crash fch_editor.web.bridge.Session.add_edit
    (see tests/test_web_bridge.py's regression test for the caller-facing
    side of this bug)."""
    for bad in (5.0, "5", True, None):
        with pytest.raises(ValueError):
            Writer().u8(bad)
        with pytest.raises(ValueError):
            Writer().num_items(bad)


def test_raw_f32_requires_four_bytes():
    with pytest.raises(ValueError):
        RawF32(b"\x00")


@pytest.mark.parametrize("s", ["", "Lorce", "x" * 127, "x" * 128, "y" * 300, "Lörce ᚠ 🐺"])
def test_string_roundtrip(s):
    value, data = roundtrip(lambda w: w.string(s), Reader.string)
    assert value == s
    byte_len = len(s.encode("utf-8"))
    assert len(data) == byte_len + (1 if byte_len < 128 else 2)


def test_string_rejects_non_canonical_length():
    with pytest.raises(FormatError, match="non-canonical"):
        Reader(b"\x81\x00a").string()


def test_string_rejects_overlong_varint_and_huge_length():
    with pytest.raises(FormatError, match="longer than 5 bytes"):
        Reader(b"\xff\xff\xff\xff\xff\x01").string()
    with pytest.raises(FormatError, match="need"):
        Reader(b"\xff\xff\xff\xff\x07").string()  # 2^31-1 bytes claimed, none present


def test_string_rejects_invalid_utf8():
    with pytest.raises(FormatError, match="UTF-8"):
        Reader(b"\x02\xc3\x28").string()


def test_truncated_read_reports_offset_and_path():
    r = Reader(b"\x05abc", base_offset=0x100)
    with r.scope("player"), r.scope("name"):
        with pytest.raises(FormatError) as e:
            r.string()
    assert e.value.path == "player.name"
    assert e.value.offset == 0x101


def test_bool_is_strict():
    assert roundtrip(lambda w: w.bool(True), Reader.bool)[0] is True
    with pytest.raises(FormatError, match="bool"):
        Reader(b"\x02").bool()


@pytest.mark.parametrize("n", [0, 127, 128, 300, 32767])
def test_num_items_roundtrip(n):
    value, data = roundtrip(lambda w: w.num_items(n), Reader.num_items)
    assert value == n
    assert len(data) == (1 if n < 128 else 2)


def test_num_items_rejects_non_canonical():
    with pytest.raises(FormatError):
        Reader(b"\x80\x05").num_items()


def test_nan_payload_preserved():
    raw = b"\x01\x00\xc0\x7f"
    v = Reader(raw).f32()
    assert isinstance(v, RawF32) and math.isnan(v)
    w = Writer()
    w.f32(v)
    assert w.to_bytes() == raw


def test_byte_array_and_count_guard():
    assert roundtrip(lambda w: w.bytes_(b"\x00\x01"), Reader.bytes_)[0] == b"\x00\x01"
    with pytest.raises(FormatError, match="implausible count"):
        Reader(b"\xff\xff\xff\x7f").count()
    with pytest.raises(FormatError, match="implausible count"):
        Reader(b"\xff\xff\xff\xff").count()
