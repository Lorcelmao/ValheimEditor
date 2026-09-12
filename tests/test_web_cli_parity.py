"""The web bridge, driven end-to-end through a realistic multi-area edit
session, must produce bytes identical to the same edits applied via the real
CLI. This is the acceptance test for the whole web-editor plan (see
plans/260912-0936-fch-web-editor-pyodide/phase-04-editing-ui.md) -- it is what
prevents the web app from quietly becoming a second implementation.

Distinct from tests/test_web_bridge.py's per-kind checks (which compare a
single edit kind against the same edit dataclass applied directly via
apply_edits): this drives the *real* `fch` CLI as separate invocations
(skills/char/inv are three different subcommands, each its own write), while
the browser session batches every edit into one `result_bytes()` call against
the original file. Proving those two produce identical bytes is a real,
distinct correctness property -- that batching multiple edits together is
equivalent to the CLI's sequential-save style -- not a restatement of the
per-kind coverage that already exists.
"""
from fch_editor.cli import main
from fch_editor.load import load_bytes
from fch_editor.web.bridge import Session


def test_web_session_matches_a_chain_of_cli_commands(sample_bytes, tmp_path):
    source = tmp_path / "hero.fch"
    source.write_bytes(sample_bytes)

    # The real CLI, invoked exactly as a user would: one command per edit
    # area, each command writing a new file the next one reads.
    step1 = tmp_path / "step1.fch"
    assert main(["skills", "set", str(source), "Run=50", "WoodCutting=25", "--out", str(step1)]) == 0
    step2 = tmp_path / "step2.fch"
    assert main(["char", "set", str(step1), "--name", "TestHero", "--beard", "Beard5",
                 "--out", str(step2)]) == 0
    step3 = tmp_path / "step3.fch"
    assert main(["inv", "add", str(step2), "Wood", "--stack", "10", "--out", str(step3)]) == 0
    expected = step3.read_bytes()

    # The same five edits, batched into one browser session against the
    # original file, written once via result_bytes().
    session = Session()
    opened = session.open(sample_bytes)
    assert opened["ok"] and opened["writable"]
    for spec in (
        {"kind": "skill", "skill": "Run", "level": 50.0},
        {"kind": "skill", "skill": "WoodCutting", "level": 25.0},
        {"kind": "name", "name": "TestHero"},
        {"kind": "beard", "style": "Beard5"},
        {"kind": "item_add", "name": "Wood", "stack": 10},
    ):
        result = session.add_edit(spec)
        assert result["ok"], result.get("error")

    assert session.result_bytes() == expected


def test_web_session_matches_cli_for_inventory_field_edits_and_removal(sample_bytes, tmp_path):
    source = tmp_path / "hero.fch"
    source.write_bytes(sample_bytes)

    # Pick real occupied slots rather than assuming any.
    save = load_bytes(sample_bytes)
    item = save.profile.player.items[0]
    slot_arg = f"{item.x},{item.y}"

    step1 = tmp_path / "step1.fch"
    assert main(["inv", "set", str(source), "--slot", slot_arg, "--stack", "7", "--durability", "42",
                 "--out", str(step1)]) == 0
    other = save.profile.player.items[1]
    step2 = tmp_path / "step2.fch"
    assert main(["inv", "remove", str(step1), "--slot", f"{other.x},{other.y}", "--out", str(step2)]) == 0
    expected = step2.read_bytes()

    session = Session()
    session.open(sample_bytes)
    r1 = session.add_edit({"kind": "item_field", "slot": [item.x, item.y], "stack": 7, "durability": 42.0})
    assert r1["ok"], r1.get("error")
    r2 = session.add_edit({"kind": "item_remove", "slot": [other.x, other.y]})
    assert r2["ok"], r2.get("error")

    assert session.result_bytes() == expected
