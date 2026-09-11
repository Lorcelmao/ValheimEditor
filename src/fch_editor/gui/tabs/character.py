"""Character tab: name, appearance and guardian power, one form per field.

Applying always builds an edit for every field (the state layer's replace-by-
field-key logic drops a field back to a no-op if it matches what's already
there, so this stays simple without re-sending needless writes).
"""
import tkinter as tk
from tkinter import colorchooser, ttk

from ...catalog.appearance import BEARDS, GUARDIAN_POWERS, HAIRS
from ...edits import character as ch
from ...edits.values import parse_number
from ...errors import EditError
from ...render import f32_text

_POWER_CHOICES = ["none"] + list(GUARDIAN_POWERS.values())
_POWER_BY_NAME = {name.lower(): pid for pid, name in GUARDIAN_POWERS.items()}


class CharacterTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        grid = ttk.Frame(self)
        grid.pack(fill="x", padx=12, pady=12)

        self.name_var = tk.StringVar()
        self.beard_var = tk.StringVar()
        self.hair_var = tk.StringVar()
        self.skin_var = tk.StringVar()
        self.hair_color_var = tk.StringVar()
        self.model_var = tk.IntVar(value=0)
        self.power_var = tk.StringVar()
        self.cooldown_var = tk.StringVar()
        self.allow_unknown_var = tk.BooleanVar(value=False)

        row = 0
        ttk.Label(grid, text="Name:").grid(row=row, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.name_var, width=30).grid(row=row, column=1, sticky="w", pady=3)

        row += 1
        ttk.Label(grid, text="Beard:").grid(row=row, column=0, sticky="w")
        ttk.Combobox(grid, textvariable=self.beard_var, values=BEARDS, width=27).grid(
            row=row, column=1, sticky="w", pady=3)

        row += 1
        ttk.Label(grid, text="Hair:").grid(row=row, column=0, sticky="w")
        ttk.Combobox(grid, textvariable=self.hair_var, values=HAIRS, width=27).grid(
            row=row, column=1, sticky="w", pady=3)

        row += 1
        ttk.Label(grid, text="Skin color:").grid(row=row, column=0, sticky="w")
        self._color_row(grid, row, self.skin_var)

        row += 1
        ttk.Label(grid, text="Hair color:").grid(row=row, column=0, sticky="w")
        self._color_row(grid, row, self.hair_color_var)

        row += 1
        ttk.Label(grid, text="Body model:").grid(row=row, column=0, sticky="w")
        models = ttk.Frame(grid)
        models.grid(row=row, column=1, sticky="w")
        ttk.Radiobutton(models, text="0", value=0, variable=self.model_var).pack(side="left")
        ttk.Radiobutton(models, text="1", value=1, variable=self.model_var).pack(side="left")

        row += 1
        ttk.Label(grid, text="Guardian power:").grid(row=row, column=0, sticky="w")
        ttk.Combobox(grid, textvariable=self.power_var, state="readonly", values=_POWER_CHOICES,
                     width=27).grid(row=row, column=1, sticky="w", pady=3)

        row += 1
        ttk.Label(grid, text="Power cooldown (s):").grid(row=row, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.cooldown_var, width=10).grid(row=row, column=1, sticky="w", pady=3)

        row += 1
        ttk.Checkbutton(grid, text="Allow beard/hair styles not in the known list",
                        variable=self.allow_unknown_var).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))

        row += 1
        ttk.Button(grid, text="Apply", command=self._apply).grid(row=row, column=1, sticky="w", pady=(10, 0))

    def _color_row(self, grid, row, var: tk.StringVar) -> None:
        frame = ttk.Frame(grid)
        frame.grid(row=row, column=1, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=var, width=20).pack(side="left")
        ttk.Button(frame, text="Pick…", command=lambda: self._pick_color(var)).pack(side="left", padx=(4, 0))

    def _pick_color(self, var: tk.StringVar) -> None:
        rgb, _hex = colorchooser.askcolor(parent=self, title="Choose a color")
        if rgb is not None:
            var.set(",".join(f"{c / 255:.4f}" for c in rgb))

    def _apply(self) -> None:
        try:
            edits = [
                ch.SetName(self.name_var.get()),
                ch.SetBeard(self.beard_var.get(), self.allow_unknown_var.get()),
                ch.SetHair(self.hair_var.get(), self.allow_unknown_var.get()),
                ch.SetColor("skin_color", ch.parse_color(self.skin_var.get())),
                ch.SetColor("hair_color", ch.parse_color(self.hair_color_var.get())),
                ch.SetModel(self.model_var.get()),
                ch.SetGuardianPower(ch.parse_guardian_power(self.power_var.get())),
                ch.SetGuardianCooldown(parse_number(self.cooldown_var.get(), "guardian power cooldown")),
            ]
        except EditError as e:
            self.app.show_error(str(e))
            return
        self.app.apply_edits_batch(edits)

    def refresh(self, profile) -> None:
        if profile is None or profile.player is None:
            for var in (self.name_var, self.beard_var, self.hair_var, self.skin_var,
                       self.hair_color_var, self.power_var, self.cooldown_var):
                var.set("")
            self.model_var.set(0)
            return
        p = profile.player
        self.name_var.set(profile.name)
        self.beard_var.set(p.beard)
        self.hair_var.set(p.hair)
        self.skin_var.set(",".join(f32_text(c) for c in p.skin_color))
        self.hair_color_var.set(",".join(f32_text(c) for c in p.hair_color))
        self.model_var.set(p.model_index)
        self.power_var.set(GUARDIAN_POWERS.get(p.guardian_power, "none") if p.guardian_power else "none")
        self.cooldown_var.set(f32_text(p.guardian_power_cooldown))
