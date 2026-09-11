"""In-memory model of a Valheim player profile (see docs/fch-format-spec.md).

Every field the file contains has a named home here, so encoding a decoded
model reproduces the original bytes. Collections keep file order: the game
writes dictionaries in insertion order, and reordering them would change bytes.
"""
from dataclasses import dataclass, field

Vec3 = tuple[float, float, float]
StatDict = list[tuple[str, float]]
StrPairs = list[tuple[str, str]]


@dataclass
class StatBlock:
    """Player statistics for one DifficultyRequirement scope (spec §4.1)."""

    stats: list[float]
    known_worlds: StatDict
    known_world_keys: StatDict
    known_commands: StatDict
    enemy_stats: list[StatDict]
    item_pickup: StatDict
    item_craft: StatDict
    pickable: StatDict
    food_eaten: StatDict
    pieces_placed: StatDict


@dataclass
class WorldData:
    """Per-world spawn/logout/death/home points plus the raw minimap blob (spec §4.2)."""

    uid: int
    have_custom_spawn: bool
    spawn_point: Vec3
    have_logout: bool
    logout_point: Vec3
    have_death: bool
    death_point: Vec3
    home_point: Vec3
    map_data: bytes | None  # raw; decode on demand with codec.map_blob


@dataclass
class Pin:
    name: str
    pos: Vec3
    type: int
    checked: bool
    owner_id: int
    author: str


@dataclass
class MapData:
    """Decoded minimap blob (spec §7). Only built when a map is inspected or edited."""

    version: int
    texture_size: int
    explored: bytes
    explored_shared: bytes
    pins: list[Pin]
    public_position: bool


# Item flag bits (spec §6).
PICKED_UP = 0x01
EQUIPPED = 0x02
HAS_QUALITY = 0x04
HAS_STACK = 0x08
HAS_VARIANT = 0x10
HAS_CRAFTER = 0x20
HAS_PREFAB = 0x40
HAS_CUSTOM_DATA = 0x80


@dataclass
class Item:
    """One inventory record. `flags` is kept exactly as read and decides which
    optional fields are encoded; edits must update flags together with fields."""

    durability_x100: int
    x: int
    y: int
    world_level: int
    flags: int
    quality: int = 1
    stack: int = 1
    variant: int = 0
    crafter_id: int = 0
    crafter_name: str = ""
    prefab_hash: int = 0
    custom_data: StrPairs = field(default_factory=list)
    extra_flags: int = 0

    @property
    def equipped(self) -> bool:
        return bool(self.flags & EQUIPPED)

    @property
    def durability(self) -> float:
        return self.durability_x100 * 0.01


@dataclass
class Skill:
    type: int
    level: float
    accumulator: float


@dataclass
class Food:
    name: str
    time: float


@dataclass
class PlayerData:
    """The embedded player blob (spec §5)."""

    version: int
    max_health: float
    health: float
    max_stamina: float
    time_since_death: float
    guardian_power: str
    guardian_power_cooldown: float
    inventory_version: int
    items: list[Item]
    known_recipes: list[str]
    known_stations: list[tuple[str, int]]
    known_materials: list[str]
    shown_tutorials: list[str]
    uniques: list[str]
    trophies: list[str]
    known_biomes: list[str]
    known_texts: StrPairs
    beard: str
    hair: str
    skin_color: Vec3
    hair_color: Vec3
    model_index: int
    foods: list[Food]
    skills_version: int
    skills: list[Skill]
    custom_data: StrPairs
    stamina: float
    max_eitr: float
    eitr: float
    build_ui_state: bytes  # opaque build-menu recents/favorites; game resets it if unreadable


@dataclass
class Profile:
    """The whole .fch payload (spec §4)."""

    version: int
    stat_count: int
    stat_blocks: list[StatBlock]
    first_spawn: bool
    worlds: list[WorldData]
    name: str
    player_id: int
    start_seed: str
    used_cheats: bool
    date_created: int  # Unix seconds
    player: PlayerData | None
    # Original player blob bytes. Encoding uses `player` when it decoded, so this
    # only matters for saves whose player blob could not be decoded (read-only).
    player_raw: bytes | None = field(default=None, repr=False, compare=False)
    player_error: str | None = field(default=None, compare=False)
