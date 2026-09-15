"""Inventory tab: a table of items plus forms to edit/remove a selected one
and to add a new item by prefab name."""
import tkinter as tk
from tkinter import ttk

from ...edits import inventory as inv
from ...errors import EditError
from ...stable_hash import stable_hash
from ..widgets import AutocompleteCombobox

_COLUMNS = ("slot", "item", "stack", "durability", "equipped", "crafter")


class InventoryTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self._selected_slot: tuple[int, int] | None = None

        self.grid_label = ttk.Label(self, text="grid: -")
        self.grid_label.pack(anchor="w", padx=8, pady=(8, 0))

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
        self.name_box = AutocompleteCombobox(add_form, width=22, textvariable=self.name_var)
        self.name_box.grid(row=0, column=1, padx=4)
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
        ttk.Label(edit_form, text="Stack:").grid(row=0, column=0, padx=4, pady=4)
        ttk.Entry(edit_form, textvariable=self.stack_var, width=8).grid(row=0, column=1)
        ttk.Label(edit_form, text="Durability:").grid(row=0, column=2, padx=4)
        ttk.Entry(edit_form, textvariable=self.durability_var, width=10).grid(row=0, column=3)
        ttk.Button(edit_form, text="Apply", command=self._apply_set).grid(row=0, column=4, padx=8)
        ttk.Button(edit_form, text="Remove", command=self._apply_remove).grid(row=0, column=5)
        edit_form.pack(side="bottom", fill="x", padx=8, pady=(0, 8))

        self.tree = ttk.Treeview(self, columns=_COLUMNS, show="headings", selectmode="browse", height=10)
        for col, width in zip(_COLUMNS, (60, 200, 60, 80, 70, 100)):
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col, width=width, anchor="center" if col not in ("item", "crafter") else "w")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)

    def _on_select(self, _event) -> None:
        sel = self.tree.selection()
        if not sel:
            self._selected_slot = None
            return
        slot_text, _name, stack, durability, *_ = self.tree.item(sel[0], "values")
        self._selected_slot = inv.parse_slot(slot_text)
        self.stack_var.set(stack)
        self.durability_var.set(durability)

    def _apply_set(self) -> None:
        if self._selected_slot is None:
            self.app.show_error("Select an item first.")
            return
        try:
            stack = int(self.stack_var.get()) if self.stack_var.get().strip() else None
            durability = float(self.durability_var.get()) if self.durability_var.get().strip() else None
            edit = inv.SetItemField(self._selected_slot, stack=stack, durability=durability)
        except ValueError:
            self.app.show_error("Stack must be a whole number and durability a number.")
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

    def _apply_add(self) -> None:
        name = self.name_var.get().strip()
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
        self.tree.delete(*self.tree.get_children())
        if profile is None or profile.player is None:
            self.grid_label.configure(text="grid: -")
            return
        width, height = inv.grid_size(profile.player)
        self.grid_label.configure(text=f"grid: {width}x{height}  ({len(profile.player.items)} items)")
        for it in sorted(profile.player.items, key=lambda i: (i.y, i.x)):
            self.tree.insert("", "end", values=(
                f"{it.x},{it.y}", self._item_label(it), it.stack, f"{it.durability:g}",
                "yes" if it.equipped else "", it.crafter_name,
            ))
        self.name_box.set_values(self.app.catalog.names())

    def _item_label(self, it) -> str:
        """In-game name with the prefab name in parentheses. Both, because the
        add box below takes the prefab name -- showing only "Bronze Plate
        Tunic" would leave the user with nothing they could type."""
        name = self.app.catalog.label(it.prefab_hash)
        display = self.app.catalog.display(it.prefab_hash)
        return f"{display} ({name})" if display and display != name else name
