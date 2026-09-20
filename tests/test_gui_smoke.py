"""Drives the real Tk window end to end: open, edit each tab, save, reload.

Skips (not fails) where no display is available, e.g. a headless CI runner.
Every dialog that would otherwise block on user input is monkeypatched to
answer automatically, per the app's own dependency-injection points
(`fch_editor.gui.dialogs`).
"""
import tkinter as tk

import pytest

from fch_editor import model
from fch_editor.load import load_file
from fch_editor.stable_hash import stable_hash

pytest.importorskip("tkinter")

from fch_editor.gui import dialogs as _dialogs_module  # noqa: E402
_REAL_CONFIRM_SORT = _dialogs_module.confirm_sort  # the autouse fixture stubs the module attribute


@pytest.fixture
def app_window():
    from fch_editor.gui.app import App

    app = None
    last_error = None
    for _attempt in range(3):  # creating a Tk root right after destroying one can transiently fail
        try:
            app = App()
            break
        except tk.TclError as e:
            last_error = e
    if app is None:
        pytest.skip(f"no display available for Tk: {last_error}")
    # Off-screen rather than withdrawn: a withdrawn window prevents a
    # `.transient()` child (any modal dialog) from ever getting real pack
    # geometry, which would hide the exact class of bug these tests exist to
    # catch (see tests/test_gui_dialogs.py).
    app.geometry("760x560+2000+2000")
    yield app
    app.destroy()


@pytest.fixture(autouse=True)
def auto_confirm(monkeypatch):
    from fch_editor.gui import dialogs
    errors = []
    monkeypatch.setattr(dialogs, "confirm_changes", lambda parent, changes: True)
    monkeypatch.setattr(dialogs, "ask_yes_no", lambda parent, msg: True)
    monkeypatch.setattr(dialogs, "confirm_game_running", lambda parent: True)
    monkeypatch.setattr(dialogs, "confirm_sort", lambda parent: True)  # a real modal loop would hang a test
    monkeypatch.setattr(dialogs, "error", lambda parent, msg: errors.append(msg))
    return errors


@pytest.fixture
def sample_copy(sample_bytes, tmp_path):
    path = tmp_path / "hero.fch"
    path.write_bytes(sample_bytes)
    return path


def test_open_populates_every_tab(app_window, sample_copy):
    app_window.open_file(sample_copy)
    app_window.update()
    assert app_window.state.save.writable
    assert len(app_window.skills_tab.tree.get_children()) == 13
    assert len(app_window.inventory_tab.tree.get_children()) == 19
    assert app_window.character_tab.name_var.get() == "Lorce"


def test_skills_tab_edit_becomes_pending(app_window, sample_copy):
    app_window.open_file(sample_copy)
    app_window.skills_tab.skill_var.set("Run")
    app_window.skills_tab.level_var.set("77")
    app_window.skills_tab._apply()
    assert app_window.state.dirty
    p = app_window.state.preview().profile
    assert p.player.skills[[s.type for s in p.player.skills].index(102)].level == 77.0


def test_skills_tab_rejects_bad_level(app_window, sample_copy, auto_confirm):
    app_window.open_file(sample_copy)
    app_window.skills_tab.skill_var.set("Run")
    app_window.skills_tab.level_var.set("-5")
    app_window.skills_tab._apply()
    assert not app_window.state.dirty
    assert auto_confirm  # the error dialog was shown


def test_character_tab_apply_updates_every_field_at_once(app_window, sample_copy):
    app_window.open_file(sample_copy)
    ct = app_window.character_tab
    ct.name_var.set("GuiHero")
    ct.hair_var.set("Hair5")
    ct.power_var.set("Eikthyr")
    ct._apply()
    p = app_window.state.preview().profile
    assert (p.name, p.player.hair, p.player.guardian_power) == ("GuiHero", "Hair5", "GP_Eikthyr")


def _select_slot(inv_tab, slot_text: str) -> None:
    # refresh() rebuilds the tree (fresh row ids), so re-find the row each time.
    row = next(r for r in inv_tab.tree.get_children() if inv_tab.tree.item(r, "values")[0] == slot_text)
    inv_tab.tree.selection_set(row)
    inv_tab._on_select(None)


def test_inventory_tab_select_set_and_remove(app_window, sample_copy):
    app_window.open_file(sample_copy)
    inv_tab = app_window.inventory_tab
    _select_slot(inv_tab, "4,2")
    inv_tab.stack_var.set("77")
    inv_tab._apply_set()
    item = next(i for i in app_window.state.preview().profile.player.items if (i.x, i.y) == (4, 2))
    assert item.stack == 77

    _select_slot(inv_tab, "4,2")
    inv_tab._apply_remove()
    assert (4, 2) not in {(i.x, i.y) for i in app_window.state.preview().profile.player.items}


