"""Little-endian decoding matching the game's ZPackage / BinaryReader encoding.

Every read is bounds-checked and reports the byte offset plus the current field
path. Decoding is strict wherever a lenient read could not be re-encoded to the
same bytes (non-canonical lengths, bools other than 0/1, invalid UTF-8).
"""
import math
import struct
from contextlib import contextmanager

from .errors import FormatError

I32 = struct.Struct("<i")
I64 = struct.Struct("<q")
U16 = struct.Struct("<H")
F32 = struct.Struct("<f")


class RawF32(float):
    """A NaN read from a save, remembering its exact bit pattern.

    Python floats cannot carry NaN payloads through struct packing, so the
    writer re-emits the original 4 bytes. Like any NaN it never compares equal,
    so change detection must compare `.raw` rather than values.
    """

    raw: bytes

    def __new__(cls, raw: bytes):
        if len(raw) != 4:
            raise ValueError(f"RawF32 needs exactly 4 bytes, got {len(raw)}")
        obj = super().__new__(cls, math.nan)
        obj.raw = bytes(raw)
        return obj

    def __reduce__(self):
        # copy/deepcopy/pickle must rebuild from the bit pattern, not the float value.
        return (type(self), (self.raw,))


def encode_7bit(n: int) -> bytes:
    """.NET Write7BitEncodedInt for a non-negative length."""
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


class Reader:
    def __init__(self, data: bytes, base_offset: int = 0):
        self._data = memoryview(data)
        self._pos = 0
        self._base = base_offset
        self._path: list[str] = []

    @property
    def offset(self) -> int:
        """Absolute offset, including the base of an enclosing blob."""
        return self._base + self._pos

    @property
    def remaining(self) -> int:
        return len(self._data) - self._pos

    def at_end(self) -> bool:
        return self._pos == len(self._data)

    @contextmanager
    def scope(self, name: str):
        """Label reads inside the block with a field path for error messages."""
        self._path.append(name)
        try:
            yield
        finally:
            self._path.pop()

    def error(self, message: str, at: int | None = None) -> FormatError:
        return FormatError(message, self.offset if at is None else at, ".".join(self._path))

    def raw(self, n: int) -> bytes:
        if n < 0 or n > self.remaining:
            raise self.error(f"need {n} bytes, {self.remaining} left")
        chunk = bytes(self._data[self._pos:self._pos + n])
        self._pos += n
        return chunk

    def u8(self) -> int:
        return self.raw(1)[0]

    def bool(self) -> bool:
        at = self.offset
        v = self.u8()
        if v > 1:
            raise self.error(f"bool byte must be 0 or 1, got {v}", at)
        return v == 1

    def u16(self) -> int:
        return U16.unpack(self.raw(2))[0]

    def i32(self) -> int:
        return I32.unpack(self.raw(4))[0]

    def i64(self) -> int:
        return I64.unpack(self.raw(8))[0]

    def f32(self) -> float:
        b = self.raw(4)
        v = F32.unpack(b)[0]
        return RawF32(b) if math.isnan(v) else v

    def vec3(self) -> tuple[float, float, float]:
        return (self.f32(), self.f32(), self.f32())

    def count(self, min_item_size: int = 1) -> int:
        """An i32 element count, rejected if it cannot fit in the remaining bytes."""
        at = self.offset
        n = self.i32()
        if n < 0 or n * max(min_item_size, 1) > self.remaining:
            raise self.error(f"implausible count {n}", at)
        return n

    def bytes_(self) -> bytes:
        """ZPackage byte array: i32 length + raw bytes."""
        return self.raw(self.count())

    def string(self) -> str:
        """.NET BinaryWriter string: 7-bit varint byte length + UTF-8."""
        at = self.offset
        n = shift = 0
        for _ in range(5):
            b = self.u8()
            n |= (b & 0x7F) << shift
            shift += 7
            if b < 0x80:
                break
        else:
            raise self.error("string length varint longer than 5 bytes", at)
        if self.offset - at != len(encode_7bit(n)):
            raise self.error("non-canonical string length", at)
        data = self.raw(n)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise self.error(f"invalid UTF-8 in string: {e.reason}", at) from None

    def num_items(self) -> int:
        """ZPackage.ReadNumItems: 1 byte below 128, else 2 bytes with the high bit set."""
        at = self.offset
        n = self.u8()
        if n & 0x80:
            n = ((n & 0x7F) << 8) | self.u8()
            if n < 0x80:
                raise self.error("non-canonical item count", at)
        return n
