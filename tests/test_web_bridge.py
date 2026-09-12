"""The web bridge's JSON-in/JSON-out surface, driven with plain pytest (no
browser, no Pyodide) — see plans/260912-0936-fch-web-editor-pyodide/phase-01
for why the browser layer itself is verified separately, under Node.

The core assertion running through this file: whatever `Session` produces via
JSON specs must be byte-identical to what the equivalent `edits/*` dataclass
produces directly (which is exactly what the CLI already wraps) — the bridge
must never become a second, divergent way to make the same edit.
"""
import pytest

from fch_editor.edits.character import SetBeard, SetColor, SetGuardianPower, SetName
from fch_editor.edits.inventory import AddItem, RemoveItem, SetItemField, parse_prefab_hash
from fch_editor.edits.pipeline import apply_edits
from fch_editor.edits.skills import ALL, SetSkillLevel
from fch_editor.load import load_bytes
from fch_editor.model import EQUIPPED
from fch_editor.render import diff_text
from fch_editor.web.bridge import Session

RUN = 102


@pytest.fixture
def session(sample_bytes):
    s = Session()
    opened = s.open(sample_bytes)
    assert opened["ok"] and opened["writable"]
    return s


@pytest.fixture
def save(sample_bytes):
    return load_bytes(sample_bytes)


# --- open() ------------------------------------------------------------

def test_open_reports_the_same_shape_as_render_to_json(sample_bytes):
    result = Session().open(sample_bytes)
    assert result["ok"] is True
    assert result["writable"] is True
    assert "profile" in result and result["profile"]["name"]


def test_item_json_includes_computed_properties_not_just_raw_fields(session):
    """`durability` and `equipped` are @property on the Item dataclass (see
    model.py), not dataclasses.fields() members, so a naive dataclass-to-JSON
    walk silently drops them -- a web page reading item.durability would get
    undefined instead of a number. render.to_json() adds both explicitly
    alongside the existing item["name"] enrichment; this pins that down."""
    items = session.preview()["save"]["profile"]["player"]["items"]
    assert items, "sample save has no items to check"
    for item in items:
        assert item["durability"] == pytest.approx(item["durability_x100"] * 0.01)
        assert item["equipped"] == bool(item["flags"] & EQUIPPED)
    assert any(item["equipped"] for item in items), \
        "sample save has no equipped item -- this test can't tell True from a bug that always returns False"


@pytest.mark.parametrize("data", [b"", b"tiny", b"not an fch file, still not a valid envelope"])
def test_open_on_unparseable_bytes_returns_a_structured_error_not_an_exception(data):
    result = Session().open(data)
    assert result["ok"] is False
    assert isinstance(result["error"], str) and result["error"]


def test_reopening_replaces_the_previous_save_and_clears_pending(session, sample_bytes):
    session.add_edit({"kind": "skill", "skill": "Run", "level": 50.0})
    assert session.preview()["changes"]
    session.open(sample_bytes)
    assert session.preview()["changes"] == []


# --- add_edit(): byte parity with the direct dataclass path -------------

def test_skill_edit_matches_the_equivalent_dataclass_edit(session, save):
    added = session.add_edit({"kind": "skill", "skill": "Run", "level": 50.0})
    assert added["ok"] is True
    expected = apply_edits(save, [SetSkillLevel(RUN, 50.0)])
    assert session.result_bytes() == expected.data


def test_skill_all_and_keep_progress_are_reachable(session, save):
    session.add_edit({"kind": "skill", "skill": "all", "level": 10.0, "keep_progress": True})
    expected = apply_edits(save, [SetSkillLevel(ALL, 10.0, keep_progress=True)])
    assert session.result_bytes() == expected.data


def test_character_edits_match_the_equivalent_dataclass_edits(session, save):
    for spec in ({"kind": "name", "name": "Hero"},
                 {"kind": "beard", "style": "Beard5"},
                 {"kind": "color", "field": "skin_color", "rgb": [0.1, 0.2, 0.3]},
                 {"kind": "guardian_power", "power": "Eikthyr"}):
        assert session.add_edit(spec)["ok"] is True
    expected = apply_edits(save, [
        SetName("Hero"), SetBeard("Beard5"), SetColor("skin_color", (0.1, 0.2, 0.3)),
        SetGuardianPower("GP_Eikthyr"),
    ])
    assert session.result_bytes() == expected.data


def test_guardian_power_none_clears_it(session, save):
    session.add_edit({"kind": "guardian_power", "power": "none"})
    expected = apply_edits(save, [SetGuardianPower("")])
    assert session.result_bytes() == expected.data


def test_item_field_and_remove_match_the_equivalent_dataclass_edits(session, save):
    # Pick a real occupied slot from the sample rather than assuming one.
    slot = save.profile.player.items[0]
    x, y = slot.x, slot.y
    r1 = Session()
    r1.open(save.original)
    assert r1.add_edit({"kind": "item_field", "slot": [x, y], "stack": 5})["ok"] is True
    expected = apply_edits(save, [SetItemField((x, y), stack=5)])
    assert r1.result_bytes() == expected.data

    r2 = Session()
    r2.open(save.original)
    assert r2.add_edit({"kind": "item_remove", "slot": [x, y]})["ok"] is True
    expected2 = apply_edits(save, [RemoveItem((x, y))])
    assert r2.result_bytes() == expected2.data


