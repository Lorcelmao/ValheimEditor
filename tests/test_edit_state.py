"""AppState: the pending-edits/preview logic behind every GUI tab.

No screen automation here (see test_gui_smoke.py for that); this is the part
of the GUI worth unit-testing on its own, same as edits/pipeline.py's tests.
"""
import pytest

from fch_editor.edits.character import SetColor, SetGuardianPower, SetHair, SetName
from fch_editor.edits.inventory import AddItem, RemoveItem, SetItemField
from fch_editor.edits.skills import SetSkillLevel
from fch_editor.edits.state import AppState
from fch_editor.errors import EditError, UnsafeWrite
from fch_editor.load import load_bytes
from fch_editor.stable_hash import stable_hash

WOOD = stable_hash("Wood")


@pytest.fixture
def state(sample_bytes):
    return AppState(load_bytes(sample_bytes))


def test_fresh_state_previews_as_the_original(state):
    result = state.preview()
    assert not state.dirty and result.changes == [] and result.data == state.save.original


def test_add_marks_dirty_and_previews_the_change(state):
    state.add(SetSkillLevel(102, 50.0))
    assert state.dirty
    result = state.preview()
    assert [p for p, _, _ in result.changes] == ["player.skills[Run].level"]


def test_preview_is_cached_until_the_next_add(state):
    state.add(SetSkillLevel(102, 50.0))
    first = state.preview()
    assert state.preview() is first
    state.add(SetSkillLevel(102, 60.0))
    assert state.preview() is not first


@pytest.mark.parametrize("first,second,expect_pending", [
    (SetSkillLevel(102, 50.0), SetSkillLevel(102, 60.0), 1),  # same skill: replaces
    (SetSkillLevel(102, 50.0), SetSkillLevel(13, 25.0), 2),   # different skill: both kept
    (SetName("Aaa"), SetName("Bbb"), 1),                      # same field: replaces
    (SetColor("skin_color", (0.1, 0.1, 0.1)), SetColor("hair_color", (0.2, 0.2, 0.2)), 2),  # different field
])
def test_replace_by_identity(state, first, second, expect_pending):
    state.add(first)
    state.add(second)
    assert len(state.pending) == expect_pending


def test_second_edit_of_the_same_skill_wins(state):
    state.add(SetSkillLevel(102, 50.0))
    state.add(SetSkillLevel(102, 60.0))
    assert state.preview().profile.player.skills[[s.type for s in state.preview().profile.player.skills].index(102)].level == 60.0


def test_set_item_field_and_remove_item_key_by_slot(state):
    state.add(SetItemField((4, 2), stack=20))
    state.add(SetItemField((4, 2), stack=30))
    assert len(state.pending) == 1
    state.add(RemoveItem((4, 2)))  # different edit type, same slot: independent identity, both kept
    assert len(state.pending) == 2


def test_add_item_is_never_deduplicated(state):
    state.add(AddItem("Wood", WOOD, slot=(7, 0)))
    state.add(AddItem("Wood", WOOD, slot=(7, 1)))
    assert len(state.pending) == 2
    assert len(state.preview().profile.player.items) == len(state.save.profile.player.items) + 2


def test_discard_clears_pending_and_cache(state):
    state.add(SetSkillLevel(102, 50.0))
    state.discard()
    assert not state.dirty and state.preview().changes == []


def test_set_pending_restores_a_rolled_back_batch(state):
    before = list(state.pending)
    state.add(SetSkillLevel(102, 50.0))
    state.set_pending(before)
    assert not state.dirty


def test_invalid_edit_raises_before_being_added(state):
    # Edits validate in their own __post_init__, so a bad one never reaches pending.
    with pytest.raises(EditError):
        SetSkillLevel(102, -5.0)
    assert not state.dirty


def test_preview_raises_if_the_pipeline_itself_refuses(state):
    class BadEdit:
        def apply(self, profile):
            profile.name = "X"
            return ["player.skills"]  # lies about scope: name isn't under player.skills

    state.pending.append(BadEdit())
    with pytest.raises(UnsafeWrite):
        state.preview()


def test_rebased_on_starts_a_clean_state(state):
    state.add(SetSkillLevel(102, 50.0))
    new_save = load_bytes(state.preview().data)
    fresh = state.rebased_on(new_save)
    assert not fresh.dirty and fresh.save is new_save
    assert fresh.preview().profile.player.skills[
        [s.type for s in fresh.preview().profile.player.skills].index(102)].level == 50.0


def test_guardian_power_replace_by_field(state):
    state.add(SetGuardianPower("GP_Eikthyr"))
    state.add(SetGuardianPower(""))
    assert len(state.pending) == 1
    assert state.preview().profile.player.guardian_power == ""


def test_hair_and_name_are_independent(state):
    state.add(SetName("Renamed"))
    state.add(SetHair("Hair5"))
    assert len(state.pending) == 2
    p = state.preview().profile
    assert (p.name, p.player.hair) == ("Renamed", "Hair5")
