"""The shared edit pipeline: scope checks, write-back verification, safe writing."""
import copy
from dataclasses import dataclass

import pytest

from fch_editor import safe_io
from fch_editor.edits import pipeline
from fch_editor.edits.pipeline import apply_edits, check_destination, write_result
from fch_editor.errors import UnsafeWrite
from fch_editor.load import load_bytes, load_file


@dataclass
class Rename:
    name: str
    scope: list[str]

    def apply(self, profile):
        profile.name = self.name
        return self.scope


@pytest.fixture
def save(sample_bytes):
    return load_bytes(sample_bytes)


@pytest.fixture(autouse=True)
def game_not_running(monkeypatch):
    monkeypatch.setattr(safe_io, "is_game_running", lambda: False)


def test_in_scope_edit_produces_verified_bytes(save):
    result = apply_edits(save, [Rename("Hero", ["name"])])
    assert [p for p, _, _ in result.changes] == ["name"]
    assert load_bytes(result.data).profile.name == "Hero"


def test_out_of_scope_change_is_refused(save):
    with pytest.raises(UnsafeWrite, match="outside its scope"):
        apply_edits(save, [Rename("Hero", ["player.skills"])])


def test_scope_prefix_rules():
    assert pipeline._in_scope("player.skills[Run].level", ["player.skills[Run]"])
    assert pipeline._in_scope("player.skills[Run#1].level", ["player.skills[Run]"])
    assert not pipeline._in_scope("player.skills[Runner].level", ["player.skills[Run]"])
    assert not pipeline._in_scope("player.skills.count", ["player.skills[Run]"])


def test_read_only_save_is_refused(save):
    save.reasons.append("pretend it is unsupported")
    with pytest.raises(UnsafeWrite, match="read-only"):
        apply_edits(save, [Rename("Hero", ["name"])])


def test_write_requires_exactly_one_destination(save, tmp_path):
    result = apply_edits(save, [Rename("Hero", ["name"])])
    src = tmp_path / "hero.fch"
    src.write_bytes(save.original)
    with pytest.raises(UnsafeWrite, match="exactly one"):
        write_result(result, src, None, in_place=False)
    with pytest.raises(UnsafeWrite, match="--in-place"):
        write_result(result, src, src, in_place=False)


def test_write_out_and_in_place(save, tmp_path):
    result = apply_edits(save, [Rename("Hero", ["name"])])
    src = tmp_path / "hero.fch"
    src.write_bytes(save.original)
    out = tmp_path / "copy.fch"
    assert write_result(result, src, out, in_place=False) is None
    assert load_file(out).profile.name == "Hero" and src.read_bytes() == save.original
    backup = write_result(result, src, None, in_place=True)
    assert load_file(src).profile.name == "Hero" and backup.read_bytes() == save.original


def test_destination_checks(save, tmp_path):
    src = tmp_path / "hero.fch"
    src.write_bytes(save.original)
    existing = tmp_path / "other.fch"
    existing.write_bytes(b"another character")
    with pytest.raises(UnsafeWrite, match="is a folder"):
        check_destination(src, tmp_path, in_place=False)
    with pytest.raises(UnsafeWrite, match="does not exist"):
        check_destination(src, tmp_path / "missing" / "x.fch", in_place=False)
    with pytest.raises(UnsafeWrite, match="already exists"):
        check_destination(src, existing, in_place=False)
    assert check_destination(src, existing, in_place=False, force=True) == existing


def test_in_place_refuses_if_source_changed_after_reading(save, tmp_path):
    src = tmp_path / "hero.fch"
    src.write_bytes(save.original)
    result = apply_edits(save, [Rename("Hero", ["name"])])
    changed = save.original[:-1] + bytes([save.original[-1] ^ 0xFF])  # the game saved meanwhile
    src.write_bytes(changed)
    with pytest.raises(UnsafeWrite, match="changed since it was read"):
        write_result(result, src, None, in_place=True)
    assert src.read_bytes() == changed


def test_write_back_mismatch_is_refused(save, monkeypatch):
    # An encoder bug that writes something other than the intended model must be caught.
    real_encode = pipeline.encode_save

    def buggy_encode(profile):
        wrong = copy.deepcopy(profile)
        wrong.first_spawn = not wrong.first_spawn
        return real_encode(wrong)

    monkeypatch.setattr(pipeline, "encode_save", buggy_encode)
    with pytest.raises(UnsafeWrite, match="does not match the intended edit at first_spawn"):
        apply_edits(save, [Rename("Hero", ["name"])])


def test_unencodable_value_is_a_clean_error(save):
    @dataclass
    class HugeId:
        def apply(self, profile):
            profile.player_id = 2**70
            return ["player_id"]
    with pytest.raises(UnsafeWrite, match="cannot be saved"):
        apply_edits(save, [HugeId()])


def test_running_game_blocks_write_unless_forced(save, tmp_path, monkeypatch):
    monkeypatch.setattr(safe_io, "is_game_running", lambda: True)
    result = apply_edits(save, [Rename("Hero", ["name"])])
    out = tmp_path / "copy.fch"
    with pytest.raises(UnsafeWrite, match="running"):
        write_result(result, tmp_path / "src.fch", out, in_place=False)
    assert not out.exists()
    write_result(result, tmp_path / "src.fch", out, in_place=False, force=True)
    assert out.exists()
