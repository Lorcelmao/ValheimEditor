# Web App

**Live:** <https://lorcelmao.github.io/ValheimEditor/>

A browser-based sibling of the CLI and Tkinter GUI: upload a `.fch` save, view and edit it, download
the result. No backend — the save never leaves your machine. See
`plans/260912-0936-fch-web-editor-pyodide/plan.md` for the architecture decision and full history.

## How it works

The same Python package this repo ships as a CLI and a Tkinter GUI (`src/fch_editor/`) runs
unmodified inside [Pyodide](https://pyodide.org/) — CPython compiled to WebAssembly — directly in
the browser tab. `web/app.js` is a small amount of JavaScript that loads Pyodide, installs the
`fch_editor` wheel into it via `micropip`, and drives `fch_editor.web.bridge.Session` (a JSON-in/
JSON-out facade over the same edit pipeline the CLI uses) to open a file, preview edits, and produce
the bytes to download. There is no server component beyond serving static files.

## Running it locally

```powershell
.venv\Scripts\python.exe -m pip install build
.\tools\build_web.ps1
cd web
python -m http.server
```

Then open `http://localhost:8000`. `build_web.ps1` builds the wheel fresh and copies it (plus a
small manifest naming it) into `web/` — both are gitignored and must be rebuilt before every local
run or deploy; see the "Staleness guard" note in the parent plan for why this is a script step and
never a committed file.

## Self-hosting Pyodide

`web/index.html` loads the Pyodide runtime from the jsDelivr CDN, pinned to an exact version so an
upstream release can't silently change float or stdlib behaviour under the app. To remove that
third-party dependency (or if the CDN is unreachable in your environment):

1. Download the matching Pyodide release's `full/` distribution.
2. Copy it into `web/vendor/pyodide/`.
3. Change `index.html`'s `<script src="https://cdn.jsdelivr.net/pyodide/...">` to point at
   `vendor/pyodide/pyodide.js`.

This costs roughly 10 MB of your own host's bandwidth per first-time visitor (cached afterward) in
exchange for no third-party request.

## The inventory grid

The Inventory tab lays items out on the same 8×N grid the game uses, sized from the save's own
`invrows` rather than a fixed height. Select a slot (click, or arrow-keys — the grid is a single tab
stop) to see the full item in the panel below and edit its stack or durability; select an empty slot
to aim **Add item** at those exact coordinates.

Items the grid cannot place are listed underneath it rather than hidden — an item whose coordinates
fall outside the grid (a mod, or a shrunken `invrows`), or two items claiming the same slot. The
out-of-grid ones stay fully editable. Items sharing a slot are shown read-only, because an edit
addressed by slot would be ambiguous and the editor refuses to guess which one you meant.

Item names show the in-game name with the prefab codename beside it. The prefab name is the real
identifier — it is what the save stores, what `fch inv add` takes, and what you type to add an item.

Selecting an occupied slot also offers **Copy**, which duplicates that item into a free slot with its
upgrade level, variant, crafter and any other data intact — not a fresh, un-upgraded copy of the same
prefab. Not offered on a shared-slot item, for the same reason those can't be edited by slot at all.

## Picking items to add

**Add item** takes a prefab name directly, for when you already know it. **Browse…** opens a picker
over the whole catalog: search matches either the in-game name or the prefab codename (`tunic` and
`ArmorBronze` both find Bronze Plate Tunic), sorted by name or by what you've added recently. Select
several and they are queued as separate edits in one pass.

If some of them don't fit — the inventory has a finite number of slots — the ones that did are kept,
the picker stays open, and only the items that failed remain selected, so clicking Add again retries
exactly those rather than adding the successful ones twice.

Typing a name the catalog doesn't know still works, with **allow unknown item** ticked. That matters:
the bundled catalog can fall behind a game update, and this is how you add something newer than it.

The picker remembers the last 20 items you added, in your browser's local storage, to power the
"recently used" sort. That list never leaves your machine and is the only thing this app stores; a
browser that blocks storage loses the convenience and nothing else.

## What the web app cannot do

Unlike the CLI (`safe_io.py`) and the Tkinter GUI, the browser has no access to your filesystem or
process list, so it cannot:

- Write the edited save back in place — every edit is a **download**, a new file, never an
  overwrite.
- Keep an automatic timestamped backup.
- Detect whether Valheim is currently running.

The in-app safety banner states this plainly. Always keep your original save and close Valheim
before replacing it with an edited copy.

## Deployment

Hosted on **GitHub Pages**, chosen over Cloudflare/Netlify/Vercel because the repo is already public
and Pages needs no new account or external service — the bandwidth advantage those alternatives would
otherwise offer is moot once Pyodide itself is CDN-served rather than self-hosted. See
`plans/260912-0936-fch-web-editor-pyodide/phase-05-deploy-and-docs.md` for the full comparison.

`.github/workflows/deploy-web.yml` runs on every push to `master`:

1. Run the full test suite (`pytest -q`) — includes `tests/test_web_cli_parity.py`'s byte-parity
   checks against the real CLI and `tests/test_web_bridge.py`'s per-edit-kind checks. **A failing
   test blocks the deploy** — a broken build can never reach Pages.
2. Build the wheel fresh from a clean `build/` directory (the same staleness class this plan hit once
   before — see phase 5's file — made structurally impossible, not just avoided by discipline).
3. Copy the wheel and a small manifest naming it into `web/`, then upload `web/` as the Pages
   artifact and deploy it.

No wheel is ever committed to the repository; every deploy builds one from the current source.

## Local development vs. deployment

Both paths produce the same `web/` directory content — `tools/build_web.ps1` locally,
`deploy-web.yml` in CI — so what you see with `python -m http.server` locally is what ships.

## Limits carried over from the desktop editor

Same format-support scope as the CLI and GUI: no map/pin editing, stat-block editing, food/custom-data
editing, or item quality/variant. See the main `README.md`'s "What it can do" table.
