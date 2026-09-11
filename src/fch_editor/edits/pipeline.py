"""Apply edits to a save without touching anything else.

Every edit mutates a copy of the model and returns the diff-path prefixes it
is allowed to change. The pipeline then proves, before any byte reaches disk:
  1. the edit stayed inside its declared scope (blast-radius check), and
  2. the encoded file decodes back to exactly the intended model.
Writing goes through safe_io, which re-verifies the bytes actually on disk.
"""
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .. import safe_io
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


def check_destination(source: Path, out: Path | None, in_place: bool, force: bool = False) -> Path:
    """Resolve and validate where an edit will be written, before any work is shown."""
    if in_place == (out is not None):
        raise UnsafeWrite("choose exactly one of --out FILE or --in-place")
    if in_place:
        return Path(source)
    target = Path(out)
    if target.resolve() == Path(source).resolve():
        raise UnsafeWrite("--out is the source file; use --in-place to overwrite it (a backup is kept)")
    if target.is_dir():
        raise UnsafeWrite(f"--out {target} is a folder; give a file name")
    if not target.parent.is_dir():
        raise UnsafeWrite(f"folder {target.parent} does not exist")
    if target.exists() and not force:
        raise UnsafeWrite(f"{target} already exists; pass --force to replace it (a backup is kept)")
    return target


def write_result(result: EditResult, source: Path, out: Path | None, in_place: bool,
                 force: bool = False) -> Path | None:
    """Write the edited save to `out` (or over `source` when `in_place`).
    Returns the backup path if an existing file was replaced."""
    target = check_destination(source, out, in_place, force)
    if not force and safe_io.is_game_running():
        raise UnsafeWrite("Valheim is running and rewrites saves on exit; close it first (or pass --force)")
    if in_place and Path(source).read_bytes() != result.original:
        # Something (the game, a cloud sync) saved it after we read it; don't clobber that.
        raise UnsafeWrite(f"{source} changed since it was read; nothing written, run the command again")
    return safe_io.write_verified(target, result.data, lambda data: _check_written(data, result.profile))
