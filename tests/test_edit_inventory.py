import pytest

from fch_editor import model, safe_io
from fch_editor.cli import main
from fch_editor.edits import inventory as inv
from fch_editor.edits.pipeline import apply_edits
from fch_editor.errors import EditError
from fch_editor.load import load_bytes, load_file
from fch_editor.stable_hash import stable_hash

WOOD = stable_hash("Wood")


@pytest.fixture
def save(sample_bytes):
    return load_bytes(sample_bytes)


def _items(profile):
    return {(i.x, i.y): i for i in profile.player.items}


def test_grid_size_reads_invrows(save):
    assert inv.grid_size(save.profile.player) == (8, 4)  # sample has "invrows 4"


def test_parse_slot():
    assert inv.parse_slot("3,0") == (3, 0)
    for bad in ("3", "3,0,1", "x,0", ""):
        with pytest.raises(EditError):
            inv.parse_slot(bad)


class TestSetItemField:
    def test_changes_only_that_item(self, save):
        # (4,2) already has a non-1 stack, so its HAS_STACK flag bit stays set: only .stack changes.
        result = apply_edits(save, [inv.SetItemField((4, 2), stack=50)])
        assert [p for p, _, _ in result.changes] == ["player.items[(4,2)].stack"]
        after = _items(load_bytes(result.data).profile)
        assert after[(4, 2)].stack == 50

    def test_stack_of_one_clears_the_flag(self, save):
        result = apply_edits(save, [inv.SetItemField((4, 2), stack=1)])
        item = _items(load_bytes(result.data).profile)[(4, 2)]
        assert item.stack == 1 and not item.flags & 0x08

    def test_durability_rounds_to_x100(self, save):
        result = apply_edits(save, [inv.SetItemField((0, 0), durability=42.375)])
        assert _items(load_bytes(result.data).profile)[(0, 0)].durability_x100 == 4238

    def test_both_fields_at_once(self, save):
        result = apply_edits(save, [inv.SetItemField((4, 2), stack=7, durability=50.0)])
        item = _items(load_bytes(result.data).profile)[(4, 2)]
        assert (item.stack, item.durability_x100) == (7, 5000)

    def test_missing_slot_rejected(self, save):
        with pytest.raises(EditError, match="no item at slot"):
            apply_edits(save, [inv.SetItemField((7, 7), stack=5)])

    @pytest.mark.parametrize("stack", [0, -1, 65536])
    def test_stack_out_of_range(self, stack):
        with pytest.raises(EditError):
            inv.SetItemField((0, 0), stack=stack)

    def test_negative_durability_rejected(self):
        with pytest.raises(EditError):
            inv.SetItemField((0, 0), durability=-1)

    def test_requires_a_field(self):
        with pytest.raises(EditError, match="at least one"):
            inv.SetItemField((0, 0))


class TestRemoveItem:
    def test_removes_only_that_item(self, save):
        before = len(save.profile.player.items)
        result = apply_edits(save, [inv.RemoveItem((2, 3))])
        out = load_bytes(result.data).profile
        assert len(out.player.items) == before - 1 and (2, 3) not in _items(out)
        assert {k: v.stack for k, v in _items(out).items()} == \
            {k: v.stack for k, v in _items(save.profile).items() if k != (2, 3)}

    def test_missing_slot_rejected(self, save):
        with pytest.raises(EditError, match="no item at slot"):
            apply_edits(save, [inv.RemoveItem((7, 7))])


