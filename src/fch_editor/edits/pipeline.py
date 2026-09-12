"""Apply edits to a save without touching anything else.

Every edit mutates a copy of the model and returns the diff-path prefixes it
is allowed to change. This module proves, before any byte is returned:
  1. the edit stayed inside its declared scope (blast-radius check), and
  2. the encoded file decodes back to exactly the intended model.

Pure by design — no filesystem or process access, only `copy`, `dataclasses`,
`typing`, and sibling package modules — so it can run anywhere CPython runs,
including inside Pyodide in a browser. Actually writing the result to disk
(backups, atomic replace, the running-game guard) is `edits/write.py`.
"""
import copy
from dataclasses import dataclass
from typing import Protocol

from ..diffing import diff
from ..errors import UnsafeWrite
from ..load import LoadedSave, encode_save, load_bytes
from ..model import Profile


class Edit(Protocol):
    def apply(self, profile: Profile) -> list[str]:
        """Mutate `profile`; return the diff-path prefixes this edit may change."""


@dataclass
class EditResult:
    data: bytes
    profile: Profile
    changes: list[tuple[str, object, object]]
    original: bytes  # the source bytes the edit was based on


def _in_scope(path: str, prefixes: list[str]) -> bool:
    """A prefix covers itself and anything nested under it (".field", "[key]").
    A keyed prefix like `player.skills[Run]` also covers duplicate keys, which
    diffing renders as `player.skills[Run#1]`."""
    for p in prefixes:
        heads = (p + ".", p + "[") + ((p[:-1] + "#",) if p.endswith("]") else ())
        if path == p or path.startswith(heads):
            return True
    return False


def _check_written(data: bytes, intended: Profile) -> None:
    written = load_bytes(data)
    if not written.writable:
        raise UnsafeWrite("edited file does not load cleanly: " + "; ".join(written.reasons))
    mismatch = diff(intended, written.profile)
    if mismatch:
        raise UnsafeWrite(f"edited file does not match the intended edit at {mismatch[0][0]}")


def apply_edits(save: LoadedSave, edits: list[Edit]) -> EditResult:
    """Pure: returns the new file bytes and the field-level changes; writes nothing."""
    if not save.writable:
        raise UnsafeWrite("save is read-only for this editor: " + "; ".join(save.reasons))
    intended = copy.deepcopy(save.profile)
    allowed: list[str] = []
    for edit in edits:
        allowed += edit.apply(intended)
    changes = diff(save.profile, intended)
    outside = [path for path, _, _ in changes if not _in_scope(path, allowed)]
    if outside:
        raise UnsafeWrite(f"edit changed fields outside its scope: {', '.join(outside[:5])}")
    try:
        data = encode_save(intended)
    except ValueError as e:  # a value the file format cannot hold
        raise UnsafeWrite(f"edit produced a value that cannot be saved: {e}") from None
    _check_written(data, intended)
    return EditResult(data=data, profile=intended, changes=changes, original=save.original)


def preview_edits(save: LoadedSave, pending: list[Edit]) -> EditResult:
    """`apply_edits(save, pending)`, or an identity result when nothing is
    pending yet. Every front end that holds a growing list of not-yet-written
    edits (the Tkinter GUI's `AppState`, the web `Session`) needs exactly this
    "what would writing now produce" view — factored out here so both share
    one definition instead of two independently-maintained copies."""
    if pending:
        return apply_edits(save, pending)
    return EditResult(data=save.original, profile=copy.deepcopy(save.profile), changes=[], original=save.original)
