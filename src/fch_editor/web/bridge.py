"""JSON-in/JSON-out facade over the editor core for the browser front end.

The web equivalent of `cli_edits.py`/`cli_inventory.py`: argument handling and
presentation only, no editing logic of its own. Every edit spec is turned into
the existing edit dataclass from `edits/*`, whose `__post_init__` does the one
and only validation — adding a rule here instead would make this a second,
divergent rulebook (see the plan's risk assessment). The two places this
module resolves a human-friendly reference into the value an edit dataclass
actually stores (a skill name into its numeric id, an item name into its
prefab hash) mirror exactly what `cli_edits.py`/`cli_inventory.py` already do
before constructing the same dataclasses — not new validation, the same
caller-side resolution the CLI performs, done once more for this caller.

State (the loaded save + pending edits) lives in one `Session` per open file,
built directly on `edits.state.AppState` — the same class the Tkinter GUI
uses — so "add an edit, validate the whole pending list, roll back on
failure" is one implementation, not two.
"""
from ..catalog.appearance import BEARDS, GUARDIAN_POWERS, HAIRS
from ..catalog.enums import SKILL_NAMES
from ..catalog.items import ItemCatalog
from ..diffing import diff
from ..edits.character import (SetBeard, SetColor, SetGuardianCooldown, SetGuardianPower, SetHair,
                               SetModel, SetName, parse_guardian_power)
from ..edits.inventory import DEFAULT_DURABILITY, AddItem, RemoveItem, SetItemField, parse_prefab_hash
from ..edits.pipeline import preview_edits
from ..edits.skills import SetSkillLevel, parse_skill
from ..edits.state import AppState
from ..errors import EditError, FchError
from ..load import load_bytes
from ..render import _jsonable, diff_text, to_json


