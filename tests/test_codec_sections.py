"""Synthetic records for layouts the sample save does not exercise
(foods, custom data, item quality/variant/custom data), built from the spec."""
import copy

import pytest

from fch_editor import model
from fch_editor.codec.inventory import decode_item, encode_item
from fch_editor.codec.player import decode_player, encode_player
from fch_editor.load import encode_save, load_bytes
from fch_editor.reader import Reader
from fch_editor.writer import Writer


def _item_bytes(item: model.Item) -> bytes:
    w = Writer()
    encode_item(w, item)
    return w.to_bytes()


def test_item_with_every_optional_field_roundtrips():
    item = model.Item(
        durability_x100=12345, x=7, y=3, world_level=2, flags=0xFF, quality=4, stack=300,
        variant=2, crafter_id=-5, crafter_name="Lörce", prefab_hash=-123456,
        custom_data=[("k1", "v1"), ("key two", "värde")], extra_flags=0x01,
    )
    data = _item_bytes(item)
    r = Reader(data)
    assert decode_item(r) == item and r.at_end()


def test_item_minimal_layout_is_nine_bytes():
    item = model.Item(durability_x100=100, x=0, y=0, world_level=0, flags=0)
    assert len(_item_bytes(item)) == 9


def test_custom_data_without_flag_is_rejected():
    item = model.Item(durability_x100=0, x=0, y=0, world_level=0, flags=model.HAS_PREFAB,
                      prefab_hash=1, custom_data=[("k", "v")])
    with pytest.raises(ValueError):
        _item_bytes(item)


@pytest.mark.parametrize("field,value", [
    ("quality", 2), ("stack", 20), ("variant", 1), ("crafter_id", 5), ("crafter_name", "x"), ("prefab_hash", 9),
])
def test_value_without_its_flag_bit_is_rejected(field, value):
    # Writing it would silently drop the value from the file.
    item = model.Item(durability_x100=0, x=0, y=0, world_level=0, flags=0)
    setattr(item, field, value)
    with pytest.raises(ValueError, match=field.split("_")[0]):
        _item_bytes(item)


def test_unknown_extra_flag_bits_preserved():
    item = model.Item(durability_x100=0, x=1, y=1, world_level=0, flags=model.HAS_PREFAB,
                      prefab_hash=7, extra_flags=0xFE)
    assert decode_item(Reader(_item_bytes(item))).extra_flags == 0xFE


def test_player_with_foods_and_custom_data_roundtrips(sample_bytes):
    save = load_bytes(sample_bytes)
    player = copy.deepcopy(save.profile.player)
    player.foods = [model.Food("CookedMeat", 1200.5), model.Food("Honey", 30.0)]
    player.custom_data = [("SomeKey", "SomeValue")]
    player.items[0].flags |= model.HAS_QUALITY | model.HAS_VARIANT
    player.items[0].quality, player.items[0].variant = 3, 1
    data = encode_player(player)
    assert decode_player(data) == player
    assert encode_player(decode_player(data)) == data


def test_code_only_features_are_reported(sample_bytes):
    save = load_bytes(sample_bytes)
    assert not any("confirmed from game code" in w for w in save.warnings)
    edited = copy.deepcopy(save.profile)
    edited.player.foods = [model.Food("Honey", 30.0)]
    again = load_bytes(encode_save(edited))
    assert again.writable
    assert any("active foods" in w for w in again.warnings)
