"""Modal dialogs: change confirmation, the item picker, and thin wrappers around messagebox."""
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from ..render import diff_text
from .widgets import ScrollableFrame


def error(parent, message: str) -> None:
    messagebox.showerror("Error", message, parent=parent)


def info(parent, message: str) -> None:
    messagebox.showinfo("Valheim Save Editor", message, parent=parent)


def ask_yes_no(parent, message: str) -> bool:
    return messagebox.askyesno("Valheim Save Editor", message, parent=parent)


def confirm_game_running(parent) -> bool:
    return messagebox.askyesno(
        "Valheim is running",
        "Valheim appears to be running and rewrites saves on exit, which would undo this write.\n\n"
        "Write anyway?",
        icon="warning", parent=parent,
    )


def confirm_changes(parent, changes: list[tuple[str, object, object]]) -> bool:
    """Show exactly what will change; return True only if the user confirms."""
    if not changes:
        info(parent, "There are no pending changes to save.")
        return False

    win = tk.Toplevel(parent)
    win.title("Confirm changes")
    win.transient(parent)
    win.grab_set()
    win.geometry("520x360")

    result = {"ok": False}

    def on_ok():
        result["ok"] = True
        win.destroy()

    def on_cancel():
        win.destroy()

    # Pack the button bar FIRST, from the bottom: with an explicit window size,
    # a widget packed afterwards with expand=True otherwise claims the entire
    # fixed cavity before the buttons are laid out, leaving them 0x0 and unclickable.
    buttons = ttk.Frame(win)
    buttons.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
    ttk.Button(buttons, text="Cancel", command=on_cancel).pack(side="right")
    ttk.Button(buttons, text="Write to file", command=on_ok).pack(side="right", padx=(0, 6))

    ttk.Label(win, text=f"{len(changes)} field(s) will change:", anchor="w").pack(fill="x", padx=8, pady=(8, 0))
    text = scrolledtext.ScrolledText(win, wrap="word")
    text.insert("1.0", diff_text(changes))
    text.configure(state="disabled")
    text.pack(fill="both", expand=True, padx=8, pady=8)

    win.protocol("WM_DELETE_WINDOW", on_cancel)
    win.wait_window()
    return result["ok"]


# --- item picker -----------------------------------------------------------

# Rendering a Tk widget is far slower than a DOM node, so the full catalogue
# (1,164 entries) is never drawn: the picker opens EMPTY and draws only what a
# search matches. The cap is just a guard for a deliberately broad query -- a
# single letter matches hundreds -- not the main mechanism.
PICKER_CAP = 150
_PICKER_DEBOUNCE_MS = 150
_PICKER_COLUMNS = 3


def search_catalog(entries, query: str, cap: int = PICKER_CAP):
    """Matches for the picker as `(first cap entries, total match count)`.

    Matches the in-game name OR the prefab name, case-insensitive substring --
    the same rule the add-form combobox already uses. An empty query matches
    NOTHING, deliberately and explicitly: falling through to "match everything"
    is exactly what would draw all 1,164 widgets and freeze the window.
    """
    q = query.strip().lower()
    if not q:
        return [], 0
    matches = [e for e in entries if q in (e.display or "").lower() or q in e.prefab.lower()]
    matches.sort(key=lambda e: (e.display or e.prefab).lower())
    return matches[:cap], len(matches)


