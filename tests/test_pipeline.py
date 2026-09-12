"""The pure edit pipeline: scope checks and write-back verification.

No filesystem access here — see test_write.py for check_destination/write_result,
which is exactly the boundary edits/pipeline.py vs edits/write.py encodes.
"""
import copy
from dataclasses import dataclass

import pytest

from fch_editor.edits import pipeline
from fch_editor.edits.pipeline import apply_edits
from fch_editor.errors import UnsafeWrite
from fch_editor.load import load_bytes


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


def test_pipeline_module_has_no_filesystem_or_process_imports():
    """Guards the Pyodide boundary: pipeline.py must stay importable with no
    subprocess/tempfile/os/pathlib access, so it can run inside a browser
    runtime that has none of those reliably. safe_io (backups, atomic replace,
    the running-game check) belongs only to edits/write.py.

    Checks the actual AST import nodes rather than the module's post-import
    namespace, so it also catches `from ..safe_io import write_verified` (a
    specific-name import binds something other than "safe_io") and a
    reintroduced `from pathlib import Path` -- neither of which a
    namespace/vars() check would notice.
    """
    import ast
    import pathlib as _pathlib

    forbidden_modules = {"subprocess", "tempfile", "os", "pathlib"}
    forbidden_names = {"safe_io", "Path"}

    source = _pathlib.Path(pipeline.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top not in forbidden_modules, f"pipeline.py must not `import {alias.name}`"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not module.endswith("safe_io"), f"pipeline.py must not import from {module!r}"
            assert module.split(".")[0] not in forbidden_modules, f"pipeline.py must not import from {module!r}"
            for alias in node.names:
                assert alias.name not in forbidden_names, \
                    f"pipeline.py must not import {alias.name!r} from {module!r}"
