"""Identity for de-duplicating a pending edit against earlier ones in the same list.

Used by `edits/state.py::AppState` — shared by the Tkinter GUI (`gui/app.py`)
and the web bridge (`web/bridge.py::Session`, via `AppState`) so "editing the
same field twice replaces rather than piles up" is one rule, not two
independently-maintained ones.
"""
from .character import SetBeard, SetColor, SetGuardianCooldown, SetGuardianPower, SetHair, SetModel, SetName
from .inventory import RemoveItem, SetItemField
from .skills import SetSkillLevel

_SINGLE_FIELD = (SetName, SetBeard, SetHair, SetModel, SetGuardianPower, SetGuardianCooldown)


def edit_key(edit):
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
