"""Inventory tab: the owned inventory as a table or as the game's slot grid
(toggle at the top), plus forms to edit/copy/remove a selected item and to add
a new item by prefab name."""
import tkinter as tk
from collections import Counter
from tkinter import ttk

from ...edits import inventory as inv
from ...errors import EditError
from ...stable_hash import stable_hash
from .. import dialogs
from ..widgets import AutocompleteCombobox, ScrollableFrame, keep_enabled

_COLUMNS = ("slot", "item", "stack", "durability", "quality", "equipped", "crafter")


class InventoryTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self._selected_slot: tuple[int, int] | None = None

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(8, 0))
        self.grid_label = ttk.Label(bar, text="grid: -")
        self.grid_label.pack(side="left")
        # Session-only, and List by default so a fresh launch looks exactly as it
        # always did: the desktop app has no settings file to remember it in.
        self.view_var = tk.StringVar(value="list")
        # Marked keep_enabled: on a read-only save set_widgets_state would
        # otherwise disable these radio buttons and trap the user in whichever
        # view they were in. Looking is not editing.
        toggle = keep_enabled(ttk.Frame(bar))
        ttk.Radiobutton(toggle, text="List", variable=self.view_var, value="list",
                        command=self._switch_view).pack(side="left")
        ttk.Radiobutton(toggle, text="Grid", variable=self.view_var, value="grid",
                        command=self._switch_view).pack(side="left", padx=(6, 0))
        toggle.pack(side="right")
        # An edit like any other, so NOT keep_enabled: a read-only save greys it out.
        ttk.Button(bar, text="Sort", command=self._sort).pack(side="right", padx=(0, 12))

        # The two forms below are packed with side="bottom" BEFORE the tree,
        # and the tree (the one expand=True widget) is packed last. Packing
        # order controls space allocation: an expand=True widget packed
        # before fixed-size siblings would claim the whole cavity first and
        # squeeze them to 0x0 — invisible and unclickable — whenever the
        # window is smaller than everything's natural size (as the confirm-
        # changes dialog was; see gui/dialogs.py). Packed this way, the forms
        # always get their natural size and only the tree shrinks/scrolls.
        add_form = ttk.LabelFrame(self, text="Add item")
        self.name_var = tk.StringVar()
        self.add_stack_var = tk.StringVar(value="1")
        self.add_slot_var = tk.StringVar()
        self.add_durability_var = tk.StringVar(value=f"{inv.DEFAULT_DURABILITY:g}")
        self.crafted_var = tk.BooleanVar(value=False)
        self.allow_unknown_var = tk.BooleanVar(value=False)
        ttk.Label(add_form, text="Name:").grid(row=0, column=0, padx=4, pady=4)
        name_cell = ttk.Frame(add_form)
        name_cell.grid(row=0, column=1, padx=4)
        self.name_box = AutocompleteCombobox(name_cell, width=22, textvariable=self.name_var)
        self.name_box.pack(side="left")
        ttk.Button(name_cell, text="Browse\u2026", command=self._browse_items).pack(side="left", padx=(4, 0))
        ttk.Label(add_form, text="Stack:").grid(row=0, column=2, padx=4)
        ttk.Entry(add_form, textvariable=self.add_stack_var, width=6).grid(row=0, column=3)
        ttk.Label(add_form, text="Slot (x,y, optional):").grid(row=0, column=4, padx=4)
        ttk.Entry(add_form, textvariable=self.add_slot_var, width=8).grid(row=0, column=5)
        ttk.Label(add_form, text="Durability:").grid(row=1, column=0, padx=4, pady=4)
        ttk.Entry(add_form, textvariable=self.add_durability_var, width=10).grid(row=1, column=1)
        ttk.Checkbutton(add_form, text="crafted by me", variable=self.crafted_var).grid(row=1, column=2, columnspan=2)
        ttk.Checkbutton(add_form, text="allow unknown item", variable=self.allow_unknown_var).grid(
            row=1, column=4, columnspan=2)
        ttk.Button(add_form, text="Add", command=self._apply_add).grid(row=0, column=6, rowspan=2, padx=8)
        add_form.pack(side="bottom", fill="x", padx=8, pady=(0, 8))

        edit_form = ttk.LabelFrame(self, text="Selected item")
        self.stack_var = tk.StringVar()
        self.durability_var = tk.StringVar()
        self.quality_var = tk.StringVar()
        ttk.Label(edit_form, text="Stack:").grid(row=0, column=0, padx=4, pady=4)
        ttk.Entry(edit_form, textvariable=self.stack_var, width=8).grid(row=0, column=1)
        ttk.Label(edit_form, text="Durability:").grid(row=0, column=2, padx=4)
        ttk.Entry(edit_form, textvariable=self.durability_var, width=10).grid(row=0, column=3)
        # No upper limit, deliberately: the old vanilla max of 4 stopped being a
        # real rule when the Ashlands Forge of Potential started pushing items
        # past it, and no confirmed ceiling exists.
        ttk.Label(edit_form, text="Quality:").grid(row=0, column=4, padx=4)
        ttk.Entry(edit_form, textvariable=self.quality_var, width=6).grid(row=0, column=5)
        ttk.Button(edit_form, text="Apply", command=self._apply_set).grid(row=0, column=6, padx=8)
        ttk.Button(edit_form, text="Copy", command=self._apply_copy).grid(row=0, column=7, padx=(0, 8))
        ttk.Button(edit_form, text="Remove", command=self._apply_remove).grid(row=0, column=8)
        ttk.Label(edit_form, foreground="gray", text=(
            "Quality has no upper limit — the Forge of Potential can push it well past the old vanilla maximum."
        )).grid(row=1, column=0, columnspan=9, sticky="w", padx=4, pady=(0, 4))
        edit_form.pack(side="bottom", fill="x", padx=8, pady=(0, 8))

        # The two views share one container, packed LAST like the tree always
        # was, so the forms above keep their natural size.
        self.view_area = ttk.Frame(self)
        self.view_area.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(self.view_area, columns=_COLUMNS, show="headings", selectmode="browse", height=10)
        for col, width in zip(_COLUMNS, (60, 200, 60, 80, 60, 70, 100)):
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col, width=width, anchor="center" if col not in ("item", "crafter") else "w")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self.grid_frame = ttk.Frame(self.view_area)
        self.grid_warning = ttk.Label(self.grid_frame, foreground="#a15c00", wraplength=560, justify="left")
        self.grid_warning.pack(anchor="w", padx=8, pady=(8, 0))
        # Scrolls because the save sets the grid height (up to 9 rows) and the
        # window is fixed-size. Slots are plain tk.Buttons, which the read-only
        # sweep (ttk classes only) never touches -- that is why they stay
        # clickable on a read-only save. A test pins it, in case they are ever
        # swapped for ttk widgets.
        scrolling = ScrollableFrame(self.grid_frame)
        scrolling.pack(fill="both", expand=True, padx=8, pady=8)
        self.slots_frame = scrolling.body
        self._slot_buttons: dict[tuple[int, int], tk.Button] = {}
        # Items the grid cannot place get their own tiles. NOT kept in
        # _slot_buttons: that is keyed by coordinate, and an item sharing a
        # coordinate with one already in the grid would silently replace its button.
        self._shelf_buttons: list[tuple[tuple[int, int], tk.Button]] = []
        self._shelf_heading: ttk.Label | None = None
        self._shared: dict[tuple[int, int], int] = {}  # coordinate -> how many items claim it
        self._slot_bg = self._slot_selected_bg = ""
        self._profile = None
        self._show_view()

    # --- views ---------------------------------------------------------

    def _show_view(self) -> None:
        if self.view_var.get() == "grid":
            self.tree.pack_forget()
            self.grid_frame.pack(fill="both", expand=True)
        else:
            self.grid_frame.pack_forget()
            self.tree.pack(fill="both", expand=True, padx=8, pady=8)

    def _switch_view(self) -> None:
        self._show_view()
        self.refresh(self._profile)  # the list branch re-selects the current slot itself

    def _reselect_in_tree(self) -> None:
        """Selection is held as a coordinate, so it survives a view switch; the
        tree just has to be told which of its (freshly rebuilt) rows it is."""
        if self._selected_slot is None:
            return
        wanted = f"{self._selected_slot[0]},{self._selected_slot[1]}"
        for row in self.tree.get_children():
            if self.tree.item(row, "values")[0] == wanted:
                self.tree.selection_set(row)
                self.tree.see(row)
                return

    # --- selection: one path for both views ----------------------------

    def _set_selection(self, slot: tuple[int, int], stack, durability, quality) -> None:
        """The single place that turns "this item is selected" into form state,
        whichever view it was clicked in -- two copies would drift apart."""
        self._selected_slot = slot
        self.stack_var.set(str(stack))
        self.durability_var.set(str(durability))
        self.quality_var.set(str(quality))

    def _refuse_shared(self, slot: tuple[int, int]) -> None:
        """Every edit finds its item by coordinate, and with several items on one
        coordinate that is ambiguous (the core refuses rather than guess). So
        such items are view-only, in the list and the grid alike: nothing gets
        selected, the form empties, and the status bar says why."""
        self._selected_slot = None
        for var in (self.stack_var, self.durability_var, self.quality_var):
            var.set("")
        self.app.status_var.set(
            f"{self._shared[slot]} items share slot {slot[0]},{slot[1]} - view-only, because an edit "
            "addressed by slot would be ambiguous.")

    def _on_select(self, _event) -> None:
        sel = self.tree.selection()
        if not sel:
            self._selected_slot = None
            return
        slot_text, _name, stack, durability, quality, *_ = self.tree.item(sel[0], "values")
        slot = inv.parse_slot(slot_text)
        if slot in self._shared:
            self._refuse_shared(slot)
            return
        if slot == self._selected_slot:
            # Already the selected item: this is refresh() putting the selection
            # back after a rebuild, not the user picking a row. Refilling here
            # would throw away whatever they had typed but not yet applied.
            return
        self._set_selection(slot, stack, durability, quality)

    def _on_slot_click(self, slot: tuple[int, int], item) -> None:
        if slot in self._shared:
            self._refuse_shared(slot)
        elif item is None:
            # An empty slot has nothing to edit, but it is exactly what the add
            # form's optional "Slot" field is for -- aim the next add at it.
            self._selected_slot = None
            for var in (self.stack_var, self.durability_var, self.quality_var):
                var.set("")
            self.add_slot_var.set(f"{slot[0]},{slot[1]}")
        else:
            self._set_selection(slot, item.stack, f"{item.durability:g}", item.quality)
            self.add_slot_var.set("")  # an earlier empty-slot click must not steer the next Add
        self._repaint_selection()

    def _repaint_selection(self) -> None:
        tiles = [*self._slot_buttons.items(), *self._shelf_buttons]
        for slot, btn in tiles:
            # A shared coordinate is never "selected": two tiles would light up for one item.
            on = slot == self._selected_slot and slot not in self._shared
            btn.configure(relief="sunken" if on else "raised", bg=self._slot_selected_bg if on else self._slot_bg)

    def _apply_set(self) -> None:
        if self._selected_slot is None:
            self.app.show_error("Select an item first.")
            return
        try:
            stack = int(self.stack_var.get()) if self.stack_var.get().strip() else None
            durability = float(self.durability_var.get()) if self.durability_var.get().strip() else None
            quality = int(self.quality_var.get()) if self.quality_var.get().strip() else None
            edit = inv.SetItemField(self._selected_slot, stack=stack, durability=durability, quality=quality)
        except ValueError:
            self.app.show_error("Stack and quality must be whole numbers and durability a number.")
            return
        except EditError as e:
            self.app.show_error(str(e))
            return
        self.app.apply_edit(edit)

    def _apply_remove(self) -> None:
        if self._selected_slot is None:
            self.app.show_error("Select an item first.")
            return
        self.app.apply_edit(inv.RemoveItem(self._selected_slot))
        self._selected_slot = None
        self._repaint_selection()  # the grid refreshed while it was still set

    def reset_selection(self) -> None:
        """Forget the selection and the form. A coordinate picked in one save
        means nothing in the next; carrying it over would silently re-select
        whatever item happens to sit there (the web app hit the same bug)."""
        self._selected_slot = None
        for var in (self.stack_var, self.durability_var, self.quality_var, self.add_slot_var):
            var.set("")
        self._repaint_selection()

    def _sort_label(self, prefab_hash: int) -> str:
        """The name a slot tile shows, so what you see is the order that was applied."""
        return self.app.catalog.display(prefab_hash) or self.app.catalog.label(prefab_hash)

    def _sort(self) -> None:
        if self.app.state is None or self._profile is None or self._profile.player is None:
            self.app.show_error("Open a save first.")
            return
        edit = inv.SortInventory(self._sort_label)
        try:
            moves = edit.plan(self._profile.player)
        except EditError as e:
            self.app.show_error(str(e))
            return
        if all((item.x, item.y) == (x, y) for item, x, y in moves):
            self.app.status_var.set("Already sorted")  # no pending edit for a no-op
            return
        state, before, previous_view = self.app.state, list(self.app.state.pending), self.view_var.get()
        if not self.app.apply_edit(edit):
            return
        # Show the result BEFORE asking about it; a coordinate now names a different item.
        self.view_var.set("grid")
        self._switch_view()
        self.reset_selection()
        keep = dialogs.confirm_sort(self)
        # The prompt is modal for the keyboard, but the native menu bar is not
        # blocked by a Tk grab: File > Open / Save / Discard, or closing the window,
        # can change the world while it is up. Undo may only restore `before` if
        # the state is still the one we sorted and the sort is still its last edit;
        # otherwise the pending list it would put back is stale (an edit that was
        # already saved, or that the user just discarded).
        try:
            alive = bool(self.winfo_exists())
        except tk.TclError:  # the whole app was closed while the prompt was up
            return
        if keep or not alive:
            return
        if self.app.state is not state or not state.pending or state.pending[-1] is not edit:
            return
        state.set_pending(before)
        self.view_var.set(previous_view)
        self._show_view()  # refresh_all() below rebuilds whichever view is now visible
        self.app.refresh_all()
        self.reset_selection()
        self.app.status_var.set("Sort undone")

    def _apply_copy(self) -> None:
        if self._selected_slot is None:
            self.app.show_error("Select an item first.")
            return
        # Selection stays on the source slot (unlike Remove, which clears it):
        # the item is still there, so "copy three times" works without
        # re-selecting between clicks. Failures (a full inventory) surface via
        # app.apply_edit()'s own EditError handling, same as every other edit.
        self.app.apply_edit(inv.CopyItem(self._selected_slot))

    def _apply_add(self) -> None:
        # The box may hold a display label ("Stone Axe (AxeStone)"); the edit
        # takes the prefab name the save actually hashes. A typed prefab, or a
        # name from a newer game version than this catalog, resolves to itself.
        name = self.name_box.resolve()
        if not name:
            self.app.show_error("Enter an item name.")
            return
        if name not in self.app.catalog and not self.allow_unknown_var.get():
            self.app.show_error(
                f"{name!r} is not a known item prefab; check spelling, or tick "
                "\"allow unknown item\" if it's valid in a newer game update (a wrong name "
                "makes the game delete it on load).")
            return
        try:
            stack = int(self.add_stack_var.get())
            durability = float(self.add_durability_var.get())
            slot = inv.parse_slot(self.add_slot_var.get()) if self.add_slot_var.get().strip() else None
            edit = inv.AddItem(prefab_name=name, prefab_hash=stable_hash(name), stack=stack, slot=slot,
                               durability=durability, crafted_by_me=self.crafted_var.get())
        except ValueError:
            self.app.show_error("Stack must be a whole number and durability a number.")
            return
        except EditError as e:
            self.app.show_error(str(e))
            return
        if self.app.apply_edit(edit):
            self.name_var.set("")
            self.add_slot_var.set("")

    def refresh(self, profile) -> None:
        self._profile = profile
        # Only the visible view is rebuilt; the other is refreshed when switched to.
        if self.view_var.get() == "grid":
            self._clear_grid()
        else:
            self.tree.delete(*self.tree.get_children())
        # Both views need this: the list can select a duplicated coordinate too.
        self._shared = {} if profile is None or profile.player is None else {
            s: n for s, n in Counter((it.x, it.y) for it in profile.player.items).items() if n > 1}
        if profile is None or profile.player is None:
            self.grid_label.configure(text="grid: -")
            self.grid_warning.configure(text="")
            return
        width, height = inv.grid_size(profile.player)
        self.grid_label.configure(text=f"grid: {width}x{height}  ({len(profile.player.items)} items)")
        if self.view_var.get() == "grid":
            self._fill_grid(profile.player, width, height)
        else:
            for it in sorted(profile.player.items, key=lambda i: (i.y, i.x)):
                self.tree.insert("", "end", values=(
                    f"{it.x},{it.y}", self._item_label(it), it.stack, f"{it.durability:g}", it.quality,
                    "yes" if it.equipped else "", it.crafter_name,
                ))
            # Deleting the selected row queues a <<TreeviewSelect>> with nothing
            # selected, and the handler would reset _selected_slot to None the
            # moment the event loop runs -- after every single edit. Putting the
            # selection back on the rebuilt row means that queued event, and the
            # one this triggers, both see it. (The tests never pump events, which
            # is how this went unnoticed.)
            self._reselect_in_tree()
        # Same "Display (Prefab)" shape as the table above, so an item reads
        # identically wherever it appears and can be found by either name.
        self.name_box.set_options(
            (e.prefab, f"{e.display} ({e.prefab})" if e.display and e.display != e.prefab else e.prefab)
            for e in self.app.catalog.entries()
        )

    def _clear_grid(self) -> None:
        for btn in self._slot_buttons.values():
            btn.destroy()
        self._slot_buttons = {}
        for _slot, btn in self._shelf_buttons:
            btn.destroy()
        self._shelf_buttons = []
        if self._shelf_heading is not None:
            self._shelf_heading.destroy()
            self._shelf_heading = None

    def _make_tile(self, text: str, command, *, height: int = 3, shared: bool = False) -> tk.Button:
        """The one tile recipe for the grid and the shelf, so they cannot drift
        apart in size (the fit test pins it against the default window)."""
        return tk.Button(self.slots_frame, text=text, width=10, height=height, wraplength=72, justify="center",
                         fg="#a15c00" if shared else "black", command=command)

    def _fill_grid(self, player, width: int, height: int) -> None:
        """Lay every item out at its real x,y on the save's own grid size; the
        ones the grid cannot place go to a shelf below it -- never nowhere."""
        by_slot: dict[tuple[int, int], object] = {}
        shelf = []
        for it in player.items:
            slot = (it.x, it.y)
            if 0 <= it.x < width and 0 <= it.y < height and slot not in by_slot:
                by_slot[slot] = it
            else:
                shelf.append(it)  # outside the grid, or a second item on a taken slot

        for y in range(height):
            for x in range(width):
                it = by_slot.get((x, y))
                btn = self._make_tile(self._slot_text(it) if it else "",
                                      lambda s=(x, y), i=it: self._on_slot_click(s, i),
                                      shared=(x, y) in self._shared)
                btn.grid(row=y, column=x, padx=2, pady=2)
                self._slot_buttons[(x, y)] = btn

        if shelf:
            cols = max(width, 1)
            self._shelf_heading = ttk.Label(
                self.slots_frame, text=f"Outside the grid ({len(shelf)})", font=("TkDefaultFont", 9, "bold"))
            self._shelf_heading.grid(row=height, column=0, columnspan=cols, sticky="w", pady=(10, 2))
            for n, it in enumerate(shelf):
                slot = (it.x, it.y)
                # height=0 sizes the tile to its text instead of a fixed line count: the
                # real x,y needs lines of its own (an int32-extreme coordinate wraps to
                # three) and it is the only thing telling two of these tiles apart, so
                # nothing here may be clipped.
                btn = self._make_tile(self._slot_text(it, show_slot=True),
                                      lambda s=slot, i=it: self._on_slot_click(s, i),
                                      height=0, shared=slot in self._shared)
                btn.grid(row=height + 1 + n // cols, column=n % cols, padx=2, pady=2)
                self._shelf_buttons.append((slot, btn))

        any_tile = next(iter(self._slot_buttons.values()), None) or (self._shelf_buttons[0][1] if self._shelf_buttons else None)
        if any_tile is not None:
            self._slot_bg = any_tile.cget("bg")
            self._slot_selected_bg = "#b9d2f0"
        self._repaint_selection()

        if self._shared:
            coords = ", ".join(f"{x},{y}" for x, y in sorted(self._shared))
            self.grid_warning.configure(text=(
                f"More than one item claims slot {coords} (orange below). An edit finds its item by slot, "
                "so those are view-only here."))
        else:
            self.grid_warning.configure(text="")

    def _browse_items(self) -> None:
        choice = dialogs.choose_item(self, self.app.catalog.entries())
        if choice:
            # The prefab name, not the display label: it is what AddItem hashes.
            self.name_var.set(choice)

    def _slot_text(self, it, show_slot: bool = False) -> str:
        name = self.app.catalog.display(it.prefab_hash) or self.app.catalog.label(it.prefab_hash)
        if len(name) > 19:  # two 10-character lines at the slot width; the rest is for @x,y / xN [eq]
            name = name[:18] + "\u2026"
        extras = ([f"x{it.stack}"] if it.stack > 1 else []) + (["[eq]"] if it.equipped else [])
        lines = [name] + ([f"@{it.x},{it.y}"] if show_slot else []) + ([" ".join(extras)] if extras else [])
        return "\n".join(lines)

    def _item_label(self, it) -> str:
        """In-game name with the prefab name in parentheses. Both, because the
        add box below takes the prefab name -- showing only "Bronze Plate
        Tunic" would leave the user with nothing they could type."""
        name = self.app.catalog.label(it.prefab_hash)
        display = self.app.catalog.display(it.prefab_hash)
        return f"{display} ({name})" if display and display != name else name
