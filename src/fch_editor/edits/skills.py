"""Skill level edits (spec §5.1).

Levels above 100 are valid: the game stores and displays them, and only caps
progression and gameplay effect at 100. So any finite level >= 0 that fits a
32-bit float is accepted. Setting a skill the character never used adds it;
the game loads any defined SkillType.
"""
from dataclasses import dataclass

from ..catalog.enums import SKILL_IDS, SKILL_NAMES
from ..errors import EditError
from ..model import Profile, Skill
from .values import parse_number, stored_f32

ALL = "all"


def parse_skill(name: str) -> int | str:
    """Skill name (case-insensitive) → SkillType id, or ALL."""
    key = name.strip().lower()
    if key == ALL:
        return ALL
    if key not in SKILL_IDS:
        raise EditError(f"unknown skill {name!r}; known: {', '.join(sorted(SKILL_NAMES.values()))}, all")
    return SKILL_IDS[key]


def parse_level(text: str) -> float:
    return parse_number(text, "skill level")


@dataclass
class SetSkillLevel:
    """Set one skill (or every defined skill) to `level`.

    The accumulator (progress toward the next level) is reset to 0 unless
    `keep_progress`, so the new level starts cleanly. Validated on
    construction, so every caller (CLI or code) gets the same checks.
    """

    skill: int | str
    level: float
    keep_progress: bool = False

    def __post_init__(self):
        if self.skill != ALL and self.skill not in SKILL_NAMES:
            raise EditError(f"unknown skill type {self.skill!r}")
        self.level = stored_f32(self.level, "skill level")

    def apply(self, profile: Profile) -> list[str]:
        if profile.player is None:
            raise EditError("save has no player data")
        skills = profile.player.skills
        targets = list(SKILL_NAMES) if self.skill == ALL else [self.skill]
        for skill_type in targets:
            matches = [s for s in skills if s.type == skill_type]
            if not matches:
                matches = [Skill(skill_type, 0.0, 0.0)]
                skills.append(matches[0])
            for s in matches:
                s.level = self.level
                if not self.keep_progress:
                    s.accumulator = 0.0
        return ["player.skills.count"] + [f"player.skills[{SKILL_NAMES[t]}]" for t in targets]
