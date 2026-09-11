"""Tk application shell: menu, tabs, status bar, and the open/save flow.

Every write still goes through `edits.pipeline.write_result`; the GUI's own
confirmation dialog and running-game warning stand in for the CLI's
`--dry-run`/printed diff and `--force` flag.
"""
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from .. import safe_io
from ..catalog.items import ItemCatalog
from ..edits.pipeline import UnsafeWrite, write_result
from ..errors import FchError
from ..load import load_file
from . import dialogs
from .state import AppState
from .tabs.character import CharacterTab
from .tabs.inventory import InventoryTab
from .tabs.overview import OverviewTab
from .tabs.skills import SkillsTab
from .widgets import set_widgets_state


def default_save_dir() -> Path:
    candidate = Path.home() / "AppData/LocalLow/IronGate/Valheim/characters_local"
    return candidate if candidate.is_dir() else Path.home()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Valheim Save Editor")
        self.geometry("760x560")
        self.catalog = ItemCatalog.load()
        self.state: AppState | None = None

        self._build_menu()
        self.status_var = tk.StringVar(value="Open a .fch save to begin.")
        ttk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken").pack(
            side="bottom", fill="x")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)
        self.overview_tab = OverviewTab(notebook)
        self.skills_tab = SkillsTab(notebook, self)
        self.character_tab = CharacterTab(notebook, self)
        self.inventory_tab = InventoryTab(notebook, self)
        for tab, label in ((self.overview_tab, "Overview"), (self.skills_tab, "Skills"),
                           (self.character_tab, "Character"), (self.inventory_tab, "Inventory")):
            notebook.add(tab, text=label)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Open…", command=lambda: self.open_file(), accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self.save_in_place, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As…", command=self.save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Discard Pending Changes", command=self.discard_pending)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menubar)
        self.bind_all("<Control-o>", lambda _e: self.open_file())
        self.bind_all("<Control-s>", lambda _e: self.save_in_place())

    # --- open / save -----------------------------------------------------

    def open_file(self, path: Path | None = None) -> None:
        if self.state is not None and self.state.dirty:
            if not dialogs.ask_yes_no(self, "Discard unsaved changes and open a different save?"):
                return
        if path is None:
            chosen = filedialog.askopenfilename(
                title="Open Valheim character save", initialdir=str(default_save_dir()),
                filetypes=[("Valheim character save", "*.fch"), ("All files", "*.*")], parent=self)
            if not chosen:
                return
            path = Path(chosen)
        try:
            save = load_file(path)
        except (OSError, FchError) as e:
            self.show_error(f"Could not open {path}:\n{e}")
            return
        self.state = AppState(save)
        self.status_var.set(f"Opened {path}" if save.writable else
                            f"Opened {path} — READ ONLY: {'; '.join(save.reasons)}")
        self.refresh_all()

    def save_in_place(self) -> None:
        self._save(in_place=True)

    def save_as(self) -> None:
        self._save(in_place=False)

    def _save(self, in_place: bool) -> None:
        if self.state is None:
            return
        if not self.state.dirty:
            dialogs.info(self, "There are no pending changes to save.")
            return
        result = self.state.preview()
        if not dialogs.confirm_changes(self, result.changes):
            return
        if in_place:
            target = self.state.save.path
        else:
            chosen = filedialog.asksaveasfilename(
                title="Save Valheim character save as", initialdir=str(
                    self.state.save.path.parent if self.state.save.path else default_save_dir()),
                initialfile=self.state.save.path.name if self.state.save.path else "character.fch",
                defaultextension=".fch", filetypes=[("Valheim character save", "*.fch")], parent=self)
            if not chosen:
                return
            target = Path(chosen)
        # The GUI's own dialogs above stand in for the CLI's --force: the save
        # dialog already confirmed overwrite, and the check below confirms
        # a running game, so `force=True` here does not skip a safety check
        # the user hasn't already seen.
        if safe_io.is_game_running() and not dialogs.confirm_game_running(self):
            return
        try:
            backup = write_result(result, self.state.save.path, None if in_place else target, in_place, force=True)
        except UnsafeWrite as e:
            self.show_error(str(e))
            return
        self._reload_after_write(target, backup)

    def _reload_after_write(self, path: Path, backup: Path | None) -> None:
        self.state = self.state.rebased_on(load_file(path))
        self.refresh_all()
        msg = f"Saved to {path}"
        if backup:
            msg += f" (previous version backed up to {backup})"
        self.status_var.set(msg)

    def discard_pending(self) -> None:
        if self.state is None or not self.state.dirty:
            return
        if dialogs.ask_yes_no(self, "Discard all pending changes?"):
            self.state.discard()
            self.refresh_all()
            self.status_var.set("Pending changes discarded")

    def on_close(self) -> None:
        if self.state is not None and self.state.dirty:
            if not dialogs.ask_yes_no(self, "You have unsaved changes. Quit without saving?"):
                return
        self.destroy()

    # --- edits called by tabs --------------------------------------------

    def apply_edit(self, edit) -> bool:
        return self.apply_edits_batch([edit])

    def apply_edits_batch(self, edit_list: list) -> bool:
        if self.state is None:
            self.show_error("Open a save first.")
            return False
        before = list(self.state.pending)
        for edit in edit_list:
            self.state.add(edit)
        try:
            self.state.preview()  # validate now, so a bug surfaces immediately, not at Save time
        except FchError as e:  # covers EditError and UnsafeWrite
            self.state.set_pending(before)
            self.show_error(str(e))
            return False
        self.refresh_all()
        self.status_var.set(f"{len(self.state.pending)} pending change(s) — not yet saved")
        return True

    def show_error(self, message: str) -> None:
        dialogs.error(self, message)

    def refresh_all(self) -> None:
        if self.state is None:
            return
        profile = self.state.preview().profile
        self.overview_tab.refresh(self.state.save, self.catalog)
        self.skills_tab.refresh(profile)
        self.character_tab.refresh(profile)
        self.inventory_tab.refresh(profile)
        writable = self.state.save.writable
        for tab in (self.skills_tab, self.character_tab, self.inventory_tab):
            set_widgets_state(tab, writable)
        star = " *" if self.state.dirty else ""
        name = self.state.save.path.name if self.state.save.path else "<unsaved>"
        self.title(f"Valheim Save Editor — {name}{star}")


def main(path: Path | None = None) -> None:
    app = App()
    if path is not None:
        app.open_file(path)
    app.mainloop()
