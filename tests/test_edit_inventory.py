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

    def test_quality_persists_and_sets_the_flag(self, save):
        result = apply_edits(save, [inv.SetItemField((4, 2), quality=3)])
        item = _items(load_bytes(result.data).profile)[(4, 2)]
        assert item.quality == 3 and item.flags & model.HAS_QUALITY

    def test_quality_of_one_clears_the_flag(self, save):
        # (4,2) starts at the default quality (1, no flag); set it up first,
        # then set it back down, matching the stack round-trip test above.
        result = apply_edits(save, [inv.SetItemField((4, 2), quality=3)])
        result = apply_edits(load_bytes(result.data), [inv.SetItemField((4, 2), quality=1)])
        item = _items(load_bytes(result.data).profile)[(4, 2)]
        assert item.quality == 1 and not item.flags & model.HAS_QUALITY

    def test_quality_above_the_old_vanilla_cap_is_accepted(self, save):
        # The headline case: Forge of Potential (Ashlands) already pushes real
        # items past the old max of 4, so this must not be rejected as "too high".
        result = apply_edits(save, [inv.SetItemField((4, 2), quality=10)])
        item = _items(load_bytes(result.data).profile)[(4, 2)]
        assert item.quality == 10

    def test_quality_combines_with_stack_and_durability_in_one_commit(self, save):
        result = apply_edits(save, [inv.SetItemField((4, 2), stack=7, durability=50.0, quality=3)])
        item = _items(load_bytes(result.data).profile)[(4, 2)]
        assert (item.stack, item.durability_x100, item.quality) == (7, 5000, 3)

    @pytest.mark.parametrize("quality", [0, -1])
    def test_quality_below_one_rejected(self, quality):
        with pytest.raises(EditError, match="quality"):
            inv.SetItemField((0, 0), quality=quality)


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


def test_cli_set_quality_above_the_old_vanilla_cap(sample_bytes, tmp_path):
    """The core error message names quality as one of the fields `inv set`
    accepts, so the command has to actually offer --quality -- and 7 is above
    the old vanilla max of 4 on purpose (Forge of Potential)."""
    src, out = tmp_path / "hero.fch", tmp_path / "edited.fch"
    src.write_bytes(sample_bytes)
    assert main(["inv", "set", str(src), "--slot", "4,2", "--quality", "7", "--out", str(out)]) == 0
    item = next(i for i in load_file(out).profile.player.items if (i.x, i.y) == (4, 2))
    assert item.quality == 7 and item.flags & model.HAS_QUALITY
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


# --- SortInventory -------------------------------------------------------------

def _label_of():
    from fch_editor.catalog.items import ItemCatalog
    catalog = ItemCatalog.load()
    return lambda h: catalog.display(h) or catalog.label(h)


def _without_position(item):
    import dataclasses
    return dataclasses.replace(item, x=0, y=0)


def _sorted_save(save, **kw):
    result = apply_edits(save, [inv.SortInventory(_label_of(), **kw)])
    return load_bytes(result.data).profile, result


def _below_hotbar(profile, equipped=False):
    width, height = inv.grid_size(profile.player)
    return [i for i in profile.player.items if 0 <= i.x < width and 1 <= i.y < height and i.equipped == equipped]


