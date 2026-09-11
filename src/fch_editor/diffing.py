"""Flatten a Profile into {field path: value} and compare two of them.

Used by `fch diff` and by the edit pipeline's blast-radius check: an edit may
only change the paths it declares. Paths use stable keys (item grid slot,
skill name, stat name, dictionary key, set member) rather than list positions
where the game has a natural key. Floats are compared as the f32 bits actually
written. Opaque blobs are represented by length + SHA-256 prefix.
"""
import hashlib
import math
import struct
from dataclasses import dataclass, fields, is_dataclass

from .catalog.enums import scope_name, skill_name, stat_name
from .model import Profile
from .reader import F32, RawF32

# Profile fields flattened specially below; every other field is included generically,
# so a field added to the model later can never be silently left out of a diff.
_SPECIAL = {"stat_blocks", "worlds", "player", "player_raw", "player_error"}


@dataclass(frozen=True)
class F32Bits:
    """A float compared by its stored bit pattern. Used for zeros (keeps -0.0
    distinct) and NaN (NaN never equals itself). A distinct type, so text that
    merely looks like one can never be mistaken for a float."""

    hex: str

    @property
    def value(self) -> float:
        return F32.unpack(bytes.fromhex(self.hex))[0]

    def __repr__(self) -> str:
        v = self.value
        return f"NaN({self.hex})" if math.isnan(v) else repr(v)


def _float(v: float):
    if isinstance(v, RawF32):
        return F32Bits(v.raw.hex())
    try:
        bits = F32.pack(v)
    except (OverflowError, struct.error):
        return f"f32-out-of-range<{v!r}>"
    stored = F32.unpack(bits)[0]  # the value as written, so 0.1 matches its re-read 0.10000000149
    if stored == 0.0 or math.isnan(stored):
        return F32Bits(bits.hex())
    return stored


def _scalar(v):
    if isinstance(v, float):
        return _float(v)
    if isinstance(v, (bytes, bytearray)):
        return f"<{len(v)} bytes sha256:{hashlib.sha256(v).hexdigest()[:16]}>"
    if isinstance(v, tuple):
        return tuple(_scalar(x) for x in v)
    return v


def _unique(key: str, seen: dict) -> str:
    """Disambiguate repeated keys (duplicate dict keys, grid slots, world ids) by occurrence."""
    n = seen.get(key, 0)
    seen[key] = n + 1
    return key if n == 0 else f"{key}#{n}"


def _is_pairs(v: list) -> bool:
    return bool(v) and isinstance(v[0], tuple) and len(v[0]) == 2 and isinstance(v[0][0], str)


def _element_key(name: str, i: int, e, keyed: dict) -> str:
    if name in keyed:
        return keyed[name](i, e)
    if isinstance(e, str):
        return repr(e)  # string lists are sets in the game (recipes, uniques, ...)
    return str(i)


def _list(out: dict, path: str, name: str, v: list, keyed: dict) -> None:
    out[f"{path}.count"] = len(v)
    seen: dict = {}
    pairs = _is_pairs(v)
    for i, e in enumerate(v):
        if pairs:
            key, e = repr(e[0]), e[1]
        else:
            key = _element_key(name, i, e, keyed)
        sub = f"{path}[{_unique(key, seen)}]"
        if is_dataclass(e):
            _walk(out, sub, e)
        elif isinstance(e, list):  # nested dict, e.g. enemy_stats[i]
            _list(out, sub, "", e, {})
        else:
            out[sub] = _scalar(e)


def _walk(out: dict, prefix: str, obj, keyed: dict | None = None, skip: set = frozenset()) -> None:
    """Flatten a dataclass. `keyed` maps a list field name to a function giving
    each element's stable key."""
    keyed = keyed or {}
    for f in fields(obj):
        if f.name in skip:
            continue
        v = getattr(obj, f.name)
        path = f"{prefix}.{f.name}" if prefix else f.name
        if isinstance(v, list):
            _list(out, path, f.name, v, keyed)
        elif is_dataclass(v):
            _walk(out, path, v)
        else:
            out[path] = _scalar(v)


def flatten(p: Profile) -> dict:
    out: dict = {}
    _walk(out, "", p, skip=_SPECIAL)
    for i, block in enumerate(p.stat_blocks):
        _walk(out, f"stats.{scope_name(i)}", block, {"stats": lambda j, _: stat_name(j)})
    out["stats.count"] = len(p.stat_blocks)
    seen: dict = {}
    for w in p.worlds:
        _walk(out, f"worlds[{_unique(str(w.uid), seen)}]", w)
    out["worlds.count"] = len(p.worlds)
    if p.player is None:
        out["player"] = _scalar(p.player_raw)
    else:
        _walk(out, "player", p.player, {
            "items": lambda _, item: f"({item.x},{item.y})",
            "skills": lambda _, skill: skill_name(skill.type),
        })
    return out


def diff(a: Profile, b: Profile) -> list[tuple[str, object, object]]:
    """(path, old, new) for every differing path; a missing side is None."""
    fa, fb = flatten(a), flatten(b)
    return [(k, fa.get(k), fb.get(k)) for k in sorted(fa.keys() | fb.keys()) if fa.get(k) != fb.get(k)]