class ItemPicker:
    """Search-first grid picker. Built without grabbing input so it can be
    driven directly in tests; `choose_item` adds the modal behaviour."""

    def __init__(self, parent, entries):
        self.entries = list(entries)
        self.result: str | None = None
        self._after = None

        self.win = win = tk.Toplevel(parent)
        win.title("Choose an item")
        win.transient(parent)
        win.geometry("660x460")
        win.protocol("WM_DELETE_WINDOW", self.cancel)
        win.bind("<Escape>", lambda _e: self.cancel())

        # Bottom bar and search row are packed BEFORE the results area, for the
        # same reason as everywhere else in this app: with an explicit geometry,
        # a widget packed earlier with expand=True claims the whole cavity and
        # squeezes later siblings to 0x0.
        buttons = ttk.Frame(win)
        buttons.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        ttk.Button(buttons, text="Cancel", command=self.cancel).pack(side="right")

        top = ttk.Frame(win)
        top.pack(side="top", fill="x", padx=8, pady=(8, 0))
        ttk.Label(top, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(top, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.search_entry.bind("<Return>", lambda _e: self._choose_first())
        self.search_var.trace_add("write", self._on_query_changed)

        self.status_var = tk.StringVar()
        ttk.Label(win, textvariable=self.status_var, wraplength=620, justify="left",
                  foreground="gray").pack(side="top", fill="x", padx=8, pady=(6, 0))

        scrolling = ScrollableFrame(win)
        scrolling.pack(side="top", fill="both", expand=True, padx=8, pady=8)
        self.canvas = scrolling.canvas
        self.results = scrolling.body

        self.render()
        self.search_entry.focus_set()

    # --- behaviour -----------------------------------------------------

    def _on_query_changed(self, *_args) -> None:
        # Debounced: without it, typing "ArmorBronze" rebuilds the result grid
        # eleven times, once per keystroke.
        if self._after is not None:
            self.win.after_cancel(self._after)
        self._after = self.win.after(_PICKER_DEBOUNCE_MS, self.render)

    def render(self) -> None:
        if self._after is not None:  # called directly (Enter, tests): the pending one is redundant
            self.win.after_cancel(self._after)
            self._after = None
        if not self.win.winfo_exists():
            return
        for child in self.results.winfo_children():
            child.destroy()
        query = self.search_var.get().strip()
        shown, total = search_catalog(self.entries, query)

        if not query:
            self.status_var.set(f"Type to search {len(self.entries):,} items.")
        elif total == 0:
            self.status_var.set(
                f"Nothing matches “{query}”. You can still type it into the Name field and tick "
                "“allow unknown item” — useful for an item from a game version newer than this catalog.")
        elif total > len(shown):
            self.status_var.set(f"showing {len(shown)} of {total} — keep typing to narrow")
        else:
            self.status_var.set(f"{total} item{'s' if total != 1 else ''}")

        for i, entry in enumerate(shown):
            label = f"{entry.display}\n{entry.prefab}" if entry.display and entry.display != entry.prefab else entry.prefab
            tk.Button(self.results, text=label, width=26, height=2, justify="left", anchor="w",
                      command=lambda p=entry.prefab: self.choose(p)).grid(
                row=i // _PICKER_COLUMNS, column=i % _PICKER_COLUMNS, padx=2, pady=2, sticky="w")
        self.canvas.yview_moveto(0)

    def result_buttons(self):
        return [w for w in self.results.winfo_children() if isinstance(w, tk.Button)]

    def _choose_first(self) -> None:
        if self._after is not None:
            self.render()  # Enter inside the debounce window must act on what is typed NOW
        buttons = self.result_buttons()
        if buttons:
            buttons[0].invoke()

    def choose(self, prefab: str) -> None:
        self.result = prefab
        self._close()

    def cancel(self) -> None:
        self.result = None
        self._close()

    def _close(self) -> None:
        if self._after is not None:
            self.win.after_cancel(self._after)
            self._after = None
        self.win.destroy()


def confirm_sort(parent) -> bool:
    """Ask "keep this order?" about a sort that is ALREADY on screen. True = keep.

    Modal, so nothing else can be edited between the sort and the answer -- that
    is what lets Undo restore the pending list exactly. A Tk grab does not stop the
    app-wide Ctrl+S / Ctrl+O shortcuts (they are bound on every window), so those
    are swallowed here too. Small and parked at the bottom-right of the app window,
    over the edit forms, so the grid it is asking about stays visible. Undo is the
    default (initial focus, Escape, closing the window): an accidental keypress
    must not lock in a rearrangement. Enter presses whichever button has focus.
    """
    top = parent.winfo_toplevel()
    win = tk.Toplevel(top)
    win.title("Keep this order?")
    win.transient(top)
    win.resizable(False, False)
    result = {"keep": False}

    def keep():
        result["keep"] = True
        win.destroy()

    def undo():
        win.destroy()

    # Button bar first, from the bottom -- same pack-order rule as confirm_changes.
    buttons = ttk.Frame(win)
    buttons.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
    undo_button = ttk.Button(buttons, text="Undo", command=undo)
    undo_button.pack(side="right")
    ttk.Button(buttons, text="Keep this order", command=keep).pack(side="right", padx=(0, 6))
    ttk.Label(win, justify="left", wraplength=420, text=(
        "The inventory below the hotbar is sorted. Equipped items stayed put.\n"
        "Nothing is written to the file until you save.")).pack(anchor="w", padx=10, pady=(10, 6))

    # Sized from what the widgets ask for, not a fixed pixel box: a scaled display
    # makes the same text wider and taller.
    win.update_idletasks()
    width, height = max(win.winfo_reqwidth(), 400), win.winfo_reqheight()
    x = top.winfo_rootx() + top.winfo_width() - width - 12
    y = top.winfo_rooty() + top.winfo_height() - height - 48
    win.geometry(f"{width}x{height}+{x}+{y}")

    def press_enter(_event):
        focused = win.focus_get()
        (focused if isinstance(focused, ttk.Button) else undo_button).invoke()

    win.protocol("WM_DELETE_WINDOW", undo)
    win.bind("<Escape>", lambda _e: undo())
    win.bind("<Return>", press_enter)
    for shortcut in ("<Control-s>", "<Control-o>"):
        win.bind(shortcut, lambda _e: "break")  # "break" stops the app's bind_all handler
    win.grab_set()
    undo_button.focus_set()
    win.wait_window()
    return result["keep"]


def choose_item(parent, entries) -> str | None:
    """Modal search-first picker. Returns a prefab name, or None if cancelled."""
    picker = ItemPicker(parent, entries)
    picker.win.wait_visibility()
    picker.win.grab_set()
    picker.win.wait_window()
    return picker.result