class TestSortInventory:
    def test_orders_everything_below_the_hotbar_by_name(self, save):
        label_of = _label_of()
        out, _ = _sorted_save(save)
        names = [label_of(i.prefab_hash).lower() for i in sorted(_below_hotbar(out), key=lambda i: (i.y, i.x))]
        assert names == sorted(names) and len(names) > 3

    def test_only_x_and_y_change(self, save):
        out, _ = _sorted_save(save)
        key = lambda i: (i.prefab_hash, i.stack, i.quality, i.durability_x100, i.flags, i.crafter_name)  # noqa: E731
        before = sorted((_without_position(i) for i in save.profile.player.items), key=key)
        after = sorted((_without_position(i) for i in out.player.items), key=key)
        assert before == after

    def test_the_hotbar_is_untouched(self, save):
        out, _ = _sorted_save(save)
        hotbar = lambda p: {(i.x, i.y): i for i in p.player.items if i.y == 0}  # noqa: E731
        assert hotbar(out) == hotbar(save.profile) and len(hotbar(out)) > 3

    def test_equipped_items_keep_their_slot_and_the_rest_sort_around_them(self, save):
        equipped_before = {(i.x, i.y) for i in save.profile.player.items if i.equipped and i.y >= 1}
        assert equipped_before  # the sample has equipped armour below the hotbar
        out, _ = _sorted_save(save)
        assert {(i.x, i.y) for i in out.player.items if i.equipped and i.y >= 1} == equipped_before
        taken = {(i.x, i.y) for i in _below_hotbar(out)}
        assert taken.isdisjoint(equipped_before)  # nothing landed on a pinned slot

    def test_items_pack_into_the_first_free_slots_with_the_gaps_at_the_end(self, save):
        out, _ = _sorted_save(save)
        width, height = inv.grid_size(out.player)
        pinned = {(i.x, i.y) for i in _below_hotbar(out, equipped=True)}
        free = [(x, y) for y in range(1, height) for x in range(width) if (x, y) not in pinned]
        used = {(i.x, i.y) for i in _below_hotbar(out)}
        assert used == set(free[:len(used)])

    def test_items_outside_the_grid_stay_where_they_are(self, save):
        stray = save.profile.player.items[0]
        stray.x, stray.y = 99, 99
        out, _ = _sorted_save(save)
        assert any((i.x, i.y) == (99, 99) for i in out.player.items)

    def test_sorting_twice_changes_nothing_more(self, save):
        first, _ = _sorted_save(save)
        again = inv.SortInventory(_label_of()).plan(first.player)
        assert all((item.x, item.y) == (x, y) for item, x, y in again)

    def test_plan_mutates_nothing(self, save):
        before = [(i.x, i.y) for i in save.profile.player.items]
        inv.SortInventory(_label_of()).plan(save.profile.player)
        assert [(i.x, i.y) for i in save.profile.player.items] == before

    def test_ties_keep_their_existing_order(self, save):
        player = save.profile.player
        first, second = [i for i in player.items if i.prefab_hash == WOOD and i.y >= 1][:2]
        for item, marker in ((first, 111), (second, 222)):
            item.stack, item.durability_x100 = 10, marker  # identical sort keys; the marker tells them apart
        # swap their positions so the on-screen order is the OPPOSITE of the list order:
        # only real stability (not "keep whatever order the grid shows") keeps first ahead of second
        (first.x, first.y), (second.x, second.y) = (second.x, second.y), (first.x, first.y)
        assert player.items.index(first) < player.items.index(second)
        out, _ = _sorted_save(save)
        by_marker = {i.durability_x100: i for i in out.player.items if i.durability_x100 in (111, 222)}
        pos = lambda i: (i.y, i.x)  # noqa: E731
        assert pos(by_marker[111]) < pos(by_marker[222])

    def test_more_items_than_slots_refuses_and_moves_nothing(self, save):
        import copy
        player = save.profile.player
        template = next(i for i in player.items if i.y >= 1 and not i.equipped)
        for _ in range(30):  # several items on one coordinate -- a broken save -- overflow the region
            extra = copy.deepcopy(template)
            player.items.append(extra)
        before = [(i.x, i.y) for i in player.items]
        with pytest.raises(EditError, match="refusing to drop"):
            inv.SortInventory(_label_of()).apply(save.profile)
        assert [(i.x, i.y) for i in player.items] == before

    def test_passes_the_blast_radius_check_and_reloads(self, save):
        _, result = _sorted_save(save)  # apply_edits raises UnsafeWrite if a change is out of scope
        assert result.changes  # the sample really does get rearranged
        assert load_bytes(result.data).writable

    def test_a_save_with_only_a_hotbar_is_left_alone(self, save):
        player = save.profile.player
        player.items = [i for i in player.items if i.y == 0]
        assert inv.SortInventory(_label_of()).plan(player) == []


class TestSortInventoryEdgeCases:
    def test_a_full_grid_still_leaves_the_pinned_slots_alone(self, save):
        """The sample only has 12 movable items, which never reach the row that holds
        the equipped armour; fill every free slot so the sort has to step around it."""
        import copy
        player = save.profile.player
        width, height = inv.grid_size(player)
        pinned = {(i.x, i.y) for i in player.items if i.equipped and i.y >= 1}
        template = next(i for i in player.items if i.y >= 1 and not i.equipped)
        taken = {(i.x, i.y) for i in player.items}
        for y in range(1, height):
            for x in range(width):
                if (x, y) not in taken:
                    extra = copy.deepcopy(template)
                    extra.x, extra.y = x, y
                    player.items.append(extra)
        assert len(_below_hotbar(save.profile)) == width * (height - 1) - len(pinned)  # exactly full
        out, _ = _sorted_save(save)
        coords = [(i.x, i.y) for i in out.player.items if i.y >= 1]
        assert len(coords) == len(set(coords))  # nobody shares a slot
        assert {(i.x, i.y) for i in out.player.items if i.equipped and i.y >= 1} == pinned

    def test_the_bigger_stack_comes_first_among_identical_items(self, save):
        out, _ = _sorted_save(save)
        stacks = [i.stack for i in sorted(_below_hotbar(out), key=lambda i: (i.y, i.x)) if i.prefab_hash == WOOD]
        assert len(stacks) >= 3 and stacks == sorted(stacks, reverse=True)


class TestSortInventoryVariants:
    def test_prefabs_that_share_a_display_name_group_instead_of_interleaving(self, save):
        import copy
        player = save.profile.player
        template = next(i for i in player.items if i.y >= 1 and not i.equipped)
        a, b = stable_hash("ArmorBronzeChest"), stable_hash("FW_ArmorBronzeChest")
        label = lambda h: "Bronze Plate Tunic" if h in (a, b) else str(h)  # noqa: E731 - one shared display name
        player.items = [i for i in player.items if i.y == 0 or i.equipped]  # start from an empty region
        for prefab, stack in ((a, 5), (b, 50), (a, 50), (b, 5)):
            extra = copy.deepcopy(template)
            extra.prefab_hash, extra.stack = prefab, stack
            extra.x, extra.y = -1, -1  # placed by the sort; give them slots that exist below
            player.items.append(extra)
        free = iter([(x, y) for y in (1, 2) for x in range(8)])
        for item in player.items[-4:]:
            item.x, item.y = next(free)
        moves = inv.SortInventory(label).plan(player)
        ordered = [item.prefab_hash for item, _x, _y in sorted(moves, key=lambda m: (m[2], m[1]))]
        changes = sum(1 for p, q in zip(ordered, ordered[1:]) if p != q)
        assert changes == 1  # AAAA... then BBBB..., never A B A B
        stacks_a = [item.stack for item, _x, _y in sorted(moves, key=lambda m: (m[2], m[1])) if item.prefab_hash == a]
        assert stacks_a == [50, 5]