class TestCopyItem:
    def test_copies_prefab_stack_and_durability(self, save):
        source = _items(save.profile)[(4, 2)]  # a real item with a non-1 stack in the sample
        result = apply_edits(save, [inv.CopyItem((4, 2))])
        out = load_bytes(result.data).profile
        new = [i for (x, y), i in _items(out).items() if (x, y) not in _items(save.profile)]
        assert len(new) == 1
        copy = new[0]
        assert copy.prefab_hash == source.prefab_hash
        assert copy.stack == source.stack
        assert copy.durability_x100 == source.durability_x100

    def test_quality_survives_the_copy_and_a_decode_round_trip(self, save):
        # The headline case: AddItem alone would silently reset this to 1.
        profile = save.profile
        item = _items(profile)[(4, 2)]
        item.quality = 3
        item.flags |= model.HAS_QUALITY
        result = apply_edits(save, [inv.CopyItem((4, 2))])
        out = load_bytes(result.data).profile  # re-decoded, not the in-memory object
        new = [i for (x, y), i in _items(out).items() if (x, y) not in _items(save.profile)]
        assert len(new) == 1
        assert new[0].quality == 3
        assert new[0].flags & model.HAS_QUALITY

    def test_variant_custom_data_world_level_and_extra_flags_survive(self, save):
        profile = save.profile
        item = _items(profile)[(4, 2)]
        item.variant = 2
        item.flags |= model.HAS_VARIANT
        item.custom_data = [("origin", "quest")]
        item.flags |= model.HAS_CUSTOM_DATA
        item.world_level = 5
        item.extra_flags = 0x12  # u8-encoded; not 0x1234, which overflows the field
        result = apply_edits(save, [inv.CopyItem((4, 2))])
        out = load_bytes(result.data).profile
        new = [i for (x, y), i in _items(out).items() if (x, y) not in _items(save.profile)]
        assert len(new) == 1
        copy = new[0]
        assert copy.variant == 2 and copy.flags & model.HAS_VARIANT
        assert copy.custom_data == [("origin", "quest")] and copy.flags & model.HAS_CUSTOM_DATA
        assert copy.world_level == 5
        assert copy.extra_flags == 0x12

    def test_crafter_of_the_original_survives_not_the_current_character(self, save):
        profile = save.profile
        item = _items(profile)[(4, 2)]
        item.crafter_id = 999999
        item.crafter_name = "SomeoneElse"
        item.flags |= model.HAS_CRAFTER
        result = apply_edits(save, [inv.CopyItem((4, 2))])
        out = load_bytes(result.data).profile
        new = [i for (x, y), i in _items(out).items() if (x, y) not in _items(save.profile)]
        assert new[0].crafter_id == 999999 and new[0].crafter_name == "SomeoneElse"

    def test_copy_of_an_equipped_item_is_not_equipped(self, save):
        profile = save.profile
        item = _items(profile)[(0, 3)]  # ArmorRagsChest, equipped in the sample
        assert item.flags & model.EQUIPPED
        result = apply_edits(save, [inv.CopyItem((0, 3))])
        out = load_bytes(result.data).profile
        source_after = _items(out)[(0, 3)]
        new = [i for (x, y), i in _items(out).items() if (x, y) not in _items(save.profile)]
        assert len(new) == 1
        assert not new[0].flags & model.EQUIPPED
        assert source_after.flags & model.EQUIPPED  # the original is untouched

    def test_source_is_not_mutated_by_a_later_change_to_the_copy(self, save):
        # Proves deepcopy, not aliasing: custom_data is a list, so a shallow
        # copy would let mutating the new item's list also mutate the source's.
        profile = save.profile
        item = _items(profile)[(4, 2)]
        item.custom_data = [("k", "v")]
        item.flags |= model.HAS_CUSTOM_DATA
        result = apply_edits(save, [inv.CopyItem((4, 2))])
        out = load_bytes(result.data).profile
        new = [i for (x, y), i in _items(out).items() if (x, y) not in _items(save.profile)][0]
        new.custom_data.append(("k2", "v2"))
        assert _items(out)[(4, 2)].custom_data == [("k", "v")]

    def test_lands_in_the_first_free_slot(self, save):
        result = apply_edits(save, [inv.CopyItem((4, 2))])
        new = [(x, y) for (x, y) in _items(load_bytes(result.data).profile) if (x, y) not in _items(save.profile)]
        assert new == [(7, 0)]  # first empty slot in row-major order, same as AddItem's default

    def test_missing_slot_rejected(self, save):
        with pytest.raises(EditError, match="no item at slot"):
            apply_edits(save, [inv.CopyItem((7, 7))])

    def test_full_inventory_rejected(self, save):
        edits = []
        occupied = {(i.x, i.y) for i in save.profile.player.items}
        for y in range(4):
            for x in range(8):
                if (x, y) not in occupied:
                    edits.append(inv.AddItem("Wood", WOOD, slot=(x, y)))
        result = apply_edits(save, edits)
        with pytest.raises(EditError, match="full"):
            apply_edits(load_bytes(result.data), [inv.CopyItem((4, 2))])

    def test_shared_slot_source_is_refused_not_guessed(self, save):
        profile = save.profile
        extra = model.Item(9999, 4, 2, 0, model.HAS_PREFAB, prefab_hash=WOOD)
        profile.player.items.append(extra)
        with pytest.raises(EditError, match="2 items occupy slot 4,2"):
            inv.CopyItem((4, 2)).apply(profile)

    def test_two_copies_in_a_row_produce_two_items(self, save):
        result = apply_edits(save, [inv.CopyItem((4, 2)), inv.CopyItem((4, 2))])
        new = [(x, y) for (x, y) in _items(load_bytes(result.data).profile) if (x, y) not in _items(save.profile)]
        assert len(new) == 2

    def test_never_deduped_against_itself(self):
        from fch_editor.edits.dedup import edit_key
        assert edit_key(inv.CopyItem((4, 2))) is None


