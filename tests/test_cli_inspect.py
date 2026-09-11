import io
import json
import shutil
import sys

import pytest

from fch_editor.cli import main
from fch_editor.load import encode_save, load_bytes


@pytest.fixture
def sample_file(sample_bytes, tmp_path):
    path = tmp_path / "hero.fch"
    path.write_bytes(sample_bytes)
    return path


def test_info(sample_file, capsys):
    assert main(["info", str(sample_file)]) == 0
    out = capsys.readouterr().out
    assert "Writable  : yes" in out and "Lorce" in out
    assert "Wood" in out and "Crafting 1000" in out


def test_dump_json_sections(sample_file, capsys):
    assert main(["dump", str(sample_file), "--section", "inventory"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["writable"] is True
    assert {i["name"] for i in doc["inventory"]} >= {"Wood", "Torch", "Bow"}
    assert main(["dump", str(sample_file)]) == 0
    full = json.loads(capsys.readouterr().out)
    assert full["profile"]["worlds"][1]["map"]["pins"][0]["name"] == "$enemy_eikthyr"
    assert full["profile"]["stat_blocks"][6]["scope"] == "Default"


def test_verify_ok_and_fail(sample_file, tmp_path, capsys):
    assert main(["verify", str(sample_file)]) == 0
    broken = tmp_path / "broken.fch"
    data = bytearray(sample_file.read_bytes())
    data[4:8] = (47).to_bytes(4, "little")  # unsupported profile version
    broken.write_bytes(bytes(data))
    assert main(["verify", str(broken)]) == 1
    assert "profile version 47" in capsys.readouterr().out


def test_diff_exit_codes(sample_file, tmp_path, capsys):
    same = tmp_path / "same.fch"
    shutil.copy(sample_file, same)
    assert main(["diff", str(sample_file), str(same)]) == 0
    assert "no differences" in capsys.readouterr().out


def _save_with(sample_bytes, tmp_path, filename, **changes):
    save = load_bytes(sample_bytes)
    for key, value in changes.items():
        setattr(save.profile, key, value)
    path = tmp_path / filename
    path.write_bytes(encode_save(save.profile))
    return path


def test_non_ascii_output_on_cp1252_stream(sample_bytes, tmp_path, monkeypatch):
    path = _save_with(sample_bytes, tmp_path, "hero.fch", name="Lộc 🐗")
    buf = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(buf, encoding="cp1252"))
    assert main(["info", str(path)]) == 0
    sys.stdout.flush()
    assert "Lộc 🐗" in buf.getvalue().decode("utf-8")


def test_diff_reports_changes_with_exit_1(sample_file, sample_bytes, tmp_path, capsys):
    other = _save_with(sample_bytes, tmp_path, "other.fch", name="Renamed")
    assert main(["diff", str(sample_file), str(other)]) == 1
    assert "name: 'Lorce' -> 'Renamed'" in capsys.readouterr().out


def test_items_option_after_subcommand(sample_file, tmp_path, capsys):
    extra = tmp_path / "items.txt"
    extra.write_text("BrandNewItem\n", encoding="utf-8")
    assert main(["info", str(sample_file), "--items", str(extra)]) == 0


def test_info_survives_bad_date_and_broken_map(sample_bytes, tmp_path, capsys):
    save = load_bytes(sample_bytes)
    save.profile.date_created = 2**62
    save.profile.worlds[0].map_data = (8).to_bytes(4, "little") + (3).to_bytes(4, "little") + b"bad"
    path = tmp_path / "odd.fch"
    path.write_bytes(encode_save(save.profile))
    assert main(["info", str(path)]) == 0
    out = capsys.readouterr().out
    assert "invalid timestamp" in out and "map error:" in out


def test_not_an_fch_file_is_a_clean_error(tmp_path, capsys):
    junk = tmp_path / "junk.fch"
    junk.write_bytes(b"not a save")
    assert main(["info", str(junk)]) == 1
    assert capsys.readouterr().err.startswith("error:")
    assert main(["info", str(tmp_path / "missing.fch")]) == 1
