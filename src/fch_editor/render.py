"""Human-readable and JSON views of a loaded save."""
import base64
import hashlib
import math
import re
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone

from .catalog.enums import scope_name, skill_name, stat_name
from .catalog.items import ItemCatalog
from .codec.map_blob import decode_map
from .diffing import F32Bits
from .edits.inventory import grid_size
from .reader import F32, RawF32
from .errors import FchError
from .load import LoadedSave
from .model import EQUIPPED, MapData


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
        # The inventory's real dimensions, so a UI can lay items out spatially
        # without re-deriving them. `grid_size` reads the `invrows` unique with
        # a clamp and a default; parsing that in a second language (the web
        # layer can already see `uniques`) would put the same rule in two
        # places, free to drift.
        width, height = grid_size(p.player)
        full["player"]["grid"] = {"width": width, "height": height}
        for item in full["player"]["items"]:
            item["name"] = catalog.label(item["prefab_hash"])
            # Presentation only, and additive: `name` stays the prefab name (or
            # #hexhash), because that is what the save hashes and what the CLI
            # and `item_add` accept. A consumer that shows only the display name
            # would leave the user unable to add or cross-reference the item.
            item["display_name"] = catalog.display(item["prefab_hash"]) or item["name"]
            # `durability` and `equipped` are computed properties on the Item
            # dataclass (see model.py), so dataclasses.fields()-based
            # serialization in _jsonable() only emits the raw fields they're
            # derived from (`durability_x100`, `flags`). Every JSON consumer
            # wants the same human-readable values render.item_line() already
            # uses for its own display, so add them here rather than making
            # each consumer re-derive them (a `flags & EQUIPPED` bit test is
            # exactly the kind of format knowledge that should stay out of a
            # JSON consumer like the web UI).
            item["durability"] = item["durability_x100"] * 0.01
            item["equipped"] = bool(item["flags"] & EQUIPPED)
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
        lines.append("  " + item_line(it, catalog))
    return "\n".join(lines)


def item_line(it, catalog: ItemCatalog) -> str:
    # The prefab name keeps the aligned column -- it is what `fch inv add`
    # takes, so it stays the thing you can read straight down the list. The
    # in-game name trails, and only when it says something the prefab doesn't.
    name = catalog.label(it.prefab_hash)
    display = catalog.display(it.prefab_hash)
    extra = "".join([" [equipped]" if it.equipped else "", f" q{it.quality}" if it.quality != 1 else "",
                     f" by {it.crafter_name}" if it.crafter_name else "",
                     f"  ({display})" if display and display != name else ""])
    return f"({it.x},{it.y}) {name:<24} x{it.stack:<4} dur {it.durability:g}{extra}"


def _pt(v) -> str:
    return "(" + ", ".join(f"{c:.1f}" for c in v) + ")"


def f32_text(v: float) -> str:
    """Shortest decimal that reads back as the same 32-bit float.

    0.800000011920929 prints as 0.8, yet two f32 values that differ only in the
    last bit still print differently (f32 needs up to 9 significant digits).
    """
    if not math.isfinite(v):
        return repr(v)
    bits = F32.pack(v)
    for digits in range(1, 10):
        text = f"{v:.{digits}g}"
        if F32.pack(float(text)) == bits:
            return repr(float(text))
    return repr(v)


def _fmt(v) -> str:
    if isinstance(v, F32Bits):
        return repr(v) if math.isnan(v.value) else f32_text(v.value)
    if isinstance(v, float):
        return f32_text(v)
    if isinstance(v, tuple):
        return "(" + ", ".join(_fmt(x) for x in v) + ")"
    return repr(v)


# A record's own fields, e.g. "player.items[(2,3)].stack" under "player.items[(2,3)]".
# `diff()` sorts paths, so every field of one record is contiguous in the list.
# Non-greedy: the record is the FIRST bracket group, even when a field further
# along the same path has its own bracket (e.g. custom_data['key']).
_RECORD = re.compile(r"^(.+?\[[^\[\]]*\])(\.|$)")


def diff_text(changes: list[tuple[str, object, object]]) -> str:
    if not changes:
        return "no differences"
    lines, i, n = [], 0, len(changes)
    while i < n:
        path, old, new = changes[i]
        m = _RECORD.match(path)
        if m:
            key, j = m.group(1), i
            while j < n and (mm := _RECORD.match(changes[j][0])) and mm.group(1) == key:
                j += 1
            group = changes[i:j]
            # Collapse only a whole record appearing or disappearing, not an edit to it.
            if len(group) > 1 and all(g[1] is None for g in group):
                lines.append(f"{key}: added")
                i = j
                continue
            if len(group) > 1 and all(g[2] is None for g in group):
                lines.append(f"{key}: removed")
                i = j
                continue
        lines.append(f"{path}: {_fmt(old)} -> {_fmt(new)}")
        i += 1
    return "\n".join(lines)