def test_inventory_tab_copy_preserves_quality_and_stays_selected(app_window, sample_copy, auto_confirm):
    app_window.open_file(sample_copy)
    inv_tab = app_window.inventory_tab
    # Mutate the baseline (state.save.profile), not preview()'s result:
    # preview() caches a deepcopy that add() throws away on the next edit, so
    # mutating that cached copy would be invisible to the edit CopyItem
    # actually applies against.
    baseline_player = app_window.state.save.profile.player
    source = next(i for i in baseline_player.items if (i.x, i.y) == (4, 2))
    # Set to a non-default value first: quality defaults to 1, so leaving it
    # untouched would let a naive AddItem-style copy (which resets quality to
    # 1) pass this assertion by accident.
    source.quality = 3
    source.flags |= model.HAS_QUALITY
    before_count = len(baseline_player.items)
    before_slots = {(it.x, it.y) for it in baseline_player.items}

    _select_slot(inv_tab, "4,2")
    inv_tab._apply_copy()

    # apply_edits_batch() swallows EditError/UnsafeWrite into a dialog, which
    # auto_confirm redirects into this list instead of raising -- so a
    # rejected edit would otherwise show up several lines down as a confusing
    # item-count mismatch with no indication of why. Assert this first.
    assert auto_confirm == [], f"copy was rejected: {auto_confirm}"

    after = app_window.state.preview().profile.player
    assert len(after.items) == before_count + 1
    new_items = [i for i in after.items if (i.x, i.y) not in before_slots]
    assert len(new_items) == 1
    assert new_items[0].prefab_hash == source.prefab_hash
    assert new_items[0].stack == source.stack
    assert new_items[0].quality == 3
    # Unlike Remove, Copy leaves the source selected -- repeat copies need no re-selection.
    assert inv_tab._selected_slot == (4, 2)


def test_inventory_tab_copy_without_a_selection_reports_cleanly(app_window, sample_copy, auto_confirm):
    app_window.open_file(sample_copy)
    inv_tab = app_window.inventory_tab
    inv_tab._selected_slot = None
    inv_tab._apply_copy()
    assert any("Select an item first" in e for e in auto_confirm)


def test_inventory_tab_sets_quality_above_the_old_vanilla_cap(app_window, sample_copy, auto_confirm):
    """The Ashlands Forge of Potential pushes items past the old max of 4, so 5
    must be accepted -- and must show up in the tree, which had no quality
    column at all before."""
    app_window.open_file(sample_copy)
    inv_tab = app_window.inventory_tab
    _select_slot(inv_tab, "4,2")
    inv_tab.quality_var.set("5")
    inv_tab._apply_set()
    assert auto_confirm == [], f"edit was rejected: {auto_confirm}"

    item = next(i for i in app_window.state.preview().profile.player.items if (i.x, i.y) == (4, 2))
    assert item.quality == 5

    # Re-selecting repopulates the field from the tree's own quality column.
    _select_slot(inv_tab, "4,2")
    assert inv_tab.quality_var.get() == "5"
    row = next(r for r in inv_tab.tree.get_children() if inv_tab.tree.item(r, "values")[0] == "4,2")
    assert "5" in [str(v) for v in inv_tab.tree.item(row, "values")]


def test_inventory_tab_quality_and_stack_edits_do_not_drop_each_other(app_window, sample_copy, auto_confirm):
    """edit_key() dedups a SetItemField by slot and REPLACES rather than merges,
    so a second Apply that omitted quality would silently discard the first.
    _apply_set reads every field each time, so editing stack afterwards must
    carry the earlier quality edit along."""
    app_window.open_file(sample_copy)
    inv_tab = app_window.inventory_tab
    _select_slot(inv_tab, "4,2")
    inv_tab.quality_var.set("3")
    inv_tab._apply_set()

    inv_tab.stack_var.set("9")
    inv_tab._apply_set()
    assert auto_confirm == [], f"edit was rejected: {auto_confirm}"

    assert len(app_window.state.pending) == 1  # replaced, not piled up
    item = next(i for i in app_window.state.preview().profile.player.items if (i.x, i.y) == (4, 2))
    assert (item.stack, item.quality) == (9, 3)


def test_inventory_tab_rejects_bad_quality(app_window, sample_copy, auto_confirm):
    app_window.open_file(sample_copy)
    inv_tab = app_window.inventory_tab
    _select_slot(inv_tab, "4,2")
    for bad in ("0", "-1", "abc", "2.5"):
        inv_tab.quality_var.set(bad)
        inv_tab._apply_set()
    assert not app_window.state.dirty
    assert len(auto_confirm) == 4  # every bad value got its own error dialog


def test_inventory_tab_add_unknown_item_needs_opt_in(app_window, sample_copy, auto_confirm):
    app_window.open_file(sample_copy)
    inv_tab = app_window.inventory_tab
    inv_tab.name_var.set("TotallyFakeItem")
    inv_tab._apply_add()
    assert not app_window.state.dirty
    assert any("not a known item prefab" in e for e in auto_confirm)

    inv_tab.allow_unknown_var.set(True)
    inv_tab._apply_add()
    assert app_window.state.dirty


def test_inventory_add_box_finds_an_item_by_its_in_game_name(app_window, sample_copy):
    """The table lists "Stone Axe (AxeStone)", so the add box below it has to
    accept the same string -- otherwise the one name the user can see is the one
    name they cannot type."""
    app_window.open_file(sample_copy)
    inv_tab = app_window.inventory_tab
    labels = list(inv_tab.name_box["values"])
    assert "Stone Axe (AxeStone)" in labels
    # The prefab stays visible in every label, because it is what the save
    # hashes and what the CLI takes.
    assert all("(" in label or label.isidentifier() for label in labels[:50])

    inv_tab.name_var.set("Stone Axe (AxeStone)")
    inv_tab._apply_add()
    added = [i for i in app_window.state.preview().profile.player.items
             if i.prefab_hash == stable_hash("AxeStone")]
    assert len(added) == 2, "the display label should add AxeStone, the prefab it stands for"


def test_inventory_add_box_still_takes_a_typed_prefab(app_window, sample_copy):
    """The label mapping must never get in the way of typing a prefab name --
    from the CLI, a bug report, or a game version newer than this catalog."""
    app_window.open_file(sample_copy)
    inv_tab = app_window.inventory_tab
    inv_tab.name_var.set("Coins")
    inv_tab._apply_add()
    assert any(i.prefab_hash == stable_hash("Coins")
               for i in app_window.state.preview().profile.player.items)


