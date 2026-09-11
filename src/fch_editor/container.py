"""Outer .fch envelope: i32 length | payload | i32 64 | SHA-512(payload).

The game ignores the hash on load, so a mismatch is reported, not fatal. Any
structural deviation (bad lengths, trailing bytes) is a FormatError because the
editor could not reproduce such a file faithfully.
"""
import hashlib
import struct
from dataclasses import dataclass

from .errors import FormatError

HASH_LENGTH = 64


@dataclass(frozen=True)
class Envelope:
    payload: bytes
    stored_hash: bytes

    @property
    def hash_ok(self) -> bool:
        return hashlib.sha512(self.payload).digest() == self.stored_hash


def unpack(data: bytes) -> Envelope:
    data = bytes(data)
    if len(data) < 8:
        raise FormatError("file too short for an .fch envelope", 0)
    (payload_len,) = struct.unpack_from("<i", data, 0)
    if payload_len < 0 or 4 + payload_len + 4 > len(data):
        raise FormatError(f"payload length {payload_len} exceeds file size {len(data)}", 0)
    hash_at = 4 + payload_len
    (hash_len,) = struct.unpack_from("<i", data, hash_at)
    if hash_len != HASH_LENGTH:
        raise FormatError(f"hash length {hash_len}, expected {HASH_LENGTH}", hash_at)
    end = hash_at + 4 + HASH_LENGTH
    if end != len(data):
        raise FormatError(f"file is {len(data)} bytes, envelope describes {end}", min(end, len(data)))
    return Envelope(payload=data[4:hash_at], stored_hash=data[hash_at + 4:end])


def pack(payload: bytes) -> bytes:
    digest = hashlib.sha512(payload).digest()
    return struct.pack("<i", len(payload)) + payload + struct.pack("<i", len(digest)) + digest