def _as_int(value, what: str) -> int:
    """Reject a non-integer JSON number (e.g. `5.0` from a sloppy JS numeric
    path) with a clean, human-facing error — mirroring what the CLI's own
    `int(text)` parsing (`edits/inventory.py::parse_slot`) already guarantees
    can never happen there. Coercing a fractional value here instead of
    rejecting it would risk silently targeting the wrong slot or size, which
    is worse than refusing it.

    Without this, a float here reaches the dataclass's own `__post_init__`
    unchanged: range checks like `1 <= stack <= 65535` succeed for a float
    exactly as for an int, so nothing rejects it until deep inside the binary
    encoder — as a raw `TypeError` in one case (`Writer.u8`, since it hand-
    rolls its bounds check rather than going through `struct.pack`, which is
    fixed separately) that would otherwise escape every `except EditError`/
    `except FchError` in this module and leave the pending list uncommitted
    to either its old or new state.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise EditError(f"{what} must be a whole number, got {value!r}")
    return value


def _optional_int(spec: dict, key: str, default=None):
    value = spec.get(key, default)
    return _as_int(value, key) if value is not None else None


def _slot(spec: dict) -> tuple[int, int]:
    """JSON has no tuple type; a bare list would compare unequal to the
    (x, y) tuples `edits/inventory.py` builds from item coordinates, so every
    slot crossing this boundary is converted here, once."""
    x, y = spec["slot"]
    return (_as_int(x, "slot"), _as_int(y, "slot"))


def _build_skill(spec: dict) -> SetSkillLevel:
    return SetSkillLevel(parse_skill(spec["skill"]), spec["level"], spec.get("keep_progress", False))


def _build_color(spec: dict) -> SetColor:
    return SetColor(spec["field"], tuple(spec["rgb"]))


def _build_guardian_power(spec: dict) -> SetGuardianPower:
    return SetGuardianPower(parse_guardian_power(spec["power"]))


def _build_item_field(spec: dict) -> SetItemField:
    return SetItemField(_slot(spec), stack=_optional_int(spec, "stack"), durability=spec.get("durability"))


def _build_item_remove(spec: dict) -> RemoveItem:
    return RemoveItem(_slot(spec))


def _build_item_add(spec: dict, catalog: ItemCatalog) -> AddItem:
    name = spec["name"]
    if name not in catalog and not spec.get("allow_unknown_item", False):
        raise EditError(
            f"{name!r} is not a known item prefab; check spelling, or set allow_unknown_item "
            "if it's a valid item from a newer game update (a wrong name makes the game delete it on load)")
    return AddItem(
        prefab_name=name, prefab_hash=parse_prefab_hash(name), stack=_optional_int(spec, "stack", default=1),
        slot=_slot(spec) if spec.get("slot") is not None else None,
        durability=spec.get("durability", DEFAULT_DURABILITY),
        crafted_by_me=spec.get("crafted_by_me", False),
    )


# kind -> (builder, needs_catalog). Builders taking only `spec` are plain
# dataclass constructions or a one-field translation; `item_add` additionally
# needs the catalog for its membership check, so it is called out separately
# in `Session._build_edit` rather than forcing every builder to accept an
# unused `catalog` argument.
_BUILDERS = {
    "skill": _build_skill,
    "name": lambda spec: SetName(spec["name"]),
    "beard": lambda spec: SetBeard(spec["style"], spec.get("allow_unknown", False)),
    "hair": lambda spec: SetHair(spec["style"], spec.get("allow_unknown", False)),
    "color": _build_color,
    "model": lambda spec: SetModel(spec["index"]),
    "guardian_power": _build_guardian_power,
    "guardian_cooldown": lambda spec: SetGuardianCooldown(spec["seconds"]),
    "item_field": _build_item_field,
    "item_remove": _build_item_remove,
}


class Session:
    """One open save plus its not-yet-written edits. One instance per file the
    page has open."""

    def __init__(self):
        self._state: AppState | None = None
        self._catalog = ItemCatalog.load()

    # --- reading -----------------------------------------------------

    def open(self, data: bytes) -> dict:
        """Load a save from raw bytes into this session, replacing whatever
        was open before. Never raises.

        Two distinct kinds of "can't use this" collapse to the same
        `{"ok": True, "writable": False, ...}` shape once past this method: a
        `.fch` envelope whose *profile* fails to decode (unsupported version,
        a section that doesn't round-trip) reports `writable: False` with
        `reasons` — `load_bytes` itself already handles that. Bytes that
        aren't an `.fch` envelope at all (too short, wrong structure) raise
        `FormatError` from `load_bytes` instead, since there is no envelope to
        even describe the reasons within — caught here and reported as
        `{"ok": False, "error": ...}` instead of a raw traceback, matching how
        every other rejected operation in this module reports failure.
        """
        try:
            save = load_bytes(bytes(data))
        except FchError as e:
            return {"ok": False, "error": str(e)}
        self._state = AppState(save)
        return {"ok": True, **self._describe()}

    def catalog(self) -> dict:
        """Static reference data for building pickers/autocomplete: never
        changes per session, so the page can fetch it once."""
        return {
            "skills": [{"id": sid, "name": name} for sid, name in sorted(SKILL_NAMES.items())],
            "beards": list(BEARDS),
            "hairs": list(HAIRS),
            "guardian_powers": [{"id": pid, "name": name} for pid, name in GUARDIAN_POWERS.items()],
            "items": self._catalog.names(),
        }

    def _describe(self) -> dict:
        return to_json(self._state.save, self._catalog)

    def list_pending(self) -> list[dict]:
        """One entry per `add_edit()` call still pending, in the order
        `remove_edit(index)` uses — the units a pending-changes panel lists,
        as opposed to `preview()['changes']`, which is flattened per *field*
        (one skill edit can touch more than one field).

        Each entry's `changes`/`diff_text` describe exactly what that one
        edit changes, computed by diffing the save-with-edits-so-far against
        save-with-edits-so-far-plus-this-one. This needs no new per-edit-kind
        description logic — it reuses the same `preview_edits`/`diff` the
        rest of the pipeline already uses, so a pending-panel label can never
        drift from what `preview()`'s own diff would show for the same edit.
        """
        if self._state is None:
            return []
        entries = []
        prior: list = []
        for edit in self._state.pending:
            before = preview_edits(self._state.save, prior).profile
            after = preview_edits(self._state.save, prior + [edit]).profile
            changes = diff(before, after)
            entries.append({"changes": _changes_json(changes), "diff_text": diff_text(changes)})
            prior.append(edit)
        return entries

    def preview(self) -> dict:
        """Everything pending, applied but not written: the JSON view a page
        renders into its tabs, plus the diff for a confirmation dialog."""
        result = self._state.preview()
        return {
            "changes": _changes_json(result.changes),
            "diff_text": diff_text(result.changes),
            "save": to_json(_ResultAsSave(result, self._state.save), self._catalog),
        }

    def result_bytes(self) -> bytes:
        """The bytes a download would write right now. Raises `FchError` if
        there is nothing pending or an edit's combination is unsafe — the page
        is expected to have already surfaced that via `preview()`/`add_edit()`
        before offering a download button."""
        return self._state.preview().data

    # --- editing -------------------------------------------------------

    def add_edit(self, spec: dict) -> dict:
        """Build one edit from `spec` and add it to the pending list.

        Mirrors the Tkinter GUI's `App.apply_edits_batch`: add, then validate
        the whole pending list by previewing it; on failure, restore the
        pending list to what it was before this call and report the error
        instead of leaving a half-applied edit in place.
        """
        if self._state is None:
            return {"ok": False, "error": "no save is open"}
        try:
            edit = self._build_edit(spec)
        except (EditError, KeyError, TypeError, ValueError) as e:
            return {"ok": False, "error": str(e)}
        before = list(self._state.pending)
        self._state.add(edit)
        try:
            result = self._state.preview()
        except FchError as e:  # covers EditError and UnsafeWrite raised only once edits combine
            self._state.set_pending(before)
            return {"ok": False, "error": str(e)}
        return {"ok": True, "changes": _changes_json(result.changes)}

    def _build_edit(self, spec: dict):
        kind = spec.get("kind")
        if kind == "item_add":
            return _build_item_add(spec, self._catalog)
        builder = _BUILDERS.get(kind)
        if builder is None:
            raise EditError(f"unknown edit kind {kind!r}")
        return builder(spec)

    def remove_edit(self, index: int) -> dict:
        """Drop one pending edit by the order it was added in (0 = the first
        `add_edit` call still pending) — one entry per action a person took,
        not one per field `preview()['changes']` lists (a single skill edit
        can touch more than one field). Always safe without re-validation:
        each edit's scope and validity were established independently of the
        others, so removing one can only shrink what the remaining edits do.
        """
        if self._state is None:
            return {"ok": False, "error": "no save is open"}
        pending = list(self._state.pending)
        if not 0 <= index < len(pending):
            return {"ok": False, "error": f"no pending edit at index {index}"}
        del pending[index]
        self._state.set_pending(pending)
        return {"ok": True}

    def discard(self) -> dict:
        if self._state is not None:
            self._state.discard()
        return {"ok": True}


def _changes_json(changes: list[tuple[str, object, object]]) -> list[dict]:
    """The (path, old, new) triples `diff()` produces, each value rendered the
    same way `render.to_json` renders a save's own fields."""
    return [{"path": p, "old": _jsonable(o), "new": _jsonable(n)} for p, o, n in changes]


class _ResultAsSave:
    """Adapts an in-memory `EditResult` to the subset of `LoadedSave` that
    `render.to_json` reads (`profile`, `writable`, `hash_ok`, `reasons`,
    `warnings`), so `preview()` can reuse that exact renderer instead of a
    second, preview-specific JSON builder. `writable`/`hash_ok`/`reasons`/
    `warnings` describe the *original* save being edited, not a claim about
    the not-yet-written preview bytes — a preview has no read-only status of
    its own to report.
    """

    def __init__(self, result, original_save):
        self.profile = result.profile
        self.writable = original_save.writable
        self.hash_ok = original_save.hash_ok
        self.reasons = original_save.reasons
        self.warnings = original_save.warnings