class TestAddItem:
    def test_first_free_slot_row_major(self, save):
        result = apply_edits(save, [inv.AddItem("Wood", WOOD)])
        new = [i for i in load_bytes(result.data).profile.player.items if (i.x, i.y) not in _items(save.profile)]
        assert len(new) == 1 and (new[0].x, new[0].y) == (7, 0)  # first empty slot in row-major order

    def test_explicit_slot(self, save):
        result = apply_edits(save, [inv.AddItem("Wood", WOOD, slot=(7, 3 - 1))])
        assert (7, 2) in _items(load_bytes(result.data).profile)

    def test_sets_prefab_and_stack_flags(self, save):
        result = apply_edits(save, [inv.AddItem("Wood", WOOD, stack=42)])
        item = load_bytes(result.data).profile.player.items[-1]
        assert item.prefab_hash == WOOD and item.stack == 42
        assert item.flags & 0x40 and item.flags & 0x08  # HAS_PREFAB, HAS_STACK

    def test_default_stack_has_no_stack_flag(self, save):
        result = apply_edits(save, [inv.AddItem("Wood", WOOD)])
        item = load_bytes(result.data).profile.player.items[-1]
        assert item.stack == 1 and not item.flags & 0x08

    def test_crafted_by_me_uses_the_character(self, save):
        result = apply_edits(save, [inv.AddItem("Wood", WOOD, crafted_by_me=True)])
        item = load_bytes(result.data).profile.player.items[-1]
        assert item.crafter_id == save.profile.player_id and item.crafter_name == save.profile.name
        assert item.flags & 0x20  # HAS_CRAFTER

    def test_occupied_slot_rejected(self, save):
        with pytest.raises(EditError, match="already occupied"):
            apply_edits(save, [inv.AddItem("Wood", WOOD, slot=(0, 0))])

    def test_out_of_bounds_slot_rejected(self, save):
        with pytest.raises(EditError, match="outside"):
            apply_edits(save, [inv.AddItem("Wood", WOOD, slot=(8, 0))])
        with pytest.raises(EditError):
            inv.AddItem("Wood", WOOD, slot=(-1, 0))

    def test_full_inventory_rejected(self, save):
        # Fill every remaining slot, then one more must fail.
        edits = []
        occupied = {(i.x, i.y) for i in save.profile.player.items}
        for y in range(4):
            for x in range(8):
                if (x, y) not in occupied:
                    edits.append(inv.AddItem("Wood", WOOD, slot=(x, y)))
        result = apply_edits(save, edits)
        with pytest.raises(EditError, match="full"):
            apply_edits(load_bytes(result.data), [inv.AddItem("Wood", WOOD)])

    @pytest.mark.parametrize("stack", [0, 65536])
    def test_stack_out_of_range(self, stack):
        with pytest.raises(EditError):
            inv.AddItem("Wood", WOOD, stack=stack)


