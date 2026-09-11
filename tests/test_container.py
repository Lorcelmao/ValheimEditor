import struct

import pytest

from fch_editor import container
from fch_editor.errors import FormatError


def test_sample_roundtrips_and_hash_verifies(sample_bytes):
    env = container.unpack(sample_bytes)
    assert env.hash_ok
    assert container.pack(env.payload) == sample_bytes


def test_payload_bit_flip_detected(sample_bytes):
    flipped = bytearray(sample_bytes)
    flipped[100] ^= 0x01
    env = container.unpack(bytes(flipped))
    assert not env.hash_ok


def test_pack_unpack_synthetic():
    data = container.pack(b"hello")
    env = container.unpack(data)
    assert env.payload == b"hello" and env.hash_ok


def test_truncated_file_rejected():
    data = container.pack(b"hello")
    with pytest.raises(FormatError):
        container.unpack(data[:-1])
    with pytest.raises(FormatError):
        container.unpack(data[:6])


def test_trailing_bytes_rejected():
    with pytest.raises(FormatError, match="envelope describes"):
        container.unpack(container.pack(b"hello") + b"\x00")


def test_wrong_hash_length_rejected():
    payload = b"hello"
    data = struct.pack("<i", len(payload)) + payload + struct.pack("<i", 32) + bytes(32)
    with pytest.raises(FormatError, match="hash length"):
        container.unpack(data)


def test_negative_payload_length_rejected():
    with pytest.raises(FormatError):
        container.unpack(struct.pack("<i", -5) + bytes(70))
