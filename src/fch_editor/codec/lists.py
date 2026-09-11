"""Counted collections shared by several sections: i32 count, then elements."""
from ..reader import Reader
from ..writer import Writer


def read_strings(r: Reader) -> list[str]:
    return [r.string() for _ in range(r.count(1))]


def write_strings(w: Writer, items: list[str]) -> None:
    w.i32(len(items))
    for s in items:
        w.string(s)


def read_string_pairs(r: Reader) -> list[tuple[str, str]]:
    return [(r.string(), r.string()) for _ in range(r.count(2))]


def write_string_pairs(w: Writer, items: list[tuple[str, str]]) -> None:
    w.i32(len(items))
    for k, v in items:
        w.string(k)
        w.string(v)


def read_string_floats(r: Reader) -> list[tuple[str, float]]:
    return [(r.string(), r.f32()) for _ in range(r.count(5))]


def write_string_floats(w: Writer, items: list[tuple[str, float]]) -> None:
    w.i32(len(items))
    for k, v in items:
        w.string(k)
        w.f32(v)
