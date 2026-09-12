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
