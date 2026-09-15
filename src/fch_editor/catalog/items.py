"""Resolve item prefab hashes back to names.

Saves store only `stable_hash(prefabName)`, so names come from a list of known
prefabs. Unknown hashes are displayed as `#xxxxxxxx` (the little-endian bytes
as they appear in the file) and are never an error. Extra names can be supplied
from a text file.

The bundled list carries optional metadata in pipe-separated columns:

    Prefab | Display Name | ItemType

Everything after the first column is optional and an empty column means
"unknown", so a file of bare prefab names -- the format `--items FILE` has
always accepted, and what users' own lists look like -- parses unchanged.

The prefab name stays the real identifier: it is what the save hashes and what
`AddItem` accepts. A display name is presentation only and never reaches the
encoder.
"""
from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path
from typing import NamedTuple

from ..errors import FchError
from ..stable_hash import stable_hash


def hash_hex(prefab_hash: int) -> str:
    """Little-endian hex of the hash, matching a hex dump of the save."""
    return prefab_hash.to_bytes(4, "little", signed=True).hex()


class CatalogEntry(NamedTuple):
    prefab: str
    display: str | None = None
    item_type: str | None = None


def _parse(text: str) -> list[CatalogEntry]:
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        prefab, display, item_type = (f.strip() for f in (line.split("|") + ["", ""])[:3])
        if prefab:
            entries.append(CatalogEntry(prefab, display or None, item_type or None))
    return entries


class ItemCatalog:
    def __init__(self, entries: Iterable[CatalogEntry]):
        self._by_hash = {stable_hash(e.prefab): e for e in entries}

    @classmethod
    def load(cls, extra_files: Iterable[Path] = ()) -> "ItemCatalog":
        entries = _parse(files(__package__).joinpath("data/items.txt").read_text(encoding="utf-8"))
        for path in extra_files:
            try:
                entries += _parse(Path(path).read_text(encoding="utf-8-sig"))
            except UnicodeDecodeError as e:
                raise FchError(f"item list {path} is not UTF-8 text: {e.reason}") from None
        return cls(entries)

    def __contains__(self, name: str) -> bool:
        return stable_hash(name) in self._by_hash

    def name(self, prefab_hash: int) -> str | None:
        entry = self._by_hash.get(prefab_hash)
        return entry.prefab if entry else None

    def label(self, prefab_hash: int) -> str:
        return self.name(prefab_hash) or f"#{hash_hex(prefab_hash)}"

    def display(self, prefab_hash: int) -> str | None:
        """The English in-game name, or None if this list doesn't carry one
        (a mod item, or a user's own bare-prefab-name list)."""
        entry = self._by_hash.get(prefab_hash)
        return entry.display if entry else None

    def names(self) -> list[str]:
        """Every known prefab name, sorted (for pickers/autocomplete)."""
        return sorted(e.prefab for e in self._by_hash.values())

    def entries(self) -> list[CatalogEntry]:
        """Every known entry with its metadata, sorted by prefab name -- what a
        picker needs to show a display name and search on either field."""
        return sorted(self._by_hash.values(), key=lambda e: e.prefab)