def test_duplicate_slot_is_refused_not_guessed(save):
    # A save that already has two items sharing a slot is inconsistent; simulate it directly
    # (this state cannot arise from AddItem's own collision check).
    profile = save.profile
    extra = model.Item(9999, 4, 2, 0, model.HAS_PREFAB, prefab_hash=WOOD)
    profile.player.items.append(extra)
    for edit in (inv.SetItemField((4, 2), stack=5), inv.RemoveItem((4, 2))):
        with pytest.raises(EditError, match="2 items occupy slot 4,2"):
            edit.apply(profile)


def test_unknown_hash_items_survive_other_edits(save):
    # Slots aside from the touched one, including any unknown-hash items, must be untouched.
    result = apply_edits(save, [inv.SetItemField((4, 2), stack=99)])
    a, b = _items(save.profile), _items(load_bytes(result.data).profile)
    for slot in set(a) - {(4, 2)}:
        assert a[slot] == b[slot]


# --- CLI ---

@pytest.fixture(autouse=True)
def game_not_running(monkeypatch):
    monkeypatch.setattr(safe_io, "is_game_running", lambda: False)


def test_cli_list(sample_bytes, tmp_path, capsys):
    src = tmp_path / "hero.fch"
    src.write_bytes(sample_bytes)
    assert main(["inv", "list", str(src)]) == 0
    out = capsys.readouterr().out
    assert "grid: 8x4" in out and "Wood" in out and "ArmorRagsChest" in out


def test_cli_set_and_verify(sample_bytes, tmp_path):
    src, out = tmp_path / "hero.fch", tmp_path / "edited.fch"
    src.write_bytes(sample_bytes)
    assert main(["inv", "set", str(src), "--slot", "4,2", "--stack", "50", "--out", str(out)]) == 0
    assert load_file(out).profile.player.items[3].stack == 50 or \
        any(i.stack == 50 for i in load_file(out).profile.player.items if (i.x, i.y) == (4, 2))
    assert src.read_bytes() == sample_bytes


def test_cli_add_unknown_needs_opt_in(sample_bytes, tmp_path, capsys):
    src = tmp_path / "hero.fch"
    src.write_bytes(sample_bytes)
    assert main(["inv", "add", str(src), "TotallyFakeItem", "--dry-run"]) == 1
    assert "not a known item prefab" in capsys.readouterr().err
    assert main(["inv", "add", str(src), "TotallyFakeItem", "--allow-unknown-item", "--dry-run"]) == 0


def test_cli_add_known_item(sample_bytes, tmp_path):
    src, out = tmp_path / "hero.fch", tmp_path / "edited.fch"
    src.write_bytes(sample_bytes)
    assert main(["inv", "add", str(src), "Coins", "--stack", "500", "--out", str(out)]) == 0
    items = load_file(out).profile.player.items
    added = [i for i in items if i.prefab_hash == stable_hash("Coins")]
    assert len(added) == 1 and added[0].stack == 500


def test_cli_remove(sample_bytes, tmp_path):
    src, out = tmp_path / "hero.fch", tmp_path / "edited.fch"
    src.write_bytes(sample_bytes)
    before = len(load_file(src).profile.player.items)
    assert main(["inv", "remove", str(src), "--slot", "2,3", "--out", str(out)]) == 0
    assert len(load_file(out).profile.player.items) == before - 1


def test_cli_list_loads_the_catalog_once(sample_bytes, tmp_path, monkeypatch):
    from fch_editor.catalog import items as items_mod

    src = tmp_path / "hero.fch"
    src.write_bytes(sample_bytes)
    calls = []
    real_load = items_mod.ItemCatalog.load
    monkeypatch.setattr(items_mod.ItemCatalog, "load", classmethod(lambda cls, extra=(): (calls.append(1), real_load(extra))[1]))
    assert main(["inv", "list", str(src)]) == 0
    assert len(calls) == 1  # not once per item (19 items in the sample)


def test_cli_bad_slot_writes_nothing(sample_bytes, tmp_path):
    src = tmp_path / "hero.fch"
    src.write_bytes(sample_bytes)
    assert main(["inv", "set", str(src), "--slot", "9,9", "--stack", "5", "--in-place"]) == 1
    assert src.read_bytes() == sample_bytes
    assert list(tmp_path.iterdir()) == [src]
