"""Inventory section, item version 109 (spec §6)."""
from .. import versions
from ..errors import UnsupportedVersion
from ..model import (HAS_CRAFTER, HAS_CUSTOM_DATA, HAS_PREFAB, HAS_QUALITY, HAS_STACK,
                     HAS_VARIANT, Item)
from ..reader import Reader
from ..writer import Writer

_MIN_ITEM_SIZE = 9  # durability + x + y + worldLevel + flags + extraFlags


def decode_item(r: Reader) -> Item:
    dur, x, y, world_level, flags = r.i32(), r.u8(), r.u8(), r.u8(), r.u8()
    item = Item(durability_x100=dur, x=x, y=y, world_level=world_level, flags=flags)
    if flags & HAS_QUALITY:
        item.quality = r.u16()
    if flags & HAS_STACK:
        item.stack = r.u16()
    if flags & HAS_VARIANT:
        item.variant = r.i32()
    if flags & HAS_CRAFTER:
        item.crafter_id = r.i64()
        item.crafter_name = r.string()
    if flags & HAS_PREFAB:
        item.prefab_hash = r.i32()
    if flags & HAS_CUSTOM_DATA:
        at = r.offset
        n = r.num_items()
        if n * 2 > r.remaining:
            raise r.error(f"implausible custom data count {n}", at)
        item.custom_data = [(r.string(), r.string()) for _ in range(n)]
    item.extra_flags = r.u8()
    return item


def _check_flags(item: Item) -> None:
    """A value whose flag bit is clear would be silently dropped from the file."""
    f = item.flags
    unflagged = [name for bit, name, is_default in (
        (HAS_QUALITY, "quality", item.quality == 1),
        (HAS_STACK, "stack", item.stack == 1),
        (HAS_VARIANT, "variant", item.variant == 0),
        (HAS_CRAFTER, "crafter", item.crafter_id == 0 and item.crafter_name == ""),
        (HAS_PREFAB, "prefab_hash", item.prefab_hash == 0),
        (HAS_CUSTOM_DATA, "custom_data", not item.custom_data),
    ) if not f & bit and not is_default]
    if unflagged:
        raise ValueError(f"item at ({item.x},{item.y}) sets {', '.join(unflagged)} without the matching flag bit")


def encode_item(w: Writer, item: Item) -> None:
    _check_flags(item)
    f = item.flags
    w.i32(item.durability_x100)
    w.u8(item.x)
    w.u8(item.y)
    w.u8(item.world_level)
    w.u8(f)
    if f & HAS_QUALITY:
        w.u16(item.quality)
    if f & HAS_STACK:
        w.u16(item.stack)
    if f & HAS_VARIANT:
        w.i32(item.variant)
    if f & HAS_CRAFTER:
        w.i64(item.crafter_id)
        w.string(item.crafter_name)
    if f & HAS_PREFAB:
        w.i32(item.prefab_hash)
    if f & HAS_CUSTOM_DATA:
        w.num_items(len(item.custom_data))
        for k, v in item.custom_data:
            w.string(k)
            w.string(v)
    w.u8(item.extra_flags)


def decode_inventory(r: Reader) -> tuple[int, list[Item]]:
    at = r.offset
    version = r.i32()
    if version != versions.INVENTORY:
        raise UnsupportedVersion(f"inventory version {version} at 0x{at:x}, supported {versions.INVENTORY}")
    at = r.offset
    n = r.u16()
    if n * _MIN_ITEM_SIZE > r.remaining:
        raise r.error(f"implausible item count {n}", at)
    items = []
    for i in range(n):
        with r.scope(f"items[{i}]"):
            items.append(decode_item(r))
    return version, items


def encode_inventory(w: Writer, version: int, items: list[Item]) -> None:
    w.i32(version)
    w.u16(len(items))
    for item in items:
        encode_item(w, item)
