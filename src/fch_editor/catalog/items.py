"""Resolve item prefab hashes back to names.

Saves store only `stable_hash(prefabName)`, so names come from a list of known
prefabs. The bundled list predates Valheim 1.0; unknown hashes are displayed as
`#xxxxxxxx` (the little-endian bytes as they appear in the file) and are never
an error. Extra names can be supplied from a text file, one per line.
"""
from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path

from ..errors import FchError
from ..stable_hash import stable_hash


def hash_hex(prefab_hash: int) -> str:
    """Little-endian hex of the hash, matching a hex dump of the save."""
    return prefab_hash.to_bytes(4, "little", signed=True).hex()


def _parse(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


class ItemCatalog:
    def __init__(self, names: list[str]):
        self._by_hash = {stable_hash(n): n for n in names}

    @classmethod
    def load(cls, extra_files: Iterable[Path] = ()) -> "ItemCatalog":
        names = _parse(files(__package__).joinpath("data/items.txt").read_text(encoding="utf-8"))
        for path in extra_files:
            try:
                names += _parse(Path(path).read_text(encoding="utf-8-sig"))
            except UnicodeDecodeError as e:
                raise FchError(f"item list {path} is not UTF-8 text: {e.reason}") from None
        return cls(names)

    def __contains__(self, name: str) -> bool:
        return stable_hash(name) in self._by_hash

    def name(self, prefab_hash: int) -> str | None:
        return self._by_hash.get(prefab_hash)

    def label(self, prefab_hash: int) -> str:
        return self.name(prefab_hash) or f"#{hash_hex(prefab_hash)}"

    def names(self) -> list[str]:
        """Every known prefab name, sorted (for pickers/autocomplete)."""
        return sorted(self._by_hash.values())
