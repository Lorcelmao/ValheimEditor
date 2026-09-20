# fch editor: usage and in-game test guide

Commands run from the project folder in **PowerShell** (or cmd):

```powershell
cd D:\ValheimEditor
```

Every command below starts with `.venv\Scripts\python.exe -m fch_editor.cli`. To shorten it in a PowerShell
session, define a helper once:

```powershell
function fch { & D:\ValheimEditor\.venv\Scripts\python.exe -m fch_editor.cli @args }
```

The examples use `fch` from here on. The full form works everywhere.

## Golden rules

1. **Close Valheim before editing.** The game rewrites your save when it exits and would overwrite your edit.
   The editor refuses to write while `valheim.exe` is running.
2. **Edit copies, not your only save.** Use `--out` to write a new file. `--in-place` also keeps a
   timestamped backup (`<name>.fch.bak-YYYYMMDD-HHMMSS`).
3. Your saves live in:
   `%USERPROFILE%\AppData\LocalLow\IronGate\Valheim\characters_local`

## Inspect a save (read-only; these never change anything)

```powershell
fch info   Save\lorce.fch                      # character, worlds, vitals, skills, inventory
fch verify Save\lorce.fch                      # "OK: safe to edit" or why it is read-only
fch skills list Save\lorce.fch                 # every skill with level and progress
fch dump   Save\lorce.fch --section skills     # JSON (sections: stats, worlds, player, inventory, skills)
fch diff   Save\a.fch Save\b.fch               # field-by-field differences between two saves
```

`verify` exits with code 1 when a save cannot be edited safely. The usual cause is a save from an older game
version: the January 2025 `.fch.old` and backup files in your folder use an older format, so they open
read-only.

## Edit skills

```powershell
# preview only, nothing written
fch skills set Save\lorce.fch Run=50 WoodCutting=25 --dry-run

# write the result to a new file (the original is untouched)
fch skills set Save\lorce.fch Run=50 WoodCutting=25 --out Save\lorce_edited.fch

# every skill at once
fch skills set Save\lorce.fch all=100 --out Save\lorce_all100.fch

# overwrite the file itself (a backup is made next to it)
fch skills set Save\lorce.fch Run=50 --in-place
```

- **Skill names** (case-insensitive): Swords, Knives, Clubs, Polearms, Spears, Blocking, Axes, Bows,
  ElementalMagic, BloodMagic, Unarmed, Pickaxes, WoodCutting, Crossbows, Jump, Sneak, Run, Swim, Fishing,
  Cooking, Farming, Crafting, Dodge, Ride, or `all`.
- **Level:** any number ≥ 0. There is no upper limit. The game shows levels above 100, but progress and
  gameplay effect stop at 100.
- **Progress:** progress toward the next level resets to 0. Add `--keep-progress` to keep it.
- **Unused skills:** a skill the character has never used is added.
- **Existing `--out` file:** writing onto an existing file needs `--force`, and a backup is kept.

## Edit name and appearance

```powershell
fch char show Save\lorce.fch

fch char set Save\lorce.fch --name LorceTest --hair Hair5 --guardian-power Eikthyr --out Save\lorcetest.fch
fch char set Save\lorce.fch --skin 0.9,0.7,0.6 --hair-color 0.1,0.05,0.03 --model 1 --dry-run
```

| Option | Values |
|--------|--------|
| `--name` | 3–64 characters. Only the name shown in game changes, not the file name, so choose the file name with `--out` |
| `--beard` / `--hair` | Style names such as `BeardNone`, `Beard5`, `HairNone`, `Hair24` (case-insensitive). Add `--allow-unknown-style` for styles from newer game versions |
| `--skin` / `--hair-color` | `R,G,B` numbers ≥ 0; your current values are shown by `char show` |
| `--model` | `0` or `1` (body type) |
| `--guardian-power` | `Eikthyr`, `TheElder`, `Bonemass`, `Moder`, `Yagluth`, `Queen`, `Fader` (Ashlands), `DeepNorth`, or `none` |
| `--gp-cooldown` | Seconds until the power can be used again (`0` = ready) |

