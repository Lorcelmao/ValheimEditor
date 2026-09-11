import pytest

from fch_editor import safe_io
from fch_editor.catalog.enums import SKILL_NAMES
from fch_editor.cli import main
from fch_editor.edits.pipeline import apply_edits
from fch_editor.edits.skills import ALL, SetSkillLevel, parse_level, parse_skill
from fch_editor.errors import EditError
from fch_editor.load import load_bytes, load_file

RUN, WOODCUTTING, SWIM = 102, 13, 103


@pytest.fixture
def save(sample_bytes):
    return load_bytes(sample_bytes)


def _skills(profile):
    return {s.type: (s.level, s.accumulator) for s in profile.player.skills}


def test_set_existing_skill_changes_only_that_skill(save):
    result = apply_edits(save, [SetSkillLevel(RUN, 50.0)])
    assert [p for p, _, _ in result.changes] == ["player.skills[Run].level"]
    after = _skills(load_bytes(result.data).profile)
    assert after[RUN] == (50.0, 0.0)
    assert {k: v for k, v in after.items() if k != RUN} == \
        {k: v for k, v in _skills(save.profile).items() if k != RUN}


def test_levels_above_100_are_allowed(save):
    result = apply_edits(save, [SetSkillLevel(RUN, 250.0)])
    assert _skills(load_bytes(result.data).profile)[RUN][0] == 250.0


def test_accumulator_reset_or_kept(save):
    jump = 100  # sample: level 99.475, progress 3.75
    reset = apply_edits(save, [SetSkillLevel(jump, 10.0)])
    kept = apply_edits(save, [SetSkillLevel(jump, 10.0, keep_progress=True)])
    assert _skills(reset.profile)[jump] == (10.0, 0.0)
    assert _skills(kept.profile)[jump] == (10.0, 3.75)


def test_unused_skill_is_added(save):
    assert SWIM not in _skills(save.profile)
    result = apply_edits(save, [SetSkillLevel(SWIM, 10.0)])
    assert _skills(load_bytes(result.data).profile)[SWIM] == (10.0, 0.0)
    assert len(result.profile.player.skills) == len(save.profile.player.skills) + 1


def test_all_sets_every_defined_skill(save):
    result = apply_edits(save, [SetSkillLevel(ALL, 100.0)])
    after = _skills(load_bytes(result.data).profile)
    assert set(after) == set(SKILL_NAMES) and all(v == (100.0, 0.0) for v in after.values())
    assert all(p.startswith("player.skills") for p, _, _ in result.changes)


def test_unchanged_value_yields_no_changes(save):
    assert apply_edits(save, [SetSkillLevel(RUN, 100.0, keep_progress=True)]).changes == []


@pytest.mark.parametrize("text", ["-1", "nan", "inf", "abc", "1e39"])
def test_invalid_levels_rejected(text):
    with pytest.raises(EditError):
        SetSkillLevel(RUN, parse_level(text))


def test_edit_validates_without_the_cli():
    with pytest.raises(EditError):
        SetSkillLevel(RUN, float("nan"))
    with pytest.raises(EditError, match="unknown skill type"):
        SetSkillLevel(999, 10.0)


def test_levels_normalised_to_stored_f32(save):
    assert SetSkillLevel(RUN, 1e-50).level == 0.0
    negative_zero = SetSkillLevel(RUN, parse_level("-0")).level
    assert negative_zero == 0.0 and str(negative_zero) == "0.0"  # never written as -0.0
    assert SetSkillLevel(RUN, 0.1).level == 0.10000000149011612
    result = apply_edits(save, [SetSkillLevel(RUN, 1e-50)])  # no false "does not match" refusal
    assert _skills(load_bytes(result.data).profile)[RUN][0] == 0.0


def test_skill_names():
    assert parse_skill("woodcutting") == WOODCUTTING and parse_skill("ALL") == ALL
    with pytest.raises(EditError, match="unknown skill"):
        parse_skill("Rnu")


def test_cli_set_writes_copy_and_leaves_source(sample_bytes, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(safe_io, "is_game_running", lambda: False)
    src, out = tmp_path / "hero.fch", tmp_path / "edited.fch"
    src.write_bytes(sample_bytes)
    assert main(["skills", "set", str(src), "Run=50", "WoodCutting=25", "--out", str(out)]) == 0
    assert src.read_bytes() == sample_bytes
    after = _skills(load_file(out).profile)
    assert after[RUN][0] == 50.0 and after[WOODCUTTING][0] == 25.0
    assert "player.skills[Run].level: 100.0 -> 50.0" in capsys.readouterr().out


def test_cli_dry_run_and_bad_input_write_nothing(sample_bytes, tmp_path, capsys):
    src = tmp_path / "hero.fch"
    src.write_bytes(sample_bytes)
    assert main(["skills", "set", str(src), "Run=50", "--dry-run"]) == 0
    assert main(["skills", "set", str(src), "Run=-5", "--in-place"]) == 1
    assert main(["skills", "set", str(src), "Run", "--in-place"]) == 1
    assert src.read_bytes() == sample_bytes
    assert sorted(p.name for p in tmp_path.iterdir()) == ["hero.fch"]


@pytest.mark.parametrize("args,message", [
    (["Run=50", "Run=60"], "more than once"),
    (["all=10", "Run=60"], "cannot be combined"),
])
def test_cli_rejects_ambiguous_assignments(sample_bytes, tmp_path, capsys, args, message):
    src = tmp_path / "hero.fch"
    src.write_bytes(sample_bytes)
    assert main(["skills", "set", str(src), *args, "--dry-run"]) == 1
    assert message in capsys.readouterr().err


def test_cli_no_change_writes_nothing(sample_bytes, tmp_path, capsys):
    src, out = tmp_path / "hero.fch", tmp_path / "out.fch"
    src.write_bytes(sample_bytes)
    assert main(["skills", "set", str(src), "Run=100", "--keep-progress", "--out", str(out)]) == 0
    assert "nothing to change" in capsys.readouterr().out and not out.exists()


def test_cli_requires_destination(sample_bytes, tmp_path):
    src = tmp_path / "hero.fch"
    src.write_bytes(sample_bytes)
    with pytest.raises(SystemExit):
        main(["skills", "set", str(src), "Run=50"])


def test_cli_list(sample_bytes, tmp_path, capsys):
    src = tmp_path / "hero.fch"
    src.write_bytes(sample_bytes)
    assert main(["skills", "list", str(src)]) == 0
    out = capsys.readouterr().out
    assert "Crafting" in out and "1000" in out
