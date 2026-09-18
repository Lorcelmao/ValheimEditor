"""Inventory edits: set stack/durability, remove, add by prefab name (spec §6).

Conservative on purpose: no quality/variant/customData editing, no equip
toggling, no moving an existing item (only setting fields on it). Items with
an unrecognised prefab hash are always safe to list, move past, or remove —
only *adding* a name needs it to resolve to a real prefab, because the game
deletes an item whose hash it does not recognise on load.
"""
import copy
import math
from dataclasses import dataclass

from ..errors import EditError
from ..model import (EQUIPPED, HAS_CRAFTER, HAS_PREFAB, HAS_QUALITY, HAS_STACK, PICKED_UP, Item,
                    PlayerData, Profile)
from ..stable_hash import stable_hash

GRID_WIDTH = 8
DEFAULT_GRID_HEIGHT = 4
DEFAULT_DURABILITY = 100.0  # matches every non-degrading item in the sample save


def grid_size(player: PlayerData) -> tuple[int, int]:
    """(width, height) of the inventory grid; height comes from the unique `invrows N`."""
    height = DEFAULT_GRID_HEIGHT
    for u in player.uniques:
        name, _, value = u.partition(" ")
        if name == "invrows":
            try:
                height = max(0, min(9, int(value)))
            except ValueError:
                pass
    return GRID_WIDTH, height


def parse_slot(text: str) -> tuple[int, int]:
    parts = text.split(",")
    if len(parts) != 2:
        raise EditError(f"slot must be X,Y (e.g. 3,0), got {text!r}")
    try:
        x, y = (int(p) for p in parts)
    except ValueError:
        raise EditError(f"slot must be two integers, got {text!r}") from None
    return x, y


def _player(profile: Profile) -> PlayerData:
    if profile.player is None:
        raise EditError("save has no player data")
    return profile.player


def _find(player: PlayerData, slot: tuple[int, int]) -> Item:
    matches = [i for i in player.items if (i.x, i.y) == slot]
    if not matches:
        raise EditError(f"no item at slot {slot[0]},{slot[1]}")
    if len(matches) > 1:
        # Two items sharing a slot means the save is already inconsistent; picking one silently
        # would misattribute the change (and the diff shown before writing) to the wrong item.
        raise EditError(f"{len(matches)} items occupy slot {slot[0]},{slot[1]} in this save; "
                        "refusing to guess which one you mean")
    return matches[0]


def _find_free_slot(items: list[Item], width: int, height: int) -> tuple[int, int]:
    occupied = {(i.x, i.y) for i in items}
    for y in range(height):
        for x in range(width):
            if (x, y) not in occupied:
                return x, y
    raise EditError(f"inventory is full ({width}x{height}); free a slot or pass --slot to replace one")


def to_durability_x100(value: float) -> int:
    if not math.isfinite(value) or value < 0:
        raise EditError(f"durability must be a finite number >= 0, got {value!r}")
    x100 = round(value * 100)
    if not -(2**31) <= x100 < 2**31:
        raise EditError(f"durability {value:g} is too large to store")
    return x100


def _scope(slot: tuple[int, int]) -> str:
    return f"player.items[({slot[0]},{slot[1]})]"


@dataclass
class SetItemField:
    """Set stack, durability, and/or quality on the item already at `slot`.

    `durability` takes the human-readable units `fch info`/`fch inv list` show
    (e.g. 100.0); it is converted to the file's x100 int once, up front.

    `quality` (the upgrade level shown in-game) has no upper bound here beyond
    the format's own u16 storage ceiling. The old vanilla max of 4 is no longer
    a real rule: the Ashlands "Forge of Potential" already pushes items past it
    using idols, and no confirmed cap exists post-Ashlands -- inventing one here
    would be a wrong guess dressed as a safety rail. An existing, trusted
    community save editor bundled in this repo for reference (REFERENCES/VPE.exe)
    validates quality the same way: a positive integer, nothing more.
    """

    slot: tuple[int, int]
    stack: int | None = None
    durability: float | None = None
    quality: int | None = None

    def __post_init__(self):
        if self.stack is None and self.durability is None and self.quality is None:
            raise EditError("give at least one of stack, durability, or quality")
        if self.stack is not None and not 1 <= self.stack <= 65535:
            raise EditError(f"stack must be 1-65535, got {self.stack}")
        if self.quality is not None and not 1 <= self.quality <= 65535:
            raise EditError(f"quality must be 1-65535, got {self.quality}")
        self._durability_x100 = to_durability_x100(self.durability) if self.durability is not None else None

    def apply(self, profile: Profile) -> list[str]:
        item = _find(_player(profile), self.slot)
        if self.quality is not None:
            item.quality = self.quality
            # Keep the flag consistent with the value: quality 1 needs no field at all.
            item.flags = (item.flags | HAS_QUALITY) if self.quality != 1 else (item.flags & ~HAS_QUALITY)
        if self.stack is not None:
            item.stack = self.stack
            # Keep the flag consistent with the value: a stack of 1 needs no field at all.
            item.flags = (item.flags | HAS_STACK) if self.stack != 1 else (item.flags & ~HAS_STACK)
        if self._durability_x100 is not None:
            item.durability_x100 = self._durability_x100
        return [_scope(self.slot)]


