"""A loaded save plus a list of not-yet-written edits.

Every consumer's "current" values, and any confirmation-diff view, come from
running the pending edits through the same `apply_edits` pipeline the CLI
uses (`preview()`) — there is no second, front-end-specific notion of current
values. Re-adding an edit for the same target (e.g. nudging a level twice)
replaces the earlier one instead of piling up redundant ops.

Framework-agnostic by construction (no tkinter, no browser API) — this is
what makes it shareable: the Tkinter GUI (`gui/app.py`) and the web bridge
(`web/bridge.py`) both hold one `AppState` per open file rather than each
re-deriving "pending edits + rollback on a failed preview" independently.
"""
from .dedup import edit_key
from .pipeline import EditResult, preview_edits
from ..load import LoadedSave


class AppState:
    def __init__(self, save: LoadedSave):
        self.save = save
        self.pending: list = []
        self._cache: EditResult | None = None

    @property
    def dirty(self) -> bool:
        return bool(self.pending)

    def add(self, edit) -> None:
        """Validation already happened in the edit's own __post_init__."""
        key = edit_key(edit)
        if key is not None:
            self.pending = [e for e in self.pending if edit_key(e) != key]
        self.pending.append(edit)
        self._cache = None

    def discard(self) -> None:
        self.pending = []
        self._cache = None

    def set_pending(self, pending: list) -> None:
        """Replace the pending list wholesale (used to roll back a failed batch)."""
        self.pending = pending
        self._cache = None

    def preview(self) -> EditResult:
        """Profile + diff reflecting every pending edit; writes nothing."""
        if self._cache is None:
            self._cache = preview_edits(self.save, self.pending)
        return self._cache

    def rebased_on(self, save: LoadedSave) -> "AppState":
        """A fresh state after a successful write: the new file is now the baseline."""
        return AppState(save)
