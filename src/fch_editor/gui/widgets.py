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
    (plain ttk.Combobox only jump-scrolls to a prefix match)."""

    def __init__(self, master=None, values: list[str] = (), **kwargs):
        super().__init__(master, **kwargs)
        self._all = list(values)
        self["values"] = self._all
        self.bind("<KeyRelease>", self._on_key)

    def set_values(self, values: list[str]) -> None:
        self._all = list(values)
        self["values"] = self._all

    def _on_key(self, event) -> None:
        if event.keysym in ("Up", "Down", "Left", "Right", "Return", "Escape", "Tab"):
            return
        typed = self.get()
        self["values"] = [v for v in self._all if typed.lower() in v.lower()] if typed else self._all


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
