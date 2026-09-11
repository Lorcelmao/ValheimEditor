# Valheim FCH Save Editor

A small, practical editor for Valheim `.fch` character saves (game 1.0.7, save formats profile v46 /
player v33 / inventory v109 / skills v2). Read, inspect, and edit skills, character appearance, and
inventory — from the command line or a Tkinter GUI.

Built by reverse-engineering the current save format from a sample save plus the installed game's own
code (see `docs/fch-format-spec.md`). No game code is redistributed here.

## Why

Existing Valheim save editors predate the 1.0 format changes (compact hashed item records, restructured
stats, new fields) and no longer parse current saves correctly. This one is built from the current format
and re-verified against it: every write is checked before it touches disk.

## Safety model

- **Lossless round trip**: decoding then re-encoding a save reproduces it byte-for-byte. A save is only
  ever opened for editing if this holds; otherwise it's read-only, with the reason shown.
- **Scoped edits**: every edit declares which fields it may change. Before any write, the tool re-decodes
  the result and refuses if anything outside that scope changed.
- **Backups**: an in-place write always keeps a timestamped backup next to the file
  (`<name>.fch.bak-YYYYMMDD-HHMMSS`) before replacing it.
- **Never mid-game**: writes are refused while Valheim is running (it rewrites saves on exit and would
  undo the edit), unless explicitly forced.

None of this has been validated by loading an edited save in-game yet — see
[Open items](#open-items) below.

## Install

Requires Python 3.11+ (developed on 3.13). No runtime dependencies.

```powershell
git clone https://github.com/Lorcelmao/ValheimEditor.git
cd ValheimEditor
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
```

## Usage

```powershell
.venv\Scripts\fch info Save\lorce.fch                              # summary
.venv\Scripts\fch verify Save\lorce.fch                             # safe to edit?
.venv\Scripts\fch skills set Save\lorce.fch Run=50 --out edited.fch # write to a new file
.venv\Scripts\fch gui                                               # graphical editor
```

Or double-click a packaged build — see [Building the GUI executable](#building-the-gui-executable).

Full command reference, every flag, and a step-by-step in-game test walkthrough:
**[`docs/usage-guide.md`](docs/usage-guide.md)**.

## What it can do

| Area | Command | Notes |
|------|---------|-------|
| Inspect | `fch info`, `fch dump`, `fch verify`, `fch diff` | Read-only; never write |
| Skills | `fch skills list`, `fch skills set` | Any level ≥ 0, no upper cap |
| Character | `fch char show`, `fch char set` | Name, beard, hair, colors, model, guardian power |
| Inventory | `fch inv list/set/remove/add` | Stack, durability, remove, add by prefab name |
| GUI | `fch gui` | Same edits, same safety checks, a window instead of a terminal |

Not yet supported (by design — see the project plan): map/pin editing, stat-block editing, food and
custom-data editing, item quality/variant.

## Building the GUI executable

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
.\tools\build_gui.ps1
```

Produces `dist\fch-editor.exe` (~11 MB), which runs without Python installed.

## Project layout

```
src/fch_editor/
  reader.py, writer.py, container.py    # binary primitives + outer envelope (length, SHA-512)
  model.py, versions.py                 # typed save structure, supported-version gate
  codec/                                # decode/encode per section (profile, player, inventory, skills, map)
  edits/                                # typed edit operations + the shared verified-write pipeline
  catalog/                              # item/skill/appearance name lookups
  cli.py, cli_edits.py, cli_inventory.py  # command-line interface
  gui/                                  # Tkinter desktop editor
docs/            fch-format-spec.md (the format, reverse-engineered), usage-guide.md, validation-log.md
plans/           development plan and phase history
tools/           format-drift checker, GUI packaging scripts
REFERENCES/      an older, incompatible open-source editor kept only as historical reference
```

## Development

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q
```

250+ tests, no external services or fixtures beyond an optional local save dropped in `tests/fixtures/`
(sample-dependent tests skip cleanly without one). See `docs/fch-format-spec.md` for the format itself and
`plans/260911-1018-valheim-fch-save-editor/` for how it was built, phase by phase, including what each
code review found and fixed.

## Open items

- **In-game validation is pending** for character and inventory edits, and for this GUI — see
  `docs/validation-log.md` for what has been confirmed so far (skills editing: confirmed working in-game).
  Always test on a copy, never your only save.
- Game updates can change the save format; `tools/spec_fingerprint.py` detects drift against the
  installed game so the spec can be re-verified.

## License

Personal project, no license file yet — treat as all-rights-reserved until one is added.
