"""Skills tab: a table of current values (including pending edits) plus a
form that sets one skill, or every skill, to a level."""
import tkinter as tk
from tkinter import ttk

from ...catalog.enums import SKILL_NAMES, skill_name
from ...edits.skills import ALL, SetSkillLevel, parse_level, parse_skill
from ...errors import EditError

_COLUMNS = ("skill", "level", "progress")


class SkillsTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app

        form = ttk.Frame(self)
        form.pack(fill="x", padx=8, pady=8)
        ttk.Label(form, text="Skill:").grid(row=0, column=0, sticky="w")
        self.skill_var = tk.StringVar()
        self.skill_box = ttk.Combobox(form, textvariable=self.skill_var, state="readonly", width=18,
                                      values=["all"] + sorted(SKILL_NAMES.values()))
        self.skill_box.grid(row=0, column=1, padx=(4, 12))
        ttk.Label(form, text="Level:").grid(row=0, column=2, sticky="w")
        self.level_var = tk.StringVar(value="0")
        ttk.Entry(form, textvariable=self.level_var, width=10).grid(row=0, column=3, padx=(4, 12))
        self.keep_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="keep progress", variable=self.keep_var).grid(row=0, column=4, padx=(0, 12))
        ttk.Button(form, text="Apply", command=self._apply).grid(row=0, column=5)

        self.tree = ttk.Treeview(self, columns=_COLUMNS, show="headings", selectmode="browse")
        for col, width in zip(_COLUMNS, (160, 100, 100)):
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col, width=width, anchor="center" if col != "skill" else "w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def _on_select(self, _event) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        name, level, _progress = self.tree.item(sel[0], "values")
        self.skill_var.set(name)
        self.level_var.set(level)

    def _apply(self) -> None:
        name = self.skill_var.get()
        if not name:
            self.app.show_error("Choose a skill first.")
            return
        try:
            skill = ALL if name == "all" else parse_skill(name)
            level = parse_level(self.level_var.get())
            edit = SetSkillLevel(skill, level, self.keep_var.get())
        except EditError as e:
            self.app.show_error(str(e))
            return
        self.app.apply_edit(edit)

    def refresh(self, profile) -> None:
        self.tree.delete(*self.tree.get_children())
        if profile is None or profile.player is None:
            return
        for s in sorted(profile.player.skills, key=lambda s: skill_name(s.type)):
            self.tree.insert("", "end", values=(skill_name(s.type), f"{s.level:g}", f"{s.accumulator:g}"))
