"""The filesystem half of the edit pipeline: where to write, and the actual write.

Split out from `pipeline.py` so that module stays importable with no filesystem
or process access at all (`copy`, `dataclasses`, `typing`, and sibling package
modules only) — a requirement for running the pure edit logic inside Pyodide,
which has no reliable `subprocess`/`tempfile`. Everything here is CLI/GUI-only:
`safe_io` (backups, atomic replace, `is_game_running`) has no browser
equivalent, and none of it is needed there.
"""
from pathlib import Path

from .. import safe_io
from ..errors import UnsafeWrite
from .pipeline import EditResult, _check_written


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
