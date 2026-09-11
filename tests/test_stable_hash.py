import pytest

from fch_editor.stable_hash import stable_hash

# Prefab hashes as stored (little-endian i32) in the sample save's inventory.
SAMPLE_VECTORS = {
    "Torch": "18f8662f",
    "ArmorRagsChest": "8d385090",
    "Raspberry": "3c1b2b58",
    "Mushroom": "c8cf0f8b",
    "AxeStone": "eff3f495",
    "Hammer": "cc2ef80b",
    "NeckTail": "b3879eac",
    "Hoe": "9ada8f59",
    "Wood": "c324f3f6",
    "Club": "aa886f31",
    "Stone": "576e14e0",
    "Feathers": "02342595",
    "ArrowWood": "0a2f62d1",
    "LeatherScraps": "c324d958",
    "ArmorRagsLegs": "bd3c4b94",
    "Bow": "62d98f59",
    "RawMeat": "79e04ad8",
}


@pytest.mark.parametrize("name,le_hex", SAMPLE_VECTORS.items())
def test_matches_hashes_in_sample_save(name, le_hex):
    assert stable_hash(name) == int.from_bytes(bytes.fromhex(le_hex), "little", signed=True)


def test_result_is_signed_32_bit():
    for name in SAMPLE_VECTORS:
        assert -(2**31) <= stable_hash(name) < 2**31


def test_empty_and_nul_terminated():
    # Loop never runs: result is 5381 + 5381 * 1566083941 with int32 wrap-around.
    assert stable_hash("") == (5381 + 5381 * 1566083941 + 2**31) % 2**32 - 2**31
    # C# stops hashing at the first NUL character.
    assert stable_hash("Wood\0junk") == stable_hash("Wood")
