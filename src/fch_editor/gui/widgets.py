"""Small reusable Tk widgets."""
import tkinter as tk
from tkinter import ttk

_STATEFUL_CLASSES = {"TEntry", "TButton", "TCombobox", "TCheckbutton", "TRadiobutton"}


def set_widgets_state(container: tk.Widget, enabled: bool) -> None:
    """Enable/disable every interactive ttk widget under `container` (e.g. to
    grey out an edit tab for a read-only save)."""
    state = "normal" if enabled else "disabled"
    for child in container.winfo_children():
        if child.winfo_class() in _STATEFUL_CLASSES:
            try:
                child.configure(state=state)
            except tk.TclError:
                pass
        set_widgets_state(child, enabled)


class AutocompleteCombobox(ttk.Combobox):
    """A Combobox whose dropdown narrows to entries containing what's typed
    (plain ttk.Combobox only jump-scrolls to a prefix match).

    An entry can show a label that differs from the value it stands for: the
    item catalog lists "Stone Axe (AxeStone)" because that is the name a player
    knows, while the edit underneath takes `AxeStone`. Typing matches against
    either half, and `resolve()` turns whatever is in the box back into a value.
    """

    def __init__(self, master=None, options=(), **kwargs):
        super().__init__(master, **kwargs)
        self.set_options(options)
        self.bind("<KeyRelease>", self._on_key)

    def set_options(self, options) -> None:
        """`options` are `(value, label)` pairs; a bare string is its own label."""
        # Not `_options`: tkinter.Misc._options is a real method the toolkit
        # calls on every configure(), and shadowing it breaks widget creation
        # with a bare "'list' object is not callable".
        self._entries = [(o, o) if isinstance(o, str) else tuple(o) for o in options]
        self._by_label = {label: value for value, label in self._entries}
        self["values"] = [label for _, label in self._entries]

    def resolve(self) -> str:
        """The value the box currently means, ready to hand to an edit.

        Anything that isn't one of our labels is returned as typed -- that is
        what keeps a hand-typed prefab working, including one this catalog has
        never heard of (the "allow unknown item" path).
        """
        text = self.get().strip()
        return self._by_label.get(text, text)

    def _on_key(self, event) -> None:
        if event.keysym in ("Up", "Down", "Left", "Right", "Return", "Escape", "Tab"):
            return
        typed = self.get().strip().lower()
        self["values"] = [
            label for value, label in self._entries
            if not typed or typed in label.lower() or typed in value.lower()
        ]


class LabeledEntry(ttk.Frame):
    """A label + entry pair laid out in one grid row, with a `.value` accessor."""

    def __init__(self, master, label: str, width: int = 20, **kwargs):
        super().__init__(master)
        ttk.Label(self, text=label).pack(side="left")
        self.entry = ttk.Entry(self, width=width, **kwargs)
        self.entry.pack(side="left", padx=(4, 0))

    @property
    def value(self) -> str:
        return self.entry.get()

    @value.setter
    def value(self, text: str) -> None:
        self.entry.delete(0, tk.END)
        self.entry.insert(0, text)