def test_inventory_add_box_narrows_on_either_name(app_window, sample_copy):
    app_window.open_file(sample_copy)
    box = app_window.inventory_tab.name_box

    # Tk delivers key events to the focused widget, and this box sits on a
    # notebook tab that isn't selected -- event_generate would be swallowed and
    # every assertion below would pass without the filter ever running. So the
    # handler is called directly, and the wiring that would call it in a real
    # session is asserted separately.
    assert box.bind("<KeyRelease>"), "the narrowing handler is no longer bound"

    class _KeyRelease:
        keysym = "a"

    def narrow_to(text):
        box.set(text)
        box._on_key(_KeyRelease())
        return list(box["values"])

    axe = narrow_to("Stone Axe")
    assert axe == ["Stone Axe (AxeStone)"], axe

    # The prefab half of the same label. Substring matching, so "AxeStone" also
    # pulls in "PickaxeStone" -- the same behaviour the web combobox has, and
    # the reason the prefab stays printed in every label.
    by_prefab = narrow_to("AxeStone")
    assert "Stone Axe (AxeStone)" in by_prefab
    assert all("axestone" in label.lower() for label in by_prefab), by_prefab

    assert narrow_to("zzzznotanitem") == []
    assert len(narrow_to("")) == len(app_window.catalog.entries())


def test_full_round_trip_save_in_place(app_window, sample_copy):
    app_window.open_file(sample_copy)
    app_window.skills_tab.skill_var.set("all")
    app_window.skills_tab.level_var.set("10")
    app_window.skills_tab._apply()
    app_window.character_tab.name_var.set("GuiHero")
    app_window.character_tab._apply()
    inv_tab = app_window.inventory_tab
    inv_tab.name_var.set("Coins")
    inv_tab.add_stack_var.set("250")
    inv_tab._apply_add()

    app_window.save_in_place()
    assert not app_window.state.dirty  # rebased onto the freshly written file

    reloaded = load_file(sample_copy)
    assert reloaded.writable and reloaded.profile.name == "GuiHero"
    assert all(s.level == 10.0 for s in reloaded.profile.player.skills)
    coins = [i for i in reloaded.profile.player.items if i.prefab_hash == stable_hash("Coins")]
    assert len(coins) == 1 and coins[0].stack == 250
    assert any(p.name.startswith("hero.fch.bak-") for p in sample_copy.parent.iterdir())


def test_save_as_leaves_the_source_untouched(app_window, sample_copy, monkeypatch, tmp_path):
    from tkinter import filedialog
    out = tmp_path / "copy.fch"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kw: str(out))

    app_window.open_file(sample_copy)
    original_bytes = sample_copy.read_bytes()
    app_window.skills_tab.skill_var.set("Run")
    app_window.skills_tab.level_var.set("99")
    app_window.skills_tab._apply()
    app_window.save_as()

    assert sample_copy.read_bytes() == original_bytes
    assert load_file(out).profile.player.skills[
        [s.type for s in load_file(out).profile.player.skills].index(102)].level == 99.0


def test_read_only_save_disables_edit_tabs(app_window, tmp_path, sample_bytes):
    import struct

    from fch_editor import container
    payload = bytearray(container.unpack(sample_bytes).payload)
    struct.pack_into("<i", payload, 0, 47)
    path = tmp_path / "old.fch"
    path.write_bytes(container.pack(bytes(payload)))

    app_window.open_file(path)
    assert not app_window.state.save.writable
    buttons = [w for w in app_window.skills_tab.winfo_children()[0].winfo_children()
              if w.winfo_class() == "TButton"]
    assert buttons and all(str(b.cget("state")) == "disabled" for b in buttons)


def test_switching_saves_refreshes_everything(app_window, sample_copy, sample_bytes, tmp_path):
    other = tmp_path / "other.fch"
    other.write_bytes(sample_bytes)
    app_window.open_file(sample_copy)
    app_window.character_tab.name_var.set("Temporary")
    app_window.character_tab._apply()
    assert app_window.state.dirty

    app_window.open_file(other)  # auto-confirms discarding the pending edit
    assert not app_window.state.dirty
    assert app_window.character_tab.name_var.get() == "Lorce"


def test_inventory_tab_forms_stay_visible_when_selected(app_window, sample_copy):
    """Regression: the edit/add forms were packed after the expand=True tree,
    so a window shorter than everyone's natural size squeezed them to 0x0
    (see gui/tabs/inventory.py's packing-order comment)."""
    app_window.open_file(sample_copy)
    notebook = app_window.inventory_tab.master
    notebook.select(app_window.inventory_tab)  # a Notebook only lays out the selected tab
    app_window.update()

    for child in app_window.inventory_tab.winfo_children():
        assert child.winfo_viewable() == 1 and child.winfo_height() > 5, \
            f"{child.winfo_class()} is not properly visible in the inventory tab"


def test_apply_edit_without_an_open_save_reports_cleanly(app_window, auto_confirm):
    from fch_editor.edits.skills import SetSkillLevel
    assert app_window.apply_edit(SetSkillLevel(102, 10.0)) is False
    assert auto_confirm


# --- grid / list view --------------------------------------------------------

def _open_inventory(app_window, sample_copy):
    app_window.open_file(sample_copy)
    tab = app_window.inventory_tab
    tab.master.select(tab)
    app_window.update()
    return tab


def _go_grid(tab):
    tab.view_var.set("grid")
    tab._switch_view()


def _go_list(tab):
    tab.view_var.set("list")
    tab._switch_view()


