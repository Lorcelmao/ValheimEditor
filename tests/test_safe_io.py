import subprocess

import pytest

from fch_editor import safe_io
from fch_editor.errors import UnsafeWrite


def _reject(_: bytes) -> None:
    raise UnsafeWrite("rejected by verifier")


def test_write_new_file_without_backup(tmp_path):
    target = tmp_path / "hero.fch"
    assert safe_io.write_verified(target, b"new", lambda b: None) is None
    assert target.read_bytes() == b"new"


def test_overwrite_makes_backup_with_original_contents(tmp_path):
    target = tmp_path / "hero.fch"
    target.write_bytes(b"original")
    backup = safe_io.write_verified(target, b"edited", lambda b: None)
    assert target.read_bytes() == b"edited"
    assert backup.read_bytes() == b"original"
    assert backup.name.startswith("hero.fch.bak-")


def test_verifier_sees_bytes_on_disk(tmp_path):
    seen = []
    safe_io.write_verified(tmp_path / "hero.fch", b"payload", seen.append)
    assert seen == [b"payload"]


def test_failed_verification_leaves_original_untouched(tmp_path):
    target = tmp_path / "hero.fch"
    target.write_bytes(b"original")
    with pytest.raises(UnsafeWrite):
        safe_io.write_verified(target, b"broken", _reject)
    assert target.read_bytes() == b"original"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["hero.fch"]


def test_falsy_verifier_return_rejects(tmp_path):
    target = tmp_path / "hero.fch"
    target.write_bytes(b"original")
    with pytest.raises(UnsafeWrite):
        safe_io.write_verified(target, b"broken", lambda b: False)
    assert target.read_bytes() == b"original"


def test_make_backup_false_skips_backup(tmp_path):
    target = tmp_path / "hero.fch"
    target.write_bytes(b"original")
    assert safe_io.write_verified(target, b"edited", lambda b: None, make_backup=False) is None
    assert sorted(p.name for p in tmp_path.iterdir()) == ["hero.fch"]


def test_replace_failure_raises_unsafe_write_and_keeps_original(tmp_path, monkeypatch):
    target = tmp_path / "hero.fch"
    target.write_bytes(b"original")

    def locked(*_):
        raise PermissionError("locked by another process")

    monkeypatch.setattr(safe_io.os, "replace", locked)
    monkeypatch.setattr(safe_io.time, "sleep", lambda _: None)
    with pytest.raises(UnsafeWrite, match="backup at"):
        safe_io.write_verified(target, b"edited", lambda b: None)
    assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob("*.fch-editor-tmp"))


def test_cleanup_failure_does_not_mask_verify_error(tmp_path, monkeypatch):
    target = tmp_path / "hero.fch"

    def locked_unlink(self, missing_ok=False):
        raise PermissionError("antivirus lock")

    monkeypatch.setattr(safe_io.Path, "unlink", locked_unlink)
    monkeypatch.setattr(safe_io.time, "sleep", lambda _: None)
    with pytest.raises(UnsafeWrite, match="rejected by verifier"):
        safe_io.write_verified(target, b"broken", _reject)


def test_backups_never_clobber_each_other(tmp_path):
    target = tmp_path / "hero.fch"
    target.write_bytes(b"v1")
    first = safe_io.backup(target)
    target.write_bytes(b"v2")
    second = safe_io.backup(target)
    assert first != second
    assert first.read_bytes() == b"v1" and second.read_bytes() == b"v2"


def test_is_game_running_parses_tasklist(monkeypatch):
    def fake_run(stdout):
        return lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(safe_io.sys, "platform", "win32")
    monkeypatch.setattr(safe_io.subprocess, "run", fake_run('"valheim.exe","1234","Console","1","2,000 K"\n'))
    assert safe_io.is_game_running()
    monkeypatch.setattr(safe_io.subprocess, "run", fake_run("INFO: No tasks are running which match the specified criteria.\n"))
    assert not safe_io.is_game_running()
