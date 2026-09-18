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


def test_inventory_tab_copy_preserves_quality_and_stays_selected(app_window, sample_copy):
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
