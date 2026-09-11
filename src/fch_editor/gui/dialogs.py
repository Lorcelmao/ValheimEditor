"""Modal dialogs: change confirmation, and thin wrappers around messagebox."""
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from ..render import diff_text


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
