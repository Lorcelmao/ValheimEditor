"""Exercises the real dialog windows (not the monkeypatched stand-ins
test_gui_smoke.py uses for the app-level flow), so a layout bug that leaves a
button at 0x0 and unclickable — as `confirm_changes` once did, see
gui/dialogs.py's packing-order comment — gets caught here.
"""
import tkinter as tk

import pytest

from fch_editor.gui import dialogs

pytest.importorskip("tkinter")


@pytest.fixture
def root():
    r, last_error = None, None
    for _attempt in range(3):  # creating a Tk root right after destroying one can transiently fail
        try:
            r = tk.Tk()
            break
        except tk.TclError as e:
            last_error = e
    if r is None:
        pytest.skip(f"no display available for Tk: {last_error}")
    # Positioned off-screen rather than withdrawn: a withdrawn parent prevents
    # a `.transient()` child from ever being realized, so pack() never
    # resolves real geometry for it either (everything reports 1x1) — which
    # would make this file unable to tell a real layout bug from a fixture
    # artifact. Off-screen keeps the window mapped without being visible.
    r.geometry("760x560+2000+2000")
    r.update()
    yield r
    r.destroy()


def _click_button(win: tk.Toplevel, text: str) -> dict:
    """Find a named button inside `win`, record its geometry, then invoke it."""
    found = {"button": None}

    def walk(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "TButton" and child.cget("text") == text:
                found["button"] = child
                return
            walk(child)

    walk(win)
    btn = found["button"]
    info = {"found": btn is not None, "viewable": btn.winfo_viewable() if btn else None,
           "width": btn.winfo_width() if btn else 0, "height": btn.winfo_height() if btn else 0}
    if btn is not None:
        btn.invoke()
    return info


@pytest.mark.parametrize("button_text,expected", [("Write to file", True), ("Cancel", False)])
def test_confirm_changes_buttons_are_visible_and_clickable(root, monkeypatch, button_text, expected):
    def patched_wait(self):
        self.update()
        info["result"] = _click_button(self, button_text)

    info = {}
    monkeypatch.setattr(tk.Toplevel, "wait_window", patched_wait)
    result = dialogs.confirm_changes(root, [("player.skills[Run].level", 100.0, 50.0)])

    assert info["result"]["found"], "button not found in the dialog's widget tree"
    assert info["result"]["viewable"] == 1, "button exists but is not viewable (likely 0x0 from a pack-order bug)"
    assert info["result"]["width"] > 10 and info["result"]["height"] > 10
    assert result is expected


def test_confirm_changes_with_no_changes_shows_info_and_returns_false(root, monkeypatch):
    shown = []
    monkeypatch.setattr(dialogs, "info", lambda parent, msg: shown.append(msg))
    assert dialogs.confirm_changes(root, []) is False
    assert shown  # the "nothing to save" message was shown, no Toplevel was ever created


def test_confirm_changes_closing_the_window_counts_as_cancel(root, monkeypatch):
    def patched_wait(self):
        self.update()
        self.protocol("WM_DELETE_WINDOW")  # can't invoke a WM close event directly; call the handler
        # The handler was registered via win.protocol(...); fetch and call it.
        handler_name = self.tk.call("wm", "protocol", self._w, "WM_DELETE_WINDOW")
        self.tk.call(handler_name) if handler_name else self.destroy()

    monkeypatch.setattr(tk.Toplevel, "wait_window", patched_wait)
    assert dialogs.confirm_changes(root, [("name", "A", "B")]) is False


def test_all_dialog_buttons_have_a_sane_minimum_size(root, monkeypatch):
    """A blanket check so a future dialog with the same pack-order mistake fails loudly."""
    sizes = []

    def patched_wait(self):
        self.update()

        def walk(widget):
            for child in widget.winfo_children():
                if child.winfo_class() == "TButton":
                    sizes.append((child.cget("text"), child.winfo_viewable(),
                                 child.winfo_width(), child.winfo_height()))
                walk(child)

        walk(self)
        self.destroy()

    monkeypatch.setattr(tk.Toplevel, "wait_window", patched_wait)
    dialogs.confirm_changes(root, [("name", "A", "B"), ("player.beard", "BeardNone", "Beard5")])
    assert sizes, "no buttons found to check"
    for text, viewable, width, height in sizes:
        assert viewable == 1 and width > 10 and height > 10, f"button {text!r} is not properly visible: {(viewable, width, height)}"


# --- item picker ---------------------------------------------------------------

from fch_editor.catalog.items import ItemCatalog  # noqa: E402


@pytest.fixture(scope="module")
def entries():
    return ItemCatalog.load().entries()


def test_search_catalog_empty_query_matches_nothing(entries):
    assert dialogs.search_catalog(entries, "") == ([], 0)
    assert dialogs.search_catalog(entries, "   ") == ([], 0)


def test_search_catalog_finds_by_either_name(entries):
    by_display, _ = dialogs.search_catalog(entries, "tunic")
    by_prefab, _ = dialogs.search_catalog(entries, "ArmorBronzeChest")
    assert any(e.prefab == "ArmorBronzeChest" for e in by_display)
    assert any(e.prefab == "ArmorBronzeChest" for e in by_prefab)
    lower, _ = dialogs.search_catalog(entries, "armorbronzechest")
    assert [e.prefab for e in lower] == [e.prefab for e in by_prefab]


def test_search_catalog_caps_but_reports_the_true_total(entries):
    shown, total = dialogs.search_catalog(entries, "a")
    assert len(shown) == dialogs.PICKER_CAP < total
    small, small_total = dialogs.search_catalog(entries, "a", cap=5)
    assert len(small) == 5 and small_total == total


def test_picker_opens_empty_with_a_prompt_and_usable_buttons(root, entries):
    root.update()
    picker = dialogs.ItemPicker(root, entries)
    picker.win.update()
    assert picker.result_buttons() == []  # the catalogue is never drawn
    assert "Type to search" in picker.status_var.get() and f"{len(entries):,}" in picker.status_var.get()
    cancel = next(w for w in _walk(picker.win) if w.winfo_class() == "TButton" and w.cget("text") == "Cancel")
    assert cancel.winfo_viewable() and cancel.winfo_width() > 5 and cancel.winfo_height() > 5
    assert picker.search_entry.winfo_height() > 5
    picker.cancel()


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def _type(picker, text):
    picker.search_var.set(text)
    picker.win.update()
    picker.render()  # skip the debounce wait


def test_picker_renders_matches_and_choosing_returns_the_prefab(root, entries):
    picker = dialogs.ItemPicker(root, entries)
    _type(picker, "ArmorBronzeChest")
    buttons = picker.result_buttons()
    assert buttons
    target = next(b for b in buttons if "ArmorBronzeChest" in b.cget("text"))
    assert "\n" in target.cget("text")  # display name and prefab on separate lines
    target.invoke()
    assert picker.result == "ArmorBronzeChest"


def test_picker_clearing_the_search_returns_to_the_prompt_not_everything(root, entries):
    picker = dialogs.ItemPicker(root, entries)
    _type(picker, "tunic")
    assert picker.result_buttons()
    _type(picker, "")
    assert picker.result_buttons() == []
    assert "Type to search" in picker.status_var.get()
    picker.cancel()


def test_picker_broad_query_stays_capped_and_says_so(root, entries):
    picker = dialogs.ItemPicker(root, entries)
    _type(picker, "a")
    assert len(picker.result_buttons()) == dialogs.PICKER_CAP
    assert f"showing {dialogs.PICKER_CAP} of" in picker.status_var.get()
    picker.cancel()


def test_picker_no_match_names_the_escape_hatch(root, entries):
    picker = dialogs.ItemPicker(root, entries)
    _type(picker, "zzzznotanitem")
    assert picker.result_buttons() == []
    assert "allow unknown item" in picker.status_var.get()
    picker.cancel()


def test_picker_debounces_typing_into_one_render(root, entries, monkeypatch):
    picker = dialogs.ItemPicker(root, entries)
    calls = []
    real = picker.render
    monkeypatch.setattr(picker, "render", lambda: (calls.append(1), real()))
    for text in ("t", "tu", "tun", "tuni", "tunic"):
        picker.search_var.set(text)
    picker.win.after(dialogs._PICKER_DEBOUNCE_MS + 200, lambda: None)
    import time
    deadline = time.time() + 1.5
    while time.time() < deadline and not calls:
        root.update()
        time.sleep(0.02)
    time.sleep(0.05)
    root.update()
    assert len(calls) == 1
    picker.cancel()


def test_picker_cancel_escape_and_close_really_close_and_return_none(root, entries):
    for how in ("cancel", "escape", "close"):
        picker = dialogs.ItemPicker(root, entries)
        _type(picker, "tunic")
        picker.result = "SomethingStale"  # so None below can only come from the handler
        if how == "cancel":
            picker.cancel()
        elif how == "escape":
            picker.win.focus_force()  # key events go to the focus window; an off-screen one has none
            picker.win.update()
            picker.search_entry.event_generate("<Escape>")
            picker.win.update()
        else:
            picker.win.tk.call(picker.win.protocol("WM_DELETE_WINDOW"))
        assert picker.result is None, how
        assert not picker.win.winfo_exists(), how


def test_picker_enter_inside_the_debounce_window_uses_what_is_typed_now(root, entries):
    picker = dialogs.ItemPicker(root, entries)
    _type(picker, "tunic")
    assert picker.result_buttons()
    picker.search_var.set("ArmorBronzeChest")  # typed; the debounced render has not run yet
    picker._choose_first()
    assert picker.result == "ArmorBronzeChest"


def test_picker_enter_with_nothing_typed_does_nothing(root, entries):
    picker = dialogs.ItemPicker(root, entries)
    picker._choose_first()
    assert picker.result is None and picker.win.winfo_exists()
    picker.cancel()


def test_picker_enter_takes_the_first_result(root, entries):
    picker = dialogs.ItemPicker(root, entries)
    _type(picker, "ArmorBronzeChest")
    first = picker.result_buttons()[0].cget("text").split("\n")[-1]
    picker._choose_first()
    assert picker.result == first


def test_choose_item_is_modal_and_returns_the_choice(root, entries, monkeypatch):
    import time

    def fake_wait(self):
        entry = next(w for w in _walk(self) if w.winfo_class() == "TEntry")
        entry.insert(0, "ArmorBronzeChest")
        buttons = []
        deadline = time.time() + 1.5
        while time.time() < deadline and not buttons:  # the debounce has to elapse
            self.update()
            buttons = [w for w in _walk(self) if w.winfo_class() == "Button"]
            time.sleep(0.02)
        buttons[0].invoke()

    monkeypatch.setattr(tk.Toplevel, "wait_window", fake_wait)
    monkeypatch.setattr(tk.Toplevel, "wait_visibility", lambda self: self.update())
    assert dialogs.choose_item(root, entries) == "ArmorBronzeChest"


# --- sort prompt ------------------------------------------------------------------

@pytest.mark.parametrize("button_text,expected", [("Keep this order", True), ("Undo", False)])
def test_confirm_sort_buttons_are_visible_and_clickable(root, monkeypatch, button_text, expected):
    info = {}

    def patched_wait(self):
        self.update()
        info["result"] = _click_button(self, button_text)

    monkeypatch.setattr(tk.Toplevel, "wait_window", patched_wait)
    result = dialogs.confirm_sort(root)
    assert info["result"]["found"]
    assert info["result"]["viewable"] == 1 and info["result"]["width"] > 10 and info["result"]["height"] > 10
    assert result is expected


@pytest.mark.parametrize("how", ["escape", "enter", "close"])
def test_confirm_sort_escape_enter_and_close_all_mean_undo(root, monkeypatch, how):
    def patched_wait(self):
        self.update()
        self.focus_force()  # key events go to the focus window; an off-screen one has none
        self.update()
        if how == "close":
            self.tk.call(self.protocol("WM_DELETE_WINDOW"))
        else:
            focused = self.focus_get() or self
            focused.event_generate("<Escape>" if how == "escape" else "<Return>")
            self.update()
        assert not self.winfo_exists(), how

    monkeypatch.setattr(tk.Toplevel, "wait_window", patched_wait)
    assert dialogs.confirm_sort(root) is False


def test_confirm_sort_focuses_undo_so_a_stray_keypress_cannot_keep(root, monkeypatch):
    seen = {}

    def patched_wait(self):
        self.update()
        seen["focus"] = self.focus_lastfor().cget("text")  # the widget that gets focus when the window does
        self.destroy()

    monkeypatch.setattr(tk.Toplevel, "wait_window", patched_wait)
    dialogs.confirm_sort(root)
    assert seen["focus"] == "Undo"


def test_confirm_sort_sits_in_the_bottom_right_of_the_parent(root, monkeypatch):
    rects = {}

    def patched_wait(self):
        self.update()
        rects["dialog"] = (self.winfo_rootx(), self.winfo_rooty(), self.winfo_width(), self.winfo_height())
        self.destroy()

    monkeypatch.setattr(tk.Toplevel, "wait_window", patched_wait)
    dialogs.confirm_sort(root)
    x, y, w, h = rects["dialog"]
    assert x + w <= root.winfo_rootx() + root.winfo_width()
    assert y + h <= root.winfo_rooty() + root.winfo_height()
    assert y >= root.winfo_rooty() + root.winfo_height() // 2  # the lower half, not over the top


def test_confirm_sort_enter_presses_the_focused_button(root, monkeypatch):
    def patched_wait(self):
        self.update()
        self.focus_force()
        keep = next(w for w in _walk_all(self) if w.winfo_class() == "TButton" and w.cget("text") == "Keep this order")
        keep.focus_force()
        self.update()
        keep.event_generate("<Return>")
        self.update()

    monkeypatch.setattr(tk.Toplevel, "wait_window", patched_wait)
    assert dialogs.confirm_sort(root) is True


def _walk_all(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk_all(child)


def test_confirm_sort_sizes_itself_from_its_contents(root, monkeypatch):
    seen = {}

    def patched_wait(self):
        self.update()
        seen["fits"] = self.winfo_width() >= self.winfo_reqwidth() and self.winfo_height() >= self.winfo_reqheight()
        self.destroy()

    monkeypatch.setattr(tk.Toplevel, "wait_window", patched_wait)
    root.tk.call("tk", "scaling", 2.5)  # a scaled display makes the same text wider and taller
    dialogs.confirm_sort(root)
    assert seen["fits"]
