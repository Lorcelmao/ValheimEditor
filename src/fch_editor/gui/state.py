"""GUI state: the loaded save plus a list of not-yet-written edits.

Every tab's "current" values, and the confirmation dialog's diff, come from
running the pending edits through the same `apply_edits` pipeline the CLI
uses (`preview()`) — there is no second, GUI-only notion of current values.
Re-adding an edit for the same target (e.g. nudging a level twice) replaces
the earlier one instead of piling up redundant ops.
"""
import copy

from ..edits.character import (SetBeard, SetColor, SetGuardianCooldown, SetGuardianPower, SetHair,
                               SetModel, SetName)
from ..edits.inventory import RemoveItem, SetItemField
from ..edits.pipeline import EditResult, apply_edits
from ..edits.skills import SetSkillLevel
from ..load import LoadedSave

_SINGLE_FIELD = (SetName, SetBeard, SetHair, SetModel, SetGuardianPower, SetGuardianCooldown)


def _edit_key(edit):
    """Identity for de-duplicating pending edits; `None` means always keep both
    (e.g. AddItem — each call is its own action, not a revision of a prior one)."""
    if isinstance(edit, SetSkillLevel):
        return (SetSkillLevel, edit.skill)
    if isinstance(edit, SetColor):
        return (SetColor, edit.field)
    if isinstance(edit, _SINGLE_FIELD):
        return (type(edit),)
    if isinstance(edit, (SetItemField, RemoveItem)):
        return (type(edit), edit.slot)
    return None


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
        key = _edit_key(edit)
        if key is not None:
            self.pending = [e for e in self.pending if _edit_key(e) != key]
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
            if self.pending:
                self._cache = apply_edits(self.save, self.pending)
            else:
                self._cache = EditResult(data=self.save.original, profile=copy.deepcopy(self.save.profile),
                                         changes=[], original=self.save.original)
        return self._cache

    def rebased_on(self, save: LoadedSave) -> "AppState":
        """A fresh state after a successful write: the new file is now the baseline."""
        return AppState(save)