def test_inventory_defaults_to_list_view(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    assert tab.view_var.get() == "list"
    assert tab.tree.winfo_ismapped() and not tab.grid_frame.winfo_ismapped()
    assert tab._slot_buttons == {}  # nothing is built until the grid is asked for


def test_grid_view_uses_the_saves_own_grid_size_and_shows_items(app_window, sample_copy):
    from fch_editor.edits import inventory as inv
    tab = _open_inventory(app_window, sample_copy)
    player = app_window.state.preview().profile.player
    width, height = inv.grid_size(player)
    _go_grid(tab)
    app_window.update()
    assert tab.grid_frame.winfo_ismapped() and not tab.tree.winfo_ismapped()
    assert len(tab._slot_buttons) == width * height
    occupied = {(i.x, i.y) for i in player.items if 0 <= i.x < width and 0 <= i.y < height}
    filled = {s for s, b in tab._slot_buttons.items() if b.cget("text")}
    assert filled == occupied


def test_grid_selection_fills_the_same_form_as_the_list(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    _select_slot(tab, "4,2")
    from_list = (tab._selected_slot, tab.stack_var.get(), tab.durability_var.get(), tab.quality_var.get())
    assert from_list[0] == (4, 2)

    _go_grid(tab)
    tab.reset_selection()
    tab._slot_buttons[(4, 2)].invoke()
    from_grid = (tab._selected_slot, tab.stack_var.get(), tab.durability_var.get(), tab.quality_var.get())
    assert from_grid == from_list


def test_grid_click_edit_apply_round_trip(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    _go_grid(tab)
    tab._slot_buttons[(4, 2)].invoke()
    tab.stack_var.set("55")
    tab._apply_set()
    item = next(i for i in app_window.state.preview().profile.player.items if (i.x, i.y) == (4, 2))
    assert item.stack == 55


def test_selection_survives_switching_views_both_ways(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    _select_slot(tab, "4,2")
    _go_grid(tab)
    assert tab._selected_slot == (4, 2)
    assert tab._slot_buttons[(4, 2)].cget("relief") == "sunken"
    _go_list(tab)
    app_window.update()  # let the queued <<TreeviewSelect>> run, as a real session would
    assert tab._selected_slot == (4, 2)
    assert tab.tree.item(tab.tree.selection()[0], "values")[0] == "4,2"


def test_selection_survives_an_edit_once_events_are_processed(app_window, sample_copy):
    """Rebuilding the tree deletes the selected row, which queues a
    <<TreeviewSelect>> with nothing selected; without re-selecting after the
    rebuild that wipes the selection after every edit. Only visible when the
    event loop actually runs."""
    tab = _open_inventory(app_window, sample_copy)
    _select_slot(tab, "4,2")
    app_window.update()
    tab.stack_var.set("12")
    tab._apply_set()
    app_window.update()
    assert tab._selected_slot == (4, 2)


def test_clicking_an_empty_slot_aims_the_add_form_and_clears_the_selection(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    taken = {(i.x, i.y) for i in app_window.state.preview().profile.player.items}
    _go_grid(tab)
    empty = next(s for s in tab._slot_buttons if s not in taken)
    tab._slot_buttons[(4, 2)].invoke()
    tab._slot_buttons[empty].invoke()
    assert tab._selected_slot is None
    assert tab.add_slot_var.get() == f"{empty[0]},{empty[1]}"
    assert tab.stack_var.get() == ""


def test_removing_from_the_grid_clears_the_highlight(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    _go_grid(tab)
    tab._slot_buttons[(4, 2)].invoke()
    tab._apply_remove()
    assert tab._selected_slot is None
    assert all(b.cget("relief") == "raised" for b in tab._slot_buttons.values())
    assert tab._slot_buttons[(4, 2)].cget("text") == ""


def test_a_fully_placeable_inventory_carries_no_grid_warning(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    _go_grid(tab)
    assert tab.grid_warning.cget("text") == ""


def test_read_only_save_can_still_toggle_and_inspect_but_not_edit(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    app_window.state.save.reasons.append("test: read only")
    app_window.refresh_all()
    assert not app_window.state.save.writable

    def buttons(container):
        for child in container.winfo_children():
            if child.winfo_class() in ("TRadiobutton", "TButton"):
                yield child
            yield from buttons(child)

    radios = [w for w in buttons(tab) if w.winfo_class() == "TRadiobutton"]
    assert radios and all(str(r.cget("state")) != "disabled" for r in radios)
    _go_grid(tab)
    app_window.update()
    assert all(str(b.cget("state")) != "disabled" for b in tab._slot_buttons.values())
    tab._slot_buttons[(4, 2)].invoke()  # inspecting works
    assert tab._selected_slot == (4, 2)
    apply_btn = next(w for w in buttons(tab) if w.cget("text") == "Apply")
    assert str(apply_btn.cget("state")) == "disabled"  # editing does not


def test_opening_another_save_forgets_the_selection(app_window, sample_copy, sample_bytes, tmp_path):
    tab = _open_inventory(app_window, sample_copy)
    _select_slot(tab, "4,2")
    tab.add_slot_var.set("1,1")
    other = tmp_path / "other.fch"
    other.write_bytes(sample_bytes)
    app_window.open_file(other)
    assert tab._selected_slot is None
    assert tab.stack_var.get() == "" and tab.add_slot_var.get() == ""


def test_keep_enabled_exempts_a_widget_and_its_subtree_from_the_sweep(app_window):
    from tkinter import ttk

    from fch_editor.gui.widgets import keep_enabled, set_widgets_state
    holder = ttk.Frame(app_window)
    swept = ttk.Button(holder)
    held = keep_enabled(ttk.Frame(holder))
    inner = ttk.Button(held)
    set_widgets_state(holder, False)
    assert str(swept.cget("state")) == "disabled"
    assert str(inner.cget("state")) != "disabled"


def _slot_is_fully_visible(tab, button) -> bool:
    """Inside the scroll area's visible box, horizontally -- not merely mapped."""
    canvas = tab.slots_frame.master
    return (button.winfo_viewable() and button.winfo_x() >= 0
            and button.winfo_x() + button.winfo_width() <= canvas.winfo_width())


def test_every_grid_column_fits_the_default_window(app_window, sample_copy):
    """Regression: at 760x560 the 8th column used to start 3px inside the frame,
    so an item in hotbar slot 8 was placed but unclickable."""
    tab = _open_inventory(app_window, sample_copy)
    _go_grid(tab)
    app_window.update()
    assert app_window.winfo_width() >= 760  # the size the app really opens at
    hidden = [s for s, b in tab._slot_buttons.items() if not _slot_is_fully_visible(tab, b)
              if s[1] == 0]
    assert hidden == []


def test_a_tall_grid_scrolls_instead_of_clipping(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    player = app_window.state.save.profile.player
    player.uniques = [u for u in player.uniques if not u.startswith("invrows")] + ["invrows 9"]
    app_window.state.set_pending([])  # drops the cached preview so it sees the mutation
    app_window.refresh_all()
    _go_grid(tab)
    app_window.update()
    assert len(tab._slot_buttons) == 8 * 9
    canvas = tab.slots_frame.master
    scroll_bottom = float(canvas.cget("scrollregion").split()[3])
    assert scroll_bottom > canvas.winfo_height()  # more content than room...
    assert scroll_bottom >= tab._slot_buttons[(7, 8)].winfo_y() + tab._slot_buttons[(7, 8)].winfo_height()  # ...all reachable


def test_refresh_keeps_text_typed_but_not_yet_applied(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    _select_slot(tab, "4,2")
    app_window.update()
    tab.stack_var.set("999")  # typed, not applied
    tab.name_var.set("AxeStone")
    tab._apply_add()  # any edit refreshes the tab
    app_window.update()
    assert tab.stack_var.get() == "999"
    assert tab._selected_slot == (4, 2)


def test_selecting_an_item_after_an_empty_slot_clears_the_add_target(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    taken = {(i.x, i.y) for i in app_window.state.preview().profile.player.items}
    _go_grid(tab)
    empty = next(s for s in tab._slot_buttons if s not in taken)
    tab._slot_buttons[empty].invoke()
    assert tab.add_slot_var.get()
    tab._slot_buttons[(4, 2)].invoke()
    assert tab.add_slot_var.get() == ""


# --- off-grid shelf ------------------------------------------------------------

def _mutate_items(app_window, tab, **moves):
    """Move items (by index into the save's item list) to new coordinates."""
    player = app_window.state.save.profile.player
    for index, (x, y) in moves.items():
        player.items[int(index[1:])].x, player.items[int(index[1:])].y = x, y
    app_window.state.set_pending([])  # drops the cached preview so it sees the mutation
    app_window.refresh_all()
    return player


def test_an_off_grid_item_gets_a_shelf_tile_with_its_real_coordinate(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    player = _mutate_items(app_window, tab, i0=(99, 99))
    _go_grid(tab)
    app_window.update()
    assert tab._shelf_heading.cget("text") == "Outside the grid (1)"
    (slot, tile), = tab._shelf_buttons
    assert slot == (99, 99) and "@99,99" in tile.cget("text")
    assert len(tab._slot_buttons) == 32 and (99, 99) not in tab._slot_buttons
    assert tab.grid_warning.cget("text") == ""  # not ambiguous, so nothing to warn about
    # every item is visible somewhere: filled grid tiles + shelf tiles == items
    filled = sum(1 for b in tab._slot_buttons.values() if b.cget("text"))
    assert filled + len(tab._shelf_buttons) == len(player.items)


def test_no_off_grid_items_means_no_shelf_at_all(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    _go_grid(tab)
    assert tab._shelf_buttons == [] and tab._shelf_heading is None


def test_a_shelf_item_selects_edits_copies_and_removes_like_any_other(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    player = _mutate_items(app_window, tab, i0=(99, 99))
    target = player.items[0]
    _go_grid(tab)
    (_slot, tile), = tab._shelf_buttons
    tile.invoke()
    assert tab._selected_slot == (99, 99)
    assert tab.stack_var.get() == str(target.stack)
    assert tile.cget("relief") == "sunken"

    tab.stack_var.set("7")
    tab._apply_set()
    edited = next(i for i in app_window.state.preview().profile.player.items if (i.x, i.y) == (99, 99))
    assert edited.stack == 7

    before = len(app_window.state.preview().profile.player.items)
    tab._apply_copy()  # lands in the first free slot INSIDE the grid, source stays put
    after = app_window.state.preview().profile.player.items
    assert len(after) == before + 1
    assert sum(1 for i in after if (i.x, i.y) == (99, 99)) == 1
    assert any(i.prefab_hash == edited.prefab_hash and (i.x, i.y) != (99, 99) and 0 <= i.x < 8 and 0 <= i.y < 4
               for i in after)  # the copy is inside the grid

    tab._apply_remove()
    assert (99, 99) not in {(i.x, i.y) for i in app_window.state.preview().profile.player.items}


def test_highlight_moves_between_the_grid_and_the_shelf(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    _mutate_items(app_window, tab, i0=(99, 99))
    _go_grid(tab)
    tab._slot_buttons[(4, 2)].invoke()
    (_slot, tile), = tab._shelf_buttons
    tile.invoke()
    assert tile.cget("relief") == "sunken"
    assert tab._slot_buttons[(4, 2)].cget("relief") == "raised"
    tab._slot_buttons[(4, 2)].invoke()
    assert tile.cget("relief") == "raised"


def test_a_shelf_selection_survives_switching_views(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    _mutate_items(app_window, tab, i0=(99, 99))
    _go_grid(tab)
    tab._shelf_buttons[0][1].invoke()
    _go_list(tab)
    app_window.update()
    assert tab.tree.item(tab.tree.selection()[0], "values")[0] == "99,99"
    _go_grid(tab)
    assert tab._shelf_buttons[0][1].cget("relief") == "sunken"


def test_a_long_shelf_wraps_eight_wide_fits_and_scrolls(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    player = app_window.state.save.profile.player
    template = player.items[0]
    import copy as copy_module
    for n in range(20):
        extra = copy_module.deepcopy(template)
        extra.x, extra.y = 100 + n, 50
        player.items.append(extra)
    app_window.state.set_pending([])
    app_window.refresh_all()
    _go_grid(tab)
    app_window.update()
    assert len(tab._shelf_buttons) == 20
    columns = {b.grid_info()["column"] for _s, b in tab._shelf_buttons}
    assert columns == set(range(8))
    assert all(_slot_is_fully_visible(tab, b) for _s, b in tab._shelf_buttons)
    canvas = tab.slots_frame.master
    scroll_bottom = float(canvas.cget("scrollregion").split()[3])
    last = tab._shelf_buttons[-1][1]
    assert scroll_bottom >= last.winfo_y() + last.winfo_height()  # the last tile is reachable


def test_items_sharing_a_coordinate_are_view_only_and_nothing_is_hidden(app_window, sample_copy, auto_confirm):
    tab = _open_inventory(app_window, sample_copy)
    player = app_window.state.save.profile.player
    first, second = player.items[0], player.items[1]
    _mutate_items(app_window, tab, i1=(first.x, first.y))
    shared = (first.x, first.y)
    _go_grid(tab)
    app_window.update()
    assert "claims slot" in tab.grid_warning.cget("text") and f"{shared[0]},{shared[1]}" in tab.grid_warning.cget("text")
    # the in-grid first item and the shelf copy are both view-only...
    tab._slot_buttons[shared].invoke()
    assert tab._selected_slot is None and tab.stack_var.get() == ""
    tab._shelf_buttons[0][1].invoke()
    assert tab._selected_slot is None and tab.stack_var.get() == ""
    assert tab._slot_buttons[shared].cget("relief") == "raised"
    assert tab._shelf_buttons[0][1].cget("relief") == "raised"
    # ...so no button path can reach the "N items occupy slot" error
    tab._apply_set()
    assert app_window.state.pending == []
    assert auto_confirm == ["Select an item first."]  # refused up front, not by the core's ambiguity error
    # ...and every item is still on screen
    filled = sum(1 for b in tab._slot_buttons.values() if b.cget("text"))
    assert filled + len(tab._shelf_buttons) == len(player.items)


def test_a_read_only_save_can_still_inspect_shelf_tiles(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    _mutate_items(app_window, tab, i0=(99, 99))
    app_window.state.save.reasons.append("test: read only")
    app_window.refresh_all()
    _go_grid(tab)
    tile = tab._shelf_buttons[0][1]
    assert str(tile.cget("state")) != "disabled"
    tile.invoke()
    assert tab._selected_slot == (99, 99)


def test_a_shared_coordinate_selected_from_the_list_lights_no_grid_tile(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    first = app_window.state.save.profile.player.items[0]
    _mutate_items(app_window, tab, i1=(first.x, first.y))
    _select_slot(tab, f"{first.x},{first.y}")  # the list still lets you look at it
    _go_grid(tab)
    assert all(b.cget("relief") == "raised" for b in tab._slot_buttons.values())
    assert all(b.cget("relief") == "raised" for _s, b in tab._shelf_buttons)


def test_refreshing_does_not_pile_up_shelf_widgets(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    _mutate_items(app_window, tab, i0=(99, 99))
    _go_grid(tab)
    for _ in range(3):
        app_window.refresh_all()
    real = tab.slots_frame.winfo_children()  # what is actually on screen, not our own bookkeeping
    assert sum(1 for w in real if w.winfo_class() == "Button") == 32 + 1
    assert sum(1 for w in real if w.winfo_class() == "TLabel") == 1  # the heading
    tab.view_var.set("list")
    _go_list(tab)
    _mutate_items(app_window, tab)  # no more off-grid items after a rebuild
    player = app_window.state.save.profile.player
    player.items[0].x, player.items[0].y = 0, 0
    app_window.state.set_pending([])
    app_window.refresh_all()
    _go_grid(tab)
    assert sum(1 for w in tab.slots_frame.winfo_children() if w.winfo_class() == "TLabel") == 0


def test_a_shared_coordinate_picked_in_the_list_cannot_reach_the_ambiguity_error(app_window, sample_copy, auto_confirm):
    tab = _open_inventory(app_window, sample_copy)
    first = app_window.state.save.profile.player.items[0]
    _mutate_items(app_window, tab, i1=(first.x, first.y))
    _select_slot(tab, f"{first.x},{first.y}")  # List view: no grid has been built at all
    assert tab._selected_slot is None and tab.stack_var.get() == ""
    assert "view-only" in app_window.status_var.get()
    for action in (tab._apply_set, tab._apply_copy, tab._apply_remove):
        action()
    assert auto_confirm == ["Select an item first."] * 3
    assert not any("occupy" in message for message in auto_confirm)
    assert app_window.state.pending == []


def test_shelf_tiles_show_all_their_text_even_for_extreme_coordinates(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    baseline = app_window.state.save.profile.player.items[0]
    baseline.stack = 65535
    _mutate_items(app_window, tab, i0=(-2147483648, -2147483648))
    _go_grid(tab)
    app_window.update()
    (_slot, tile), = tab._shelf_buttons
    natural = tk.Button(tab.slots_frame, text=tile.cget("text"), width=10, height=0, wraplength=72)
    natural.grid(row=99, column=0)
    app_window.update()
    assert "-2147483648,-2147483648" in tile.cget("text") and "x65535" in tile.cget("text")
    assert tile.winfo_height() >= natural.winfo_reqheight()  # sized to its text, not to a fixed line count
    natural.destroy()


# --- sort button -----------------------------------------------------------------

def _grid_layout(app_window):
    """{(x, y): (prefab_hash, stack)} for the previewed profile."""
    return {(i.x, i.y): (i.prefab_hash, i.stack) for i in app_window.state.preview().profile.player.items}


def _sort_button(tab):
    def walk(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "TButton" and child.cget("text") == "Sort":
                return child
            found = walk(child)
            if found:
                return found
        return None
    return walk(tab)


def test_sort_shows_the_grid_sorts_below_the_hotbar_and_keeps_it_pending(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    hotbar_before = {s: v for s, v in _grid_layout(app_window).items() if s[1] == 0}
    equipped_before = {(i.x, i.y) for i in app_window.state.preview().profile.player.items if i.equipped and i.y >= 1}
    _select_slot(tab, "4,2")
    tab._sort()  # confirm_sort auto-answers Keep in these tests
    app_window.update()
    assert tab.view_var.get() == "grid" and tab.grid_frame.winfo_ismapped()
    assert [type(e).__name__ for e in app_window.state.pending] == ["SortInventory"]
    assert app_window.state.dirty and tab._selected_slot is None and tab.stack_var.get() == ""
    layout = _grid_layout(app_window)
    assert {s: v for s, v in layout.items() if s[1] == 0} == hotbar_before
    player = app_window.state.preview().profile.player
    assert {(i.x, i.y) for i in player.items if i.equipped and i.y >= 1} == equipped_before
    names = [tab._sort_label(i.prefab_hash).lower()
             for i in sorted(player.items, key=lambda i: (i.y, i.x)) if i.y >= 1 and not i.equipped]
    assert names == sorted(names)


def test_undo_restores_the_pending_edits_exactly(app_window, sample_copy, monkeypatch):
    from fch_editor.gui import dialogs as dialogs_mod
    tab = _open_inventory(app_window, sample_copy)
    _select_slot(tab, "4,2")
    tab.stack_var.set("41")
    tab._apply_set()  # something already pending before the sort
    before = list(app_window.state.pending)
    layout_before = _grid_layout(app_window)
    monkeypatch.setattr(dialogs_mod, "confirm_sort", lambda parent: False)
    tab._sort()
    assert app_window.state.pending == before  # same edit objects, same order, no sort left behind
    assert _grid_layout(app_window) == layout_before
    assert "undone" in app_window.status_var.get().lower()
    assert tab._selected_slot is None


def test_keep_leaves_earlier_edits_working_on_the_right_items(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    _select_slot(tab, "4,2")
    tab.stack_var.set("77")
    source_prefab = next(i.prefab_hash for i in app_window.state.preview().profile.player.items if (i.x, i.y) == (4, 2))
    tab._apply_set()  # addressed by where the item is BEFORE the sort
    tab._sort()
    edited = [i for i in app_window.state.preview().profile.player.items if i.stack == 77]
    assert len(edited) == 1 and edited[0].prefab_hash == source_prefab  # it followed ITS item through the sort


def test_sorting_an_already_sorted_inventory_adds_nothing_and_does_not_ask(app_window, sample_copy, monkeypatch):
    from fch_editor.gui import dialogs as dialogs_mod
    tab = _open_inventory(app_window, sample_copy)
    tab._sort()
    asked = []
    monkeypatch.setattr(dialogs_mod, "confirm_sort", lambda parent: asked.append(1) or True)
    tab._sort()
    assert len(app_window.state.pending) == 1 and asked == []
    assert app_window.status_var.get() == "Already sorted"


def test_the_sort_button_is_disabled_on_a_read_only_save(app_window, sample_copy):
    tab = _open_inventory(app_window, sample_copy)
    assert str(_sort_button(tab).cget("state")) != "disabled"
    app_window.state.save.reasons.append("test: read only")
    app_window.refresh_all()
    assert str(_sort_button(tab).cget("state")) == "disabled"


def test_sort_with_no_save_open_reports_cleanly(app_window, auto_confirm):
    app_window.inventory_tab._sort()
    assert auto_confirm == ["Open a save first."]


def test_sort_that_cannot_fit_refuses_and_changes_nothing(app_window, sample_copy, auto_confirm):
    import copy
    tab = _open_inventory(app_window, sample_copy)
    player = app_window.state.save.profile.player
    template = next(i for i in player.items if i.y >= 1 and not i.equipped)
    player.items.extend(copy.deepcopy(template) for _ in range(30))  # a broken save: too many for the region
    app_window.state.set_pending([])
    app_window.refresh_all()
    tab._sort()
    assert any("refusing to drop" in message for message in auto_confirm)
    assert app_window.state.pending == []


def test_a_kept_sort_saves_and_reloads_sorted_with_the_hotbar_intact(app_window, sample_copy):
    from fch_editor.load import load_file
    tab = _open_inventory(app_window, sample_copy)
    hotbar_before = {(i.x, i.y): i for i in load_file(sample_copy).profile.player.items if i.y == 0}
    tab._sort()
    app_window.save_in_place()  # the confirm-changes dialog is auto-confirmed
    reloaded = load_file(sample_copy).profile.player
    assert {(i.x, i.y): i for i in reloaded.items if i.y == 0} == hotbar_before
    names = [tab._sort_label(i.prefab_hash).lower()
             for i in sorted(reloaded.items, key=lambda i: (i.y, i.x)) if i.y >= 1 and not i.equipped]
    assert names == sorted(names) and len(names) > 3


def test_the_real_prompt_leaves_the_grid_it_asks_about_visible(app_window, sample_copy, monkeypatch):
    from fch_editor.gui import dialogs as dialogs_mod
    monkeypatch.setattr(dialogs_mod, "confirm_sort", _REAL_CONFIRM_SORT)
    seen = {}

    def patched_wait(self):
        self.update()
        seen["dialog_top"] = self.winfo_rooty()
        tab = app_window.inventory_tab
        seen["tiles_bottom"] = max(b.winfo_rooty() + b.winfo_height() for b in tab._slot_buttons.values())
        seen["dialog_left"] = self.winfo_rootx()
        self.destroy()

    monkeypatch.setattr(tk.Toplevel, "wait_window", patched_wait)
    tab = _open_inventory(app_window, sample_copy)
    tab._sort()
    assert seen["dialog_top"] >= seen["tiles_bottom"], "the prompt sits on top of the grid it is asking about"


def test_app_shortcuts_are_blocked_while_the_sort_prompt_is_open(app_window, sample_copy, monkeypatch):
    """A Tk grab does not stop bind_all shortcuts: Ctrl+S on the prompt used to save
    and reload the state underneath it, and a later Undo then restored a stale
    pending list onto the new state."""
    from fch_editor.gui import dialogs as dialogs_mod
    tab = _open_inventory(app_window, sample_copy)  # before the stubs, or this setup call trips them
    monkeypatch.setattr(dialogs_mod, "confirm_sort", _REAL_CONFIRM_SORT)
    reached = []
    monkeypatch.setattr(app_window, "save_in_place", lambda: reached.append("save"))
    monkeypatch.setattr(app_window, "open_file", lambda *a, **k: reached.append("open"))

    def patched_wait(self):
        self.update()
        self.focus_force()
        self.update()
        target = next(w for w in _walk_widgets(self) if w.winfo_class() == "TButton" and w.cget("text") == "Undo")
        for keys in ("<Control-s>", "<Control-o>"):
            target.event_generate(keys)
            self.update()
        self.destroy()

    monkeypatch.setattr(tk.Toplevel, "wait_window", patched_wait)
    tab._sort()
    assert reached == []


def _walk_widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk_widgets(child)


def test_undo_does_nothing_if_the_state_was_replaced_while_the_prompt_was_up(app_window, sample_copy, sample_bytes,
                                                                             tmp_path, monkeypatch):
    from fch_editor.gui import dialogs as dialogs_mod
    other = tmp_path / "other.fch"
    other.write_bytes(sample_bytes)
    tab = _open_inventory(app_window, sample_copy)
    _select_slot(tab, "4,2")
    tab.stack_var.set("41")
    tab._apply_set()  # a pending edit that the "restore" would otherwise resurrect

    def replace_state_then_undo(parent):
        app_window.open_file(other)  # e.g. File > Open from the menu bar, which a Tk grab does not block
        return False

    monkeypatch.setattr(dialogs_mod, "confirm_sort", replace_state_then_undo)
    tab._sort()
    assert app_window.state.pending == []  # the fresh state is untouched by the stale Undo
    assert "undone" not in app_window.status_var.get().lower()


def test_undo_does_nothing_if_the_pending_edits_were_discarded_meanwhile(app_window, sample_copy, monkeypatch):
    from fch_editor.gui import dialogs as dialogs_mod
    tab = _open_inventory(app_window, sample_copy)
    _select_slot(tab, "4,2")
    tab.stack_var.set("41")
    tab._apply_set()

    def discard_then_undo(parent):
        app_window.state.discard()  # File > Discard Pending Changes while the prompt is up
        return False

    monkeypatch.setattr(dialogs_mod, "confirm_sort", discard_then_undo)
    tab._sort()
    assert app_window.state.pending == []  # not resurrected by Undo


def test_undo_returns_to_the_view_the_user_was_in(app_window, sample_copy, monkeypatch):
    from fch_editor.gui import dialogs as dialogs_mod
    tab = _open_inventory(app_window, sample_copy)
    assert tab.view_var.get() == "list"
    monkeypatch.setattr(dialogs_mod, "confirm_sort", lambda parent: False)
    tab._sort()
    app_window.update()
    assert tab.view_var.get() == "list" and tab.tree.winfo_ismapped()


def test_closing_the_app_while_the_prompt_is_up_does_not_raise(app_window, sample_copy, monkeypatch):
    """Once the app is destroyed, even winfo_exists() raises TclError; the Undo path must not
    then try to refresh a dead window."""
    from fch_editor.gui import dialogs as dialogs_mod
    tab = _open_inventory(app_window, sample_copy)

    def dead(*_a):
        raise tk.TclError("application has been destroyed")

    monkeypatch.setattr(dialogs_mod, "confirm_sort", lambda parent: False)
    monkeypatch.setattr(tab, "winfo_exists", dead)
    refreshed = []
    monkeypatch.setattr(app_window, "refresh_all", lambda: refreshed.append(1))
    tab._sort()  # returns quietly instead of raising, and touches nothing afterwards
    assert refreshed == [1]  # only apply_edit's own refresh; the Undo path never ran
