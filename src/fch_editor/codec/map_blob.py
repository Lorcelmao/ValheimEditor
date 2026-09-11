"""Minimap blob, map version 8 (spec §7).

Profiles keep these blobs raw: re-compressing with a different gzip encoder
yields different (still valid) bytes, so a map is only rebuilt when edited.
Inflation is capped to guard against decompression bombs in crafted files.
"""
import gzip
import zlib

from .. import versions
from ..errors import FormatError, UnsupportedVersion
from ..model import MapData, Pin
from ..reader import Reader
from ..writer import Writer

MAX_INFLATED = 64 * 1024 * 1024  # a 2048² map inflates to ~8.4 MB
_MIN_PIN_SIZE = 27  # empty name + vec3 + type + checked + ownerId + empty author


def map_version(raw: bytes) -> int | None:
    return int.from_bytes(raw[:4], "little", signed=True) if len(raw) >= 4 else None


def _gunzip(data: bytes) -> bytes:
    d = zlib.decompressobj(wbits=31)  # gzip container
    try:
        out = d.decompress(data, MAX_INFLATED + 1)
    except zlib.error as e:
        raise FormatError(f"map data is not valid gzip: {e}") from None
    if len(out) > MAX_INFLATED:
        raise FormatError(f"map data inflates beyond {MAX_INFLATED} bytes")
    if not d.eof:
        raise FormatError("map gzip stream is truncated")
    if d.unused_data:
        raise FormatError(f"{len(d.unused_data)} unexpected bytes after the map gzip stream")
    return out


def decode_map_inner(inner: bytes, version: int = versions.MAP) -> MapData:
    r = Reader(inner)
    with r.scope("map"):
        at = r.offset
        size = r.i32()
        if size <= 0 or 2 * size * size > r.remaining:
            raise r.error(f"implausible texture size {size}", at)
        explored = r.raw(size * size)
        explored_shared = r.raw(size * size)
        pins = [Pin(r.string(), r.vec3(), r.i32(), r.bool(), r.i64(), r.string())
                for _ in range(r.count(_MIN_PIN_SIZE))]
        public_position = r.bool()
        if not r.at_end():
            raise r.error(f"{r.remaining} unexpected bytes after map data")
    return MapData(version, size, explored, explored_shared, pins, public_position)


def encode_map_inner(m: MapData) -> bytes:
    if len(m.explored) != m.texture_size ** 2 or len(m.explored_shared) != m.texture_size ** 2:
        raise ValueError("explored arrays must be texture_size² bytes")
    w = Writer()
    w.i32(m.texture_size)
    w.raw(m.explored)
    w.raw(m.explored_shared)
    w.i32(len(m.pins))
    for p in m.pins:
        w.string(p.name)
        w.vec3(p.pos)
        w.i32(p.type)
        w.bool(p.checked)
        w.i64(p.owner_id)
        w.string(p.author)
    w.bool(m.public_position)
    return w.to_bytes()


def split_map(raw: bytes) -> tuple[int, bytes]:
    """Return (map version, inflated inner bytes) of a raw map blob."""
    r = Reader(raw)
    version = r.i32()
    if version != versions.MAP:
        raise UnsupportedVersion(f"map version {version}, supported {versions.MAP}")
    compressed = r.bytes_()
    if not r.at_end():
        raise r.error("unexpected bytes after compressed map data")
    return version, _gunzip(compressed)


def decode_map(raw: bytes) -> MapData:
    version, inner = split_map(raw)
    return decode_map_inner(inner, version)


def encode_map(m: MapData) -> bytes:
    w = Writer()
    w.i32(m.version)
    w.bytes_(gzip.compress(encode_map_inner(m), compresslevel=1, mtime=0))
    return w.to_bytes()
