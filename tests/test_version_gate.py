"""Malformed or unsupported saves must open read-only (or fail cleanly), never crash."""
import copy
import random
import struct

import pytest

from fch_editor import container
from fch_editor.codec.profile import encode_profile
from fch_editor.errors import FchError
from fch_editor.load import encode_save, load_bytes


def _payload(sample_bytes: bytes) -> bytearray:
    return bytearray(container.unpack(sample_bytes).payload)


def test_unsupported_profile_version_is_read_only(sample_bytes):
    payload = _payload(sample_bytes)
    struct.pack_into("<i", payload, 0, 47)
    save = load_bytes(container.pack(bytes(payload)))
    assert not save.writable and save.profile is None
    assert "profile version 47" in save.reasons[0]


def test_unsupported_player_version_keeps_profile_readable(sample_bytes):
    save = load_bytes(sample_bytes)
    raw = bytearray(save.profile.player_raw)
    struct.pack_into("<i", raw, 0, 34)
    save.profile.player, save.profile.player_raw = None, bytes(raw)
    reloaded = load_bytes(container.pack(encode_profile(save.profile)))
    assert not reloaded.writable
    assert reloaded.profile.name == "Lorce" and reloaded.profile.player is None
    assert "player data version 34" in reloaded.reasons[0]


def test_bad_bool_byte_is_read_only(sample_bytes):
    save = load_bytes(sample_bytes)
    payload = _payload(sample_bytes)
    # Everything from the firstSpawn bool onward = a re-encode without stat blocks,
    # minus the 12-byte header (version, stat count, block count).
    no_stats = copy.deepcopy(save.profile)
    no_stats.stat_blocks = []
    first_spawn_at = len(payload) - len(encode_profile(no_stats)[12:])
    assert payload[first_spawn_at] in (0, 1)
    payload[first_spawn_at] = 2
    bad = load_bytes(container.pack(bytes(payload)))
    assert not bad.writable and "bool" in bad.reasons[0]


def test_hash_mismatch_is_a_warning_not_a_blocker(sample_bytes):
    data = bytearray(sample_bytes)
    data[-1] ^= 0xFF
    save = load_bytes(bytes(data))
    assert save.writable and not save.hash_ok
    assert encode_save(save.profile) == sample_bytes  # hash is recomputed on write


@pytest.mark.parametrize("seed", range(3))
def test_truncated_and_corrupted_payloads_never_crash(sample_bytes, seed):
    rng = random.Random(seed)
    payload = bytes(_payload(sample_bytes))
    cases = [payload[:rng.randrange(len(payload))] for _ in range(40)]
    for _ in range(40):
        mutated = bytearray(payload)
        for _ in range(rng.randint(1, 4)):
            mutated[rng.randrange(len(mutated))] = rng.randrange(256)
        cases.append(bytes(mutated))
    for case in cases:
        try:
            save = load_bytes(container.pack(case))
        except FchError:
            continue
        if save.writable:
            assert encode_save(save.profile) == container.pack(case)


def test_trailing_garbage_is_read_only(sample_bytes):
    save = load_bytes(container.pack(bytes(_payload(sample_bytes)) + b"\x00"))
    assert not save.writable and "unexpected bytes" in save.reasons[0]
