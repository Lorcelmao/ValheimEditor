"""Skills section, version 2 (spec §5.1)."""
from .. import versions
from ..errors import UnsupportedVersion
from ..model import Skill
from ..reader import Reader
from ..writer import Writer


def decode_skills(r: Reader) -> tuple[int, list[Skill]]:
    at = r.offset
    version = r.i32()
    if version != versions.SKILLS:
        raise UnsupportedVersion(f"skills version {version} at 0x{at:x}, supported {versions.SKILLS}")
    return version, [Skill(r.i32(), r.f32(), r.f32()) for _ in range(r.count(12))]


def encode_skills(w: Writer, version: int, skills: list[Skill]) -> None:
    w.i32(version)
    w.i32(len(skills))
    for s in skills:
        w.i32(s.type)
        w.f32(s.level)
        w.f32(s.accumulator)