def test_two_partial_item_field_edits_for_the_same_slot_replace_not_merge(session):
    """Documents a real contract, not a bug: `edit_key` (edits/dedup.py) keys
    a pending SetItemField by slot alone, and AppState.add() fully replaces
    the earlier same-key edit rather than merging fields into it -- so a
    *second*, partial `item_field` edit for a slot already pending silently
    drops whatever the first one set and didn't repeat.

    This bit web/app.js for real (found by code review, phase 4): its stack
    and durability inputs each committed independently, so editing both
    fields of one row lost whichever was edited first. The fix belongs in
    the caller (send one edit with every field you want to keep, exactly as
    the Tkinter GUI's "Apply" already does, and as app.js now does too), not
    here -- this test exists so a future change doesn't "fix" this replace
    behavior in bridge.py/edits/dedup.py itself and break the dedup contract
    every other edit kind also relies on.
    """
    item = session._state.save.profile.player.items[0]
    x, y = item.x, item.y
    original_durability = item.durability

    session.add_edit({"kind": "item_field", "slot": [x, y], "stack": 99})
    session.add_edit({"kind": "item_field", "slot": [x, y], "durability": 77.0})

    assert len(session._state.pending) == 1  # the second replaced the first, not merged
    after = session.preview()["save"]["profile"]["player"]["items"][0]
    assert after["durability"] == 77.0  # the second edit's own field
    assert after["stack"] == 1  # the first edit's stack=99 was lost, not preserved -- this is the trap

    # The fix: send every field you want kept in ONE call.
    session.discard()
    session.add_edit({"kind": "item_field", "slot": [x, y], "stack": 99, "durability": 77.0})
    combined = session.preview()["save"]["profile"]["player"]["items"][0]
    assert (combined["stack"], combined["durability"]) == (99, 77.0)
    assert original_durability != 77.0  # sanity: this really did change something


def test_item_add_resolves_the_same_hash_the_cli_would(session, save):
    # No explicit slot: both sides fall back to the first free slot in the
    # grid, exactly like the CLI's `inv add` with no `--slot`.
    added = session.add_edit({"kind": "item_add", "name": "Wood", "stack": 10})
    assert added["ok"] is True
    expected = apply_edits(save, [AddItem("Wood", parse_prefab_hash("Wood"), stack=10)])
    assert session.result_bytes() == expected.data


def test_item_add_rejects_an_unknown_name_unless_allowed(session):
    result = session.add_edit({"kind": "item_add", "name": "TotallyMadeUpPrefab"})
    assert result["ok"] is False and "not a known item prefab" in result["error"]
    assert session.preview()["changes"] == []  # rejected spec never touched pending

    allowed = session.add_edit({"kind": "item_add", "name": "TotallyMadeUpPrefab",
                                "allow_unknown_item": True})
    assert allowed["ok"] is True


# --- error handling and dedup -------------------------------------------

def test_unknown_kind_is_a_structured_error_and_pending_is_untouched(session):
    result = session.add_edit({"kind": "not_a_real_kind"})
    assert result == {"ok": False, "error": "unknown edit kind 'not_a_real_kind'"}
    assert session.preview()["changes"] == []


def test_missing_required_field_is_a_structured_error(session):
    result = session.add_edit({"kind": "skill", "skill": "Run"})  # no "level"
    assert result["ok"] is False and "level" in result["error"]


def test_invalid_value_is_a_structured_error(session):
    result = session.add_edit({"kind": "skill", "skill": "Run", "level": -5.0})
    assert result["ok"] is False
    assert session.preview()["changes"] == []


@pytest.mark.parametrize("spec", [
    {"kind": "item_add", "name": "Wood", "slot": [7.0, 0.0]},          # float slot coordinate
    {"kind": "item_field", "slot": [0, 0], "stack": 5.0},              # float stack
    {"kind": "item_field", "slot": [0.0, 0], "stack": 5},              # float in one slot component
    {"kind": "item_remove", "slot": [True, 0]},                        # bool is an int subclass -- must not sneak through
])
def test_non_integer_slot_or_stack_is_a_clean_error_not_a_crash(session, spec):
    """Regression test: a JSON float where a slot/stack expects a whole number
    used to reach fch_editor.writer.Writer.u8() unguarded, raising a raw
    TypeError instead of returning {"ok": False, ...} -- and because that
    exception wasn't an EditError/FchError, add_edit's rollback never ran,
    leaving the bad edit stuck in the pending list and every later preview()
    call raising the same TypeError forever. Both symptoms are checked here.
    """
    before = list(session._state.pending)
    result = session.add_edit(spec)
    assert result["ok"] is False
    assert "whole number" in result["error"]
    assert session._state.pending == before  # nothing was left half-added
    session.preview()  # must not raise -- the session must not be left wedged


