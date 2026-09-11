import pytest

from fch_editor import safe_io
from fch_editor.cli import main
from fch_editor.edits import character as ch
from fch_editor.edits.pipeline import apply_edits
from fch_editor.errors import EditError
from fch_editor.load import load_bytes, load_file


@pytest.fixture
def save(sample_bytes):
    return load_bytes(sample_bytes)


@pytest.mark.parametrize("edit,path,check", [
    (ch.SetName("LorceTest"), "name", lambda p: p.name == "LorceTest"),
    (ch.SetBeard("beard5"), "player.beard", lambda p: p.player.beard == "Beard5"),
    (ch.SetHair("HAIR5"), "player.hair", lambda p: p.player.hair == "Hair5"),
    (ch.SetColor("skin_color", (0.9, 0.7, 0.6)), "player.skin_color",
     lambda p: [round(c, 5) for c in p.player.skin_color] == [0.9, 0.7, 0.6]),
    (ch.SetColor("hair_color", (0.0, 0.0, 0.0)), "player.hair_color",
     lambda p: p.player.hair_color == (0.0, 0.0, 0.0)),
    (ch.SetModel(1), "player.model_index", lambda p: p.player.model_index == 1),
    (ch.SetGuardianPower("GP_Eikthyr"), "player.guardian_power", lambda p: p.player.guardian_power == "GP_Eikthyr"),
    (ch.SetGuardianCooldown(300), "player.guardian_power_cooldown",
     lambda p: p.player.guardian_power_cooldown == 300.0),
])
def test_each_edit_changes_exactly_its_field(save, edit, path, check):
    result = apply_edits(save, [edit])
    assert [p for p, _, _ in result.changes] == [path]
    assert check(load_bytes(result.data).profile)


def test_combined_edits_and_items_keep_crafter_name(save):
    result = apply_edits(save, [ch.SetName("LorceTest"), ch.SetHair("Hair5"), ch.SetGuardianPower("GP_Queen")])
    out = load_bytes(result.data).profile
    assert (out.name, out.player.hair, out.player.guardian_power) == ("LorceTest", "Hair5", "GP_Queen")
    assert {i.crafter_name for i in out.player.items if i.crafter_name} == {"Lorce"}


@pytest.mark.parametrize("name", ["ab", " Lorce", "Lorce ", "Lo\nrce", "x" * 65, "   ",
                                  "Lo rce", "Lorce", "Lo͸rce", "Lo‍rce"])
def test_bad_names_rejected(name):
    with pytest.raises(EditError):
        ch.SetName(name)


def test_non_ascii_name_roundtrips(save):
    result = apply_edits(save, [ch.SetName("Lộc Ragnar")])
    assert load_bytes(result.data).profile.name == "Lộc Ragnar"


def test_unknown_styles_need_opt_in(save):
    with pytest.raises(EditError, match="unknown hair"):
        ch.SetHair("Hair99")
    edit = ch.SetHair("Hair99", allow_unknown=True)
    assert load_bytes(apply_edits(save, [edit]).data).profile.player.hair == "Hair99"
    assert ch.SetBeard(" beard5 ").style == "Beard5"  # trimmed, canonical casing


@pytest.mark.parametrize("style", ["", "Beard 5", "Hair1", "Beard" + "x" * 100, "Beard-5"])
def test_unknown_styles_must_look_like_prefab_names(style):
    with pytest.raises(EditError):
        ch.SetBeard(style, allow_unknown=True)


@pytest.mark.parametrize("text,expected", [
    ("Eikthyr", "GP_Eikthyr"), ("gp_theelder", "GP_TheElder"), ("Fader", "GP_Ashlands"),
    ("ashlands", "GP_Ashlands"), ("DeepNorth", "GP_DeepNorth"), ("none", ""), (" NONE ", ""),
])
def test_guardian_power_names(text, expected):
    assert ch.parse_guardian_power(text) == expected


def test_invalid_values_rejected():
    for bad in (lambda: ch.parse_guardian_power("Odin"), lambda: ch.SetGuardianPower("GP_Odin"),
                lambda: ch.SetModel(2), lambda: ch.SetColor("skin_color", (1.0, float("nan"), 0.0)),
                lambda: ch.SetColor("skin_color", (-0.1, 0.0, 0.0)), lambda: ch.parse_color("1,2"),
                lambda: ch.SetGuardianCooldown(-5), lambda: ch.SetColor("eye_color", (0, 0, 0)),
                lambda: ch.parse_guardian_power(""), lambda: ch.parse_guardian_power("GP_"),
                lambda: ch.SetColor("skin_color", (1.0, 1.0)), lambda: ch.SetModel(True),
                lambda: ch.SetModel(1.0)):
        with pytest.raises(EditError):
            bad()


def test_cli_show_and_set(sample_bytes, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(safe_io, "is_game_running", lambda: False)
    src, out = tmp_path / "hero.fch", tmp_path / "lorcetest.fch"
    src.write_bytes(sample_bytes)
    assert main(["char", "show", str(src)]) == 0
    assert "Hair24" in capsys.readouterr().out
    assert main(["char", "set", str(src), "--name", "LorceTest", "--hair", "Hair5", "--guardian-power",
                 "eikthyr", "--gp-cooldown", "0", "--skin", "0.9,0.7,0.6", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "player.skin_color: (0.8, 0.8, 0.8) -> (0.9, 0.7, 0.6)" in printed
    p = load_file(out).profile
    assert (p.name, p.player.hair, p.player.guardian_power) == ("LorceTest", "Hair5", "GP_Eikthyr")
    assert src.read_bytes() == sample_bytes


def test_cli_set_requires_a_field(sample_bytes, tmp_path, capsys):
    src = tmp_path / "hero.fch"
    src.write_bytes(sample_bytes)
    assert main(["char", "set", str(src), "--dry-run"]) == 1
    assert "at least one field" in capsys.readouterr().err
