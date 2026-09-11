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
