import copy

import pytest

from fch_editor import model
from fch_editor.catalog.enums import STAT_NAMES, skill_name
from fch_editor.catalog.items import ItemCatalog, hash_hex
from fch_editor.diffing import diff, flatten
from fch_editor.load import load_bytes
from fch_editor.reader import RawF32
from fch_editor.stable_hash import stable_hash


def test_bundled_catalog_resolves_sample_items(sample_bytes):
    catalog = ItemCatalog.load()
    items = load_bytes(sample_bytes).profile.player.items
    assert all(catalog.name(i.prefab_hash) for i in items)
    assert "Wood" in catalog and "NotARealItem" not in catalog


def test_unknown_hash_label_and_extra_file(tmp_path):
    h = stable_hash("BrandNewItem")
    assert ItemCatalog.load().label(h) == f"#{hash_hex(h)}"
    extra = tmp_path / "more.txt"
    extra.write_text("# comment\nBrandNewItem\n", encoding="utf-8")
    assert ItemCatalog.load([extra]).label(h) == "BrandNewItem"


def test_enum_tables():
    assert len(STAT_NAMES) == 205 and STAT_NAMES[0] == "Deaths"
    assert skill_name(107) == "Crafting" and skill_name(999) == "Skill#999"


def test_identical_profiles_have_no_diff(sample_bytes):
    p = load_bytes(sample_bytes).profile
    assert diff(p, copy.deepcopy(p)) == []


def test_diff_reports_exact_paths(sample_bytes):
    a = load_bytes(sample_bytes).profile
    b = copy.deepcopy(a)
    b.player.skills[0].level = 50.0          # Run
    b.player.items[0].stack = 3              # item at (0,0)
    b.stat_blocks[0].stats[0] = 99.0         # Deaths, RawStats scope
    b.stat_blocks[0].enemy_stats[0].append(("$enemy_troll", 1.0))
    paths = [p for p, _, _ in diff(a, b)]
    assert paths == sorted([
        "player.items[(0,0)].stack",
        "player.skills[Run].level",
        "stats.RawStats.enemy_stats[0].count",
        "stats.RawStats.enemy_stats[0]['$enemy_troll']",
        "stats.RawStats.stats[Deaths]",
    ])


def test_diff_catches_item_added_and_blob_change(sample_bytes):
    a = load_bytes(sample_bytes).profile
    b = copy.deepcopy(a)
    b.player.items.append(model.Item(10000, 7, 2, 0, model.HAS_PREFAB | model.PICKED_UP,
                                     prefab_hash=stable_hash("Coins")))
    b.player.build_ui_state = b""
    paths = {p for p, _, _ in diff(a, b)}
    assert "player.items.count" in paths and "player.items[(7,2)].prefab_hash" in paths
    assert "player.build_ui_state" in paths


def test_nan_compared_by_bits(sample_bytes):
    a = load_bytes(sample_bytes).profile
    b = copy.deepcopy(a)
    a.player.health = RawF32(b"\x01\x00\xc0\x7f")
    b.player.health = RawF32(b"\x01\x00\xc0\x7f")
    assert diff(a, b) == []
    b.player.health = RawF32(b"\x02\x00\xc0\x7f")
    assert [p for p, _, _ in diff(a, b)] == ["player.health"]


def test_nan_profile_survives_deepcopy(sample_bytes):
    a = load_bytes(sample_bytes).profile
    a.player.health = RawF32(b"\x01\x00\xc0\x7f")
    b = copy.deepcopy(a)
    assert b.player.health.raw == b"\x01\x00\xc0\x7f"
    assert diff(a, b) == []


def test_floats_compared_as_stored_f32(sample_bytes):
    a = load_bytes(sample_bytes).profile
    b = copy.deepcopy(a)
    b.player.eitr = -0.0  # sample stores +0.0; the written bytes differ
    assert [p for p, _, _ in diff(a, b)] == ["player.eitr"]
    a.player.eitr, b.player.eitr = 0.1, 0.10000000149011612  # same f32
    assert diff(a, b) == []


def test_duplicate_world_uids_do_not_mask_changes(sample_bytes):
    a = load_bytes(sample_bytes).profile
    a.worlds[1].uid = a.worlds[0].uid
    b = copy.deepcopy(a)
    b.worlds[0].home_point = (1.0, 2.0, 3.0)
    assert [p for p, _, _ in diff(a, b)] == [f"worlds[{a.worlds[0].uid}].home_point"]


