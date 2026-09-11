"""Read-only summary tab: the on-disk save as loaded, not the live edit preview
(pending changes are covered by the confirmation dialog before writing)."""
from tkinter import scrolledtext, ttk

from ...catalog.items import ItemCatalog
from ...load import LoadedSave
from ...render import info_text


class OverviewTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.text = scrolledtext.ScrolledText(self, wrap="word", font=("Consolas", 10))
        self.text.pack(fill="both", expand=True, padx=8, pady=8)
        self.text.configure(state="disabled")

    def refresh(self, save: LoadedSave, catalog: ItemCatalog) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", info_text(save, catalog))
        self.text.configure(state="disabled")
