"""File writes that cannot leave a half-written or unverified save behind.

Flow: write a unique temp file next to the target, fsync, read it back, run the
caller's verification on the bytes actually on disk, back up the existing
target, then atomically replace it. Any failure before the replace leaves the
original untouched, and cleanup never masks the original error.
"""
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .errors import UnsafeWrite


def backup(path: Path) -> Path:
    """Copy `path` to `<name>.bak-YYYYMMDD-HHMMSS[-n]`, never overwriting a backup."""
    data = Path(path).read_bytes()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    n = 0
    while True:
        dest = path.with_name(f"{path.name}.bak-{stamp}" + (f"-{n}" if n else ""))
        try:
            # Exclusive create: a concurrent run can never clobber this backup.
            with open(dest, "xb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            return dest
        except FileExistsError:
            n += 1


def _retry(action: Callable[[], None], attempts: int = 5, delay: float = 0.2) -> None:
    # Antivirus and cloud sync briefly lock freshly written files on Windows.
    for attempt in range(attempts):
        try:
            action()
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _discard(tmp: Path) -> None:
    """Best-effort temp removal; never raises so the original error surfaces."""
    try:
        _retry(lambda: tmp.unlink(missing_ok=True))
    except OSError:
        pass


def write_verified(
    path: Path,
    data: bytes,
    verify: Callable[[bytes], object],
    make_backup: bool = True,
) -> Path | None:
    """Write `data` to `path` only after `verify(bytes_on_disk)` accepts it.

    `verify` rejects by raising or by returning False. Returns the backup
    path, if one was made.
    """
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".fch-editor-tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        written = tmp.read_bytes()
        if written != data:
            raise UnsafeWrite(f"read-back of {tmp.name} differs from the data written")
        if verify(written) is False:
            raise UnsafeWrite("verification rejected the new file")
        backup_path = backup(path) if make_backup and path.exists() else None
        try:
            _retry(lambda: os.replace(tmp, path))
        except OSError as e:
            where = f"; original is unchanged, backup at {backup_path}" if backup_path else ""
            raise UnsafeWrite(f"could not replace {path.name}: {e}{where}") from e
        return backup_path
    finally:
        _discard(tmp)


def is_game_running() -> bool:
    """True if a Valheim process is running (it rewrites the save on exit)."""
    if sys.platform != "win32":
        return False
    tasklist = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tasklist.exe"
    try:
        result = subprocess.run(
            [str(tasklist), "/FI", "IMAGENAME eq valheim.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "valheim.exe" in result.stdout.lower()