def test_string_lists_keyed_by_value(sample_bytes):
    a = load_bytes(sample_bytes).profile
    b = copy.deepcopy(a)
    b.player.known_recipes.insert(0, "$item_new_recipe")
    assert [p for p, _, _ in diff(a, b)] == [
        "player.known_recipes.count", "player.known_recipes['$item_new_recipe']"]


@pytest.mark.parametrize("text", ["f32<zzzzzzzz>", "f32<0000803f>"])
def test_text_resembling_float_tokens_is_shown_as_text(sample_bytes, text):
    from fch_editor.render import diff_text
    a = load_bytes(sample_bytes).profile
    b = copy.deepcopy(a)
    b.name = text
    assert diff_text(diff(a, b)) == f"name: 'Lorce' -> {text!r}"


def test_diff_text_collapses_whole_record_add_and_remove(sample_bytes):
    import copy as _copy

    from fch_editor import model
    from fch_editor.render import diff_text
    from fch_editor.stable_hash import stable_hash

    a = load_bytes(sample_bytes).profile
    b = _copy.deepcopy(a)
    b.player.items.append(model.Item(10000, 7, 0, 0, model.HAS_PREFAB | model.PICKED_UP,
                                     prefab_hash=stable_hash("Coins")))
    text = diff_text(diff(a, b))
    assert "player.items[(7,0)]: added" in text
    assert "player.items[(7,0)].prefab_hash" not in text  # not spelled out per field

    c = _copy.deepcopy(a)
    c.player.items = [i for i in c.player.items if (i.x, i.y) != (0, 0)]
    text = diff_text(diff(a, c))
    assert "player.items[(0,0)]: removed" in text
    assert "player.items[(0,0)].durability_x100" not in text


def test_diff_text_collapses_records_with_a_nested_bracket_field(sample_bytes):
    # custom_data['key'] has its own bracket; the record key must still be the item's,
    # not a second, larger key ending at that inner bracket.
    import copy as _copy

    from fch_editor import model
    from fch_editor.render import diff_text
    from fch_editor.stable_hash import stable_hash

    a = load_bytes(sample_bytes).profile
    b = _copy.deepcopy(a)
    b.player.items.append(model.Item(
        10000, 7, 0, 0, model.HAS_PREFAB | model.HAS_CUSTOM_DATA | model.PICKED_UP,
        prefab_hash=stable_hash("Coins"), custom_data=[("origin", "quest")],
    ))
    text = diff_text(diff(a, b))
    lines = text.splitlines()
    assert lines.count("player.items[(7,0)]: added") == 1
    assert not any("custom_data" in line for line in lines)  # folded into the single "added" line


def test_diff_text_does_not_collapse_a_partial_edit(sample_bytes):
    import copy as _copy
    from fch_editor.render import diff_text

    a = load_bytes(sample_bytes).profile
    b = _copy.deepcopy(a)
    b.player.items[0].stack = 5
    b.player.items[0].durability_x100 = 500
    text = diff_text(diff(a, b))
    assert "removed" not in text and "added" not in text
    assert ".stack: " in text and ".durability_x100: " in text


def test_f32_text_is_shortest_and_unambiguous():
    import struct
    from fch_editor.render import f32_text
    assert f32_text(0.800000011920929) == "0.8" and f32_text(50.0) == "50.0"
    assert f32_text(12345678.0) == "12345678.0"  # no exponent/rounding for large integers
    a = struct.unpack("<f", bytes.fromhex("5a9b473d"))[0]  # 0.04881338...
    b = struct.unpack("<f", bytes.fromhex("5b9b473d"))[0]  # next f32 up
    assert f32_text(a) != f32_text(b)
    for v in (a, b):
        assert struct.pack("<f", float(f32_text(v))) == struct.pack("<f", v)


def test_every_model_field_appears_in_flatten(sample_bytes):
    from dataclasses import fields
    p = load_bytes(sample_bytes).profile
    p.player.foods = [model.Food("Honey", 1.0)]
    paths = " ".join(flatten(p))
    internal = {"player_raw", "player_error", "stat_blocks", "worlds", "player"}
    for dc in (model.Profile, model.PlayerData, model.StatBlock, model.WorldData, model.Item,
               model.Skill, model.Food):
        for f in fields(dc):
            if f.name not in internal:
                assert f".{f.name}" in paths or paths.startswith(f.name) or f" {f.name}" in paths, \
                    f"{dc.__name__}.{f.name} missing from flatten()"


def test_flatten_covers_every_world_and_item(sample_bytes):
    flat = flatten(load_bytes(sample_bytes).profile)
    assert flat["player.items.count"] == 19 and flat["worlds.count"] == 2
    assert flat["player.skills[Crafting].level"] == 1000.0