Health and stamina are not editable: the game recalculates them when the character loads.

An edited copy keeps the original character's player ID. Playing both the original and the copy in the same
world can make the game treat them as one player (e.g. for ownership of beds and wards). Use a throwaway
world for tests, or keep only one of the two in your saves folder.

Before writing, the editor prints exactly which fields change. It refuses to write if anything outside the
requested fields would change, or if the new file doesn't read back exactly as intended.

## In-game load test (skills)

A ready-made test copy exists: `Save\lorce_skilltest.fch`. It has Run 50, WoodCutting 25, and Swim 10 (newly
added); everything else is identical to your character. To make it again:

```powershell
fch skills set Save\lorce.fch Run=50 WoodCutting=25 Swim=10 --out Save\lorce_skilltest.fch --force
```

### Steps

1. **Close Valheim.**
2. **Put the test copy next to your real character:**
   ```powershell
   $saves = "$env:USERPROFILE\AppData\LocalLow\IronGate\Valheim\characters_local"
   Copy-Item Save\lorce_skilltest.fch "$saves\lorce_skilltest.fch"
   ```
   It shows up as a **second character named "Lorce"**. Your real `lorce.fch` is not touched. Renaming
   characters comes in a later phase.
3. **Start Valheim** and pick the test character. You can tell the two apart by their skills: the test copy
   has Run 50.
4. **Check the Skills panel** (inventory → Skills tab):
   - Run **50**, Woodcutting **25**, Swim **10**
   - Everything else as before (e.g. Crafting 1000, Sneak 700)
5. **Enter a world.** A throwaway world is best, because the copy shares your character's player ID. Walk
   around for a minute, then **Menu → Logout** or **Save & Quit** so the game saves the character.
6. **Close Valheim** and bring the re-saved file back:
   ```powershell
   Copy-Item "$saves\lorce_skilltest.fch" Save\lorce_skilltest_resaved.fch
   fch verify Save\lorce_skilltest_resaved.fch
   fch diff   Save\lorce_skilltest.fch Save\lorce_skilltest_resaved.fch
   ```

### What a pass looks like

- `verify` prints **`OK: safe to edit`**: the game wrote a file the editor still reads perfectly.
- `diff` shows only what playing changed: logout position, play-time stats, maybe Run or Jump
  rising a little if you used them. Run should still be about 50, WoodCutting 25, and Swim about 10.
- The Skills panel in step 4 matched.

### What to send back

- The output of the two commands in step 6.
- What the Skills panel showed in step 4 (a screenshot is fine).
- Anything odd: the character failing to load, wrong values, items missing.

### Clean up afterwards

```powershell
Remove-Item "$saves\lorce_skilltest.fch"
Remove-Item "$saves\lorce_skilltest.fch.old" -ErrorAction SilentlyContinue   # the game may create this
```

Only delete the `lorce_skilltest*` files. Never delete `lorce.fch` or your backups.

**Note:** your save folder contains a `steam_autocloud.vdf`, so Steam may sync it. If Steam ever shows a
cloud-conflict prompt about these characters, choose to keep the **local** files.

## Edit inventory

```powershell
fch inv list Save\lorce.fch                                              # slot, name, stack, durability

fch inv set Save\lorce.fch --slot 4,2 --stack 50                          --out Save\edited.fch
fch inv set Save\lorce.fch --slot 0,0 --durability 80                     --out Save\edited.fch
fch inv remove Save\lorce.fch --slot 2,3                                  --out Save\edited.fch
fch inv add   Save\lorce.fch Coins --stack 500                            --out Save\edited.fch
fch inv add   Save\lorce.fch Wood --stack 50 --slot 7,0 --crafted-by-me   --out Save\edited.fch
```

