# Builds a double-clickable Windows .exe for the GUI (no console window).
# Requires: pip install pyinstaller (a build-time tool only; the app itself
# stays stdlib-only). Run from the project root: .\tools\build_gui.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

# Run pyinstaller out of the project venv explicitly. A bare `pyinstaller`
# only resolves when a venv happens to be activated in the caller's shell --
# otherwise it fails outright, or (worse) picks up a different interpreter's
# copy. tools\build_web.ps1 calls its Python the same way, for the same reason.
$pyinstaller = "$root\.venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $pyinstaller)) {
    throw "pyinstaller not found at $pyinstaller -- run: .venv\Scripts\python.exe -m pip install pyinstaller"
}

& $pyinstaller --noconfirm --onefile --windowed --name fch-editor `
    --paths "$root\src" `
    --add-data "$root\src\fch_editor\catalog\data\items.txt;fch_editor\catalog\data" `
    --distpath "$root\dist" --workpath "$root\build" --specpath "$root\build" `
    "$root\tools\gui_launcher.py"
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed with exit code $LASTEXITCODE" }

Write-Output "Built: $root\dist\fch-editor.exe"