@dataclass
class RemoveItem:
    slot: tuple[int, int]

    def apply(self, profile: Profile) -> list[str]:
        player = _player(profile)
        item = _find(player, self.slot)
        player.items.remove(item)
        return ["player.items.count", _scope(self.slot)]


@dataclass
class CopyItem:
    """Duplicate the item at `slot` into the first free slot, keeping what makes
    it that item -- upgrade level, variant, crafter, custom data -- rather than
    the pristine level-1 item AddItem alone would produce."""

    slot: tuple[int, int]

    def apply(self, profile: Profile) -> list[str]:
        player = _player(profile)
        source = _find(player, self.slot)  # raises the existing not-found/ambiguous-slot errors
        width, height = grid_size(player)
        free = _find_free_slot(player.items, width, height)  # raises the existing "inventory is full"
        # A deep copy, not a field-by-field reconstruction: `custom_data` is a
        # list and `flags` decides which optional fields the encoder writes
        # (see model.py's Item docstring), so copying both wholesale is what
        # keeps them paired correctly and carries any field Item gains later.
        item = copy.deepcopy(source)
        item.x, item.y = free
        # Two items flagged EQUIPPED for one slot type is a state the game does
        # not produce; PICKED_UP stays, since the copy is genuinely in the
        # inventory.
        item.flags &= ~EQUIPPED
        player.items.append(item)
        return ["player.items.count", _scope(free)]


@dataclass
class AddItem:
    """Add a new item by prefab name. `prefab_hash` is resolved by the caller
    (the CLI checks it against the item catalog first, since an unresolved
    name would make the game silently delete the item on load)."""

    prefab_name: str
    prefab_hash: int
    stack: int = 1
    slot: tuple[int, int] | None = None
    durability: float = DEFAULT_DURABILITY
    crafted_by_me: bool = False

    def __post_init__(self):
        if not 1 <= self.stack <= 65535:
            raise EditError(f"stack must be 1-65535, got {self.stack}")
        self.durability = to_durability_x100(self.durability)
        if self.slot is not None:
            x, y = self.slot
            if x < 0 or y < 0:
                raise EditError(f"slot must be non-negative, got {x},{y}")

    def apply(self, profile: Profile) -> list[str]:
        player = _player(profile)
        width, height = grid_size(player)
        if self.slot is not None:
            x, y = self.slot
            if x >= width or y >= height:
                raise EditError(f"slot {x},{y} is outside the {width}x{height} inventory grid")
            if any((i.x, i.y) == self.slot for i in player.items):
                raise EditError(f"slot {x},{y} is already occupied; remove that item first or choose another slot")
            slot = self.slot
        else:
            slot = _find_free_slot(player.items, width, height)
        item = Item(durability_x100=self.durability, x=slot[0], y=slot[1], world_level=0,
                   flags=PICKED_UP | HAS_PREFAB, prefab_hash=self.prefab_hash)
        if self.stack != 1:
            item.stack = self.stack
            item.flags |= HAS_STACK
        if self.crafted_by_me:
            item.crafter_id = profile.player_id
            item.crafter_name = profile.name
            item.flags |= HAS_CRAFTER
        player.items.append(item)
        return ["player.items.count", _scope(slot)]


def parse_prefab_hash(name: str) -> int:
    return stable_hash(name)