- **Slots** are `X,Y` (`fch inv list` shows them); the grid is 8 wide, height from the save (usually 4).
- **`--stack`**: 1–65535. **`--durability`**: the same number shown by `fch info`/`fch inv list`, ≥ 0.
- **`add`** needs the exact, case-sensitive prefab name (e.g. `Wood`, not `wood` or `Log`). Unknown names are
  rejected, because the game silently deletes an item whose name it doesn't recognise. If you're sure a name
  from a newer game update is real, add `--allow-unknown-item`. Without `--slot`, the first free slot is used.
- **`--durability`** on `add` defaults to 100. The editor has no way to know a fresh item's real maximum
  durability (that lives in the game's own data, not the save), so tools and weapons may need a different
  value to look right in the durability bar.
- **`--crafted-by-me`** stamps the item as made by this character, matching how self-crafted items already
  look in the save.

## Graphical editor

For clicking instead of typing commands:

```powershell
fch gui                          # opens empty; use File > Open
fch gui Save\lorce.fch           # opens straight into a save
```

Or, once built (see below), just double-click **`dist\fch-editor.exe`** — no Python needed.

- **Tabs:** Overview (read-only summary), Skills, Character, Inventory. Each edit form has its own
  **Apply**/**Add**/**Remove** button; nothing is written to disk until you use **File > Save** or **Save As**.
- **Inventory view:** the **List / Grid** switch at the top of the Inventory tab shows the same items as a table
  or as the game's slot grid (List is the default each launch). Click an item in either view to load it into the
  **Selected item** form; click an empty slot to aim the Add form's *Slot* field at it. Items the grid can't place
  because their coordinates fall outside it (a mod, or a shrunken grid) appear as tiles under an **Outside the
  grid** heading, labelled with their real `x,y`, and edit like any other item. If two items claim the same slot,
  both are view-only (orange in Grid view), since an edit finds its item by slot. A read-only save can still
  switch views and inspect items.
- **Sort** (Inventory tab) tidies everything below the hotbar: items are ordered A–Z by in-game name, with the
  bigger stack first among identical items, and packed from the top-left of the second row. The hotbar (top row),
  equipped items and anything outside the grid stay where they are, and stacks are not merged. It switches to Grid
  view and asks **Keep this order?** — **Undo** (also Escape / closing the window) puts everything back exactly.
  A kept sort is still only pending until you save.
- **Add item > Browse…** opens a search window: type part of an in-game name (`tunic`) or a prefab name
  (`ArmorBronzeChest`) and click a result to fill the Name field. It starts empty on purpose — it lists only what
  you search for — and typing the name directly, including *allow unknown item*, still works.
- **File > Save** overwrites the open file (a timestamped backup is kept next to it, same as `--in-place`).
  **File > Save As…** writes a new file and leaves the original untouched, same as `--out`.
- Before writing, a dialog lists every field that will change — cancel there and nothing is written.
- A read-only save (see Troubleshooting) opens for viewing with editing disabled and the reason shown in the
  status bar.
- **File > Discard Pending Changes** drops everything you've entered without writing, in case you want to
  start over.

### Building the standalone .exe

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller   # build tool only, not a runtime dependency
.\tools\build_gui.ps1
```

Produces `dist\fch-editor.exe` (~11 MB), which runs on a machine with no Python installed. Windows SmartScreen
or antivirus may flag a fresh, unsigned PyInstaller build the first time — this is a known PyInstaller quirk,
not a sign of anything in the exe itself; running from source (`fch gui`) is always an alternative.

## Troubleshooting

| Message | Meaning / fix |
|---------|---------------|
| `Valheim is running ... close it first` | Quit the game fully, then retry (`--force` skips the check; not recommended) |
| `... already exists; pass --force` | `--out` points at an existing file; choose a new name or add `--force` (backup kept) |
| `FAIL: save is read-only for this editor` | Older or unknown save format; the reason is printed above it |
| `... changed since it was read` | The file was saved by something else mid-edit; just run the command again |
| `unknown skill 'X'` | Typo in the skill name; the valid names are listed in the message |

**Restoring:** every `--in-place` edit leaves `<name>.fch.bak-<date>-<time>` next to the file. To restore,
close Valheim and copy the backup back over `<name>.fch`.
