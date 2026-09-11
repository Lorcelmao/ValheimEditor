"""Character identity and appearance edits (spec §4, §5).

One edit per field, each declaring the single diff path it may change. Health
and stamina are deliberately absent: the game recomputes maximums and resets
out-of-range health on load, so edits to them would not stick.
"""
import re
import unicodedata
from dataclasses import dataclass

from ..catalog.appearance import BEARDS, GUARDIAN_POWERS, HAIRS
from ..errors import EditError
from ..model import PlayerData, Profile
from .values import stored_f32

MIN_NAME_LENGTH = 3  # the game's character-creation screen requires at least 3 characters
MAX_NAME_LENGTH = 64  # generous guard; the in-game input field is shorter


def _player(profile: Profile) -> PlayerData:
    if profile.player is None:
        raise EditError("save has no player data")
    return profile.player


@dataclass
class SetName:
    """Display name only. The file name on disk (the game uses the lowercased
    name at creation) and crafter names on existing items stay as they are."""

    name: str

    def __post_init__(self):
        if not MIN_NAME_LENGTH <= len(self.name) <= MAX_NAME_LENGTH:
            raise EditError(f"name must be {MIN_NAME_LENGTH}-{MAX_NAME_LENGTH} characters, got {len(self.name)}")
        # Other (C*: control, format, surrogate, private-use, unassigned) and line/paragraph separators.
        if any(unicodedata.category(c)[0] == "C" or unicodedata.category(c) in ("Zl", "Zp") for c in self.name):
            raise EditError("name must not contain control, invisible or unassigned characters")
        if self.name != self.name.strip():
            raise EditError("name must not start or end with spaces")

    def apply(self, profile: Profile) -> list[str]:
        profile.name = self.name
        return ["name"]


def _style(value: str, known: list[str], what: str, allow_unknown: bool) -> str:
    value = value.strip()
    match = next((k for k in known if k.lower() == value.lower()), None)
    if match:
        return match
    if not allow_unknown:
        raise EditError(f"unknown {what} {value!r} (known: {known[0]} … {known[-1]}); "
                        f"use --allow-unknown-style for styles added in newer game versions")
    # Even unknown styles must look like the game's prefab names (Beard…/Hair…).
    prefix = known[0][:known[0].index("None")]
    if not re.fullmatch(prefix + r"[A-Za-z0-9_]{1,40}", value):
        raise EditError(f"{what} style must look like {prefix}<letters/digits/_>, got {value!r}")
    return value


@dataclass
class SetBeard:
    style: str
    allow_unknown: bool = False

    def __post_init__(self):
        self.style = _style(self.style, BEARDS, "beard", self.allow_unknown)

    def apply(self, profile: Profile) -> list[str]:
        _player(profile).beard = self.style
        return ["player.beard"]


@dataclass
class SetHair:
    style: str
    allow_unknown: bool = False

    def __post_init__(self):
        self.style = _style(self.style, HAIRS, "hair", self.allow_unknown)

    def apply(self, profile: Profile) -> list[str]:
        _player(profile).hair = self.style
        return ["player.hair"]


def parse_color(text: str) -> tuple[float, float, float]:
    parts = text.split(",")
    if len(parts) != 3:
        raise EditError(f"color must be R,G,B (e.g. 0.8,0.8,0.8), got {text!r}")
    try:
        return tuple(float(p) for p in parts)
    except ValueError:
        raise EditError(f"color must be three numbers, got {text!r}") from None


@dataclass
class SetColor:
    """Skin or hair color, stored as three floats (the game applies no range checks)."""

    field: str  # "skin_color" or "hair_color"
    rgb: tuple[float, float, float]

    def __post_init__(self):
        if self.field not in ("skin_color", "hair_color"):
            raise EditError(f"unknown color field {self.field!r}")
        if len(self.rgb) != 3:
            raise EditError(f"color needs exactly 3 components (R,G,B), got {len(self.rgb)}")
        self.rgb = tuple(stored_f32(c, self.field.replace("_", " ")) for c in self.rgb)

    def apply(self, profile: Profile) -> list[str]:
        setattr(_player(profile), self.field, self.rgb)
        return [f"player.{self.field}"]


@dataclass
class SetModel:
    index: int

    def __post_init__(self):
        if type(self.index) is not int or self.index not in (0, 1):
            raise EditError(f"body model must be 0 or 1, got {self.index!r}")

    def apply(self, profile: Profile) -> list[str]:
        _player(profile).model_index = self.index
        return ["player.model_index"]


def parse_guardian_power(text: str) -> str:
    """'none', a power id (GP_Eikthyr) or its boss name (Eikthyr, Fader), case-insensitive."""
    key = text.strip().lower()
    if key == "none":  # only the explicit word: an empty value (e.g. unset variable) must not clear it
        return ""
    for power_id, boss in GUARDIAN_POWERS.items():
        if key in (power_id.lower(), power_id[3:].lower(), boss.lower()):
            return power_id
    raise EditError(f"unknown guardian power {text!r}; known: {', '.join(GUARDIAN_POWERS)}, none")


@dataclass
class SetGuardianPower:
    power: str  # a GUARDIAN_POWERS id, or "" for none

    def __post_init__(self):
        if self.power and self.power not in GUARDIAN_POWERS:
            raise EditError(f"unknown guardian power {self.power!r}")

    def apply(self, profile: Profile) -> list[str]:
        _player(profile).guardian_power = self.power
        return ["player.guardian_power"]


@dataclass
class SetGuardianCooldown:
    seconds: float

    def __post_init__(self):
        self.seconds = stored_f32(self.seconds, "guardian power cooldown")

    def apply(self, profile: Profile) -> list[str]:
        _player(profile).guardian_power_cooldown = self.seconds
        return ["player.guardian_power_cooldown"]
