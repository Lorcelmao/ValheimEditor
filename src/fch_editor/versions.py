"""Section versions this editor decodes and writes (spec §1, game 1.0.7)."""
from .model import HAS_CUSTOM_DATA, HAS_QUALITY, HAS_VARIANT, Profile

PROFILE = 46
PLAYER = 33
INVENTORY = 109
SKILLS = 2
MAP = 8


def code_only_features(profile: Profile) -> list[str]:
    """Sections present in this save whose layout is confirmed from game code
    but not yet by any real save. Writes are allowed; an in-game load test of
    such a save promotes them to fully verified."""
    p = profile.player
    if p is None:
        return []
    found = []
    if p.foods:
        found.append("active foods")
    if p.custom_data:
        found.append("player custom data")
    flags = 0
    for item in p.items:
        flags |= item.flags
    for bit, label in ((HAS_QUALITY, "item quality"), (HAS_VARIANT, "item variants"),
                       (HAS_CUSTOM_DATA, "item custom data")):
        if flags & bit:
            found.append(label)
    return found
