"""Human-readable and JSON views of a loaded save."""
import base64
import hashlib
import math
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone

from .catalog.enums import scope_name, skill_name, stat_name
from .catalog.items import ItemCatalog
from .codec.map_blob import decode_map
from .errors import FchError
from .load import LoadedSave
from .model import MapData
from .reader import RawF32


def map_summary(raw: bytes | None) -> dict | None:
    if raw is None:
        return None
    try:
        m: MapData = decode_map(raw)
    except FchError as e:
        return {"error": str(e), "bytes": len(raw)}
    cells = m.texture_size ** 2
    explored = cells - m.explored.count(0)
    return {
        "texture_size": m.texture_size,
        "explored_percent": round(100 * explored / cells, 3),
        "shared_explored_percent": round(100 * (cells - m.explored_shared.count(0)) / cells, 3),
        "pins": [_jsonable(p) for p in m.pins],
        "public_position": m.public_position,
    }


# Internal bookkeeping, not save content.
_JSON_SKIP = {"player_raw"}


def _jsonable(v):
    if isinstance(v, RawF32):
        return f"NaN:{v.raw.hex()}"
    if isinstance(v, float) and not math.isfinite(v):
        return repr(v)  # JSON has no NaN/Infinity literals
    if isinstance(v, (bytes, bytearray)):
        return {"bytes": len(v), "sha256": hashlib.sha256(v).hexdigest(),
                "base64": base64.b64encode(v).decode() if len(v) <= 4096 else None}
    if is_dataclass(v):
        return {f.name: _jsonable(getattr(v, f.name)) for f in fields(v) if f.name not in _JSON_SKIP}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def to_json(save: LoadedSave, catalog: ItemCatalog, section: str | None = None) -> dict:
    doc = {"writable": save.writable, "hash_ok": save.hash_ok, "reasons": save.reasons,
           "warnings": save.warnings}
    p = save.profile
    if p is None:
        return doc
    full = _jsonable(p)
    for i, block in enumerate(full["stat_blocks"]):
        block["scope"] = scope_name(i)
        block["stats"] = {stat_name(j): v for j, v in enumerate(block["stats"])}
    for w, raw in zip(full["worlds"], (w.map_data for w in p.worlds)):
        w["map"] = map_summary(raw)
        del w["map_data"]
    if p.player is not None:
        for item in full["player"]["items"]:
            item["name"] = catalog.label(item["prefab_hash"])
        for skill in full["player"]["skills"]:
            skill["name"] = skill_name(skill["type"])
    sections = {"stats": full["stat_blocks"], "worlds": full["worlds"], "player": full["player"],
                "inventory": (full["player"] or {}).get("items"), "skills": (full["player"] or {}).get("skills")}
    if section:
        return {**doc, section: sections[section]}
    return {**doc, "profile": full}


def info_text(save: LoadedSave, catalog: ItemCatalog) -> str:
    lines = [f"File      : {save.path or '<bytes>'} ({len(save.original)} bytes)",
             f"Writable  : {'yes' if save.writable else 'NO'}", f"Hash      : {'ok' if save.hash_ok else 'MISMATCH'}"]
    lines += [f"Read-only : {r}" for r in save.reasons] + [f"Warning   : {w}" for w in save.warnings]
    p = save.profile
    if p is None:
        return "\n".join(lines)
    try:
        created = datetime.fromtimestamp(p.date_created, timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        created = f"<invalid timestamp {p.date_created}>"
    lines += [f"Character : {p.name} (id {p.player_id}), created {created}, used cheats: {p.used_cheats}",
              f"Versions  : profile {p.version}"
              + (f", player {p.player.version}, inventory {p.player.inventory_version}, skills {p.player.skills_version}"
                 if p.player else "")]
    for w in p.worlds:
        m = map_summary(w.map_data)
        if m is None:
            explored = "no map"
        elif "error" in m:
            explored = f"map error: {m['error']}"
        else:
            explored = f"{m['explored_percent']}% explored, {len(m['pins'])} pins"
        lines.append(f"World     : {w.uid}  logout {_pt(w.logout_point) if w.have_logout else '-'}  {explored}")
    pd = p.player
    if pd is None:
        return "\n".join(lines)
    lines.append(f"Vitals    : HP {pd.health:g}/{pd.max_health:g}  stamina {pd.stamina:g}/{pd.max_stamina:g}  "
                 f"eitr {pd.eitr:g}/{pd.max_eitr:g}  guardian power {pd.guardian_power or '-'}")
    lines.append(f"Look      : model {pd.model_index}, {pd.beard}, {pd.hair}")
    lines.append("Skills    : " + ", ".join(f"{skill_name(s.type)} {s.level:g}" for s in pd.skills))
    lines.append(f"Inventory : {len(pd.items)} items")
    for it in sorted(pd.items, key=lambda i: (i.y, i.x)):
        extra = "".join([" [equipped]" if it.equipped else "", f" q{it.quality}" if it.quality != 1 else "",
                         f" by {it.crafter_name}" if it.crafter_name else ""])
        lines.append(f"  ({it.x},{it.y}) {catalog.label(it.prefab_hash):<24} x{it.stack:<4} dur {it.durability:g}{extra}")
    return "\n".join(lines)


def _pt(v) -> str:
    return "(" + ", ".join(f"{c:.1f}" for c in v) + ")"


def diff_text(changes: list[tuple[str, object, object]]) -> str:
    # diffing.F32Bits reprs as a plain number, so every value can use repr().
    if not changes:
        return "no differences"
    return "\n".join(f"{path}: {old!r} -> {new!r}" for path, old, new in changes)