def test_valid_edit_after_a_rejected_float_slot_still_works(session, save):
    session.add_edit({"kind": "item_add", "name": "Wood", "slot": [7.0, 0.0]})  # rejected
    added = session.add_edit({"kind": "item_add", "name": "Wood", "stack": 10})  # valid, no explicit slot
    assert added["ok"] is True
    expected = apply_edits(save, [AddItem("Wood", parse_prefab_hash("Wood"), stack=10)])
    assert session.result_bytes() == expected.data


def test_repeated_edit_to_the_same_skill_replaces_not_accumulates(session):
    session.add_edit({"kind": "skill", "skill": "Run", "level": 50.0})
    session.add_edit({"kind": "skill", "skill": "Run", "level": 60.0})
    assert len(session._state.pending) == 1
    profile = session.preview()["save"]["profile"]
    run = next(s for s in profile["player"]["skills"] if s["name"] == "Run")
    assert run["level"] == 60.0


def test_no_save_open_is_a_structured_error_not_a_crash():
    fresh = Session()
    assert fresh.add_edit({"kind": "skill", "skill": "Run", "level": 50.0}) == \
        {"ok": False, "error": "no save is open"}
    assert fresh.remove_edit(0) == {"ok": False, "error": "no save is open"}


# --- remove_edit / discard ------------------------------------------------

def test_remove_edit_by_add_order_index(session):
    session.add_edit({"kind": "skill", "skill": "Run", "level": 50.0})
    session.add_edit({"kind": "name", "name": "Renamed"})
    assert session.remove_edit(0) == {"ok": True}
    assert len(session._state.pending) == 1
    profile = session.preview()["save"]["profile"]
    assert profile["name"] == "Renamed"
    run = next(s for s in profile["player"]["skills"] if s["name"] == "Run")
    assert run["level"] != 50.0


def test_remove_edit_out_of_range_is_a_structured_error(session):
    result = session.remove_edit(99)
    assert result["ok"] is False and "no pending edit" in result["error"]


def test_discard_clears_everything(session):
    session.add_edit({"kind": "skill", "skill": "Run", "level": 50.0})
    assert session.discard() == {"ok": True}
    assert session.preview()["changes"] == []


# --- preview() / result_bytes() -------------------------------------------

def test_preview_before_any_edit_matches_the_original(session, sample_bytes):
    preview = session.preview()
    assert preview["changes"] == [] and preview["diff_text"] == "no differences"
    assert session.result_bytes() == sample_bytes


def test_preview_diff_text_is_exactly_render_diff_text_of_the_same_changes(session, save):
    session.add_edit({"kind": "skill", "skill": "Run", "level": 50.0})
    expected = apply_edits(save, [SetSkillLevel(RUN, 50.0)])
    assert session.preview()["diff_text"] == diff_text(expected.changes)


# --- list_pending() ----------------------------------------------------

def test_list_pending_is_one_entry_per_edit_not_per_field(session, save):
    session.add_edit({"kind": "skill", "skill": "all", "level": 100.0})  # touches many fields
    session.add_edit({"kind": "name", "name": "TestHero"})
    pending = session.list_pending()
    assert len(pending) == 2  # one per add_edit call, unlike preview()['changes']
    assert len(pending[0]["changes"]) > 1  # the "all" edit really does touch several fields
    assert pending[1]["changes"] == [{"path": "name", "old": save.profile.name, "new": "TestHero"}]


def test_list_pending_entry_matches_render_diff_text_for_that_edit_alone(session, save):
    session.add_edit({"kind": "skill", "skill": "Run", "level": 50.0})
    session.add_edit({"kind": "name", "name": "TestHero"})
    pending = session.list_pending()
    # Each entry is what THAT edit alone changes, not cumulative with the others.
    assert pending[0]["diff_text"] == diff_text(apply_edits(save, [SetSkillLevel(RUN, 50.0)]).changes)
    assert pending[1]["diff_text"] == "name: 'Lorce' -> 'TestHero'"


def test_list_pending_shrinks_after_remove_edit(session):
    session.add_edit({"kind": "skill", "skill": "Run", "level": 50.0})
    session.add_edit({"kind": "name", "name": "TestHero"})
    session.remove_edit(0)
    pending = session.list_pending()
    assert len(pending) == 1
    assert pending[0]["diff_text"] == "name: 'Lorce' -> 'TestHero'"


def test_list_pending_empty_before_any_edit(session):
    assert session.list_pending() == []


def test_list_pending_without_an_open_save_is_empty_not_a_crash():
    assert Session().list_pending() == []


# --- catalog() -------------------------------------------------------------

def test_catalog_exposes_every_reference_list():
    cat = Session().catalog()
    assert {"skills", "beards", "hairs", "guardian_powers", "items"} <= cat.keys()
    assert {"id": 102, "name": "Run"} in cat["skills"]
    assert "Beard5" in cat["beards"] and "Hair5" in cat["hairs"]
    assert {"id": "GP_Eikthyr", "name": "Eikthyr"} in cat["guardian_powers"]
    assert "Wood" in cat["items"]
