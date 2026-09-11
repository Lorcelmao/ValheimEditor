"""Load a save and decide whether it is safe to write back.

A save is writable only if every section decoded and re-encoding the model
reproduces the original payload byte-for-byte. That self-check guards the
invariant that untouched data is never altered by an edit.
"""
from dataclasses import dataclass, field
from pathlib import Path

from . import container, versions
from .codec.map_blob import map_version
from .codec.profile import decode_profile, encode_profile
from .errors import FormatError, UnsupportedVersion
from .model import Profile


@dataclass
class LoadedSave:
    original: bytes
    hash_ok: bool
    profile: Profile | None
    path: Path | None = None
    reasons: list[str] = field(default_factory=list)   # why the save is read-only
    warnings: list[str] = field(default_factory=list)  # safe to write, but worth knowing

    @property
    def writable(self) -> bool:
        return self.profile is not None and not self.reasons


def encode_save(profile: Profile) -> bytes:
    return container.pack(encode_profile(profile))


def load_bytes(data: bytes, path: Path | None = None) -> LoadedSave:
    """Raises FormatError only if `data` is not an .fch envelope at all."""
    env = container.unpack(data)
    save = LoadedSave(original=bytes(data), hash_ok=env.hash_ok, profile=None, path=path)
    if not env.hash_ok:
        save.warnings.append("stored SHA-512 does not match the payload (the game ignores it; it is rewritten on save)")
    try:
        save.profile = decode_profile(env.payload)
    except (FormatError, UnsupportedVersion) as e:
        save.reasons.append(f"cannot decode profile: {e}")
        return save
    profile = save.profile
    if profile.player_error:
        save.reasons.append(f"cannot decode player data: {profile.player_error}")
    elif encode_profile(profile) != env.payload:
        save.reasons.append("re-encoding does not reproduce the original bytes")
    for w in profile.worlds:
        v = map_version(w.map_data) if w.map_data is not None else versions.MAP
        if v != versions.MAP:
            save.warnings.append(f"world {w.uid}: map version {v} is kept as-is but cannot be inspected")
    features = versions.code_only_features(profile)
    if features:
        save.warnings.append("layout confirmed from game code but not yet from a real save: " + ", ".join(features))
    return save


def load_file(path: Path) -> LoadedSave:
    path = Path(path)
    return load_bytes(path.read_bytes(), path)
