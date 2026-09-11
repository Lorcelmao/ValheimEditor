"""Little-endian encoding matching the game's ZPackage / BinaryWriter, the inverse of reader.py.

Out-of-range values raise ValueError: they are programming or input-validation
errors, never something to silently truncate into a save.
"""
import struct

from .reader import F32, I32, I64, U16, RawF32, encode_7bit


class Writer:
    def __init__(self):
        self._buf = bytearray()

    def to_bytes(self) -> bytes:
        return bytes(self._buf)

    def raw(self, data: bytes) -> None:
        self._buf += data

    def _pack(self, s: struct.Struct, v, name: str) -> None:
        try:
            self._buf += s.pack(v)
        except (struct.error, OverflowError) as e:
            raise ValueError(f"{name} value {v!r} out of range: {e}") from None

    def u8(self, v: int) -> None:
        if not 0 <= v <= 0xFF:
            raise ValueError(f"u8 value {v!r} out of range")
        self._buf.append(v)

    def bool(self, v: bool) -> None:
        self._buf.append(1 if v else 0)

    def u16(self, v: int) -> None:
        self._pack(U16, v, "u16")

    def i32(self, v: int) -> None:
        self._pack(I32, v, "i32")

    def i64(self, v: int) -> None:
        self._pack(I64, v, "i64")

    def f32(self, v: float) -> None:
        if isinstance(v, RawF32):
            self._buf += v.raw
        else:
            self._pack(F32, v, "f32")

    def vec3(self, v: tuple[float, float, float]) -> None:
        for c in v:
            self.f32(c)

    def bytes_(self, data: bytes) -> None:
        self.i32(len(data))
        self._buf += data

    def string(self, s: str) -> None:
        try:
            data = s.encode("utf-8")
        except UnicodeEncodeError as e:
            raise ValueError(f"string is not valid Unicode text: {e.reason}") from None
        self._buf += encode_7bit(len(data))
        self._buf += data

    def num_items(self, n: int) -> None:
        if not 0 <= n <= 0x7FFF:
            raise ValueError(f"item count {n} out of range 0..32767")
        if n < 0x80:
            self._buf.append(n)
        else:
            self._buf += bytes(((n >> 8) | 0x80, n & 0xFF))
