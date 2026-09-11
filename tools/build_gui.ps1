# Builds a double-clickable Windows .exe for the GUI (no console window).
# Requires: pip install pyinstaller (a build-time tool only; the app itself
# stays stdlib-only). Run from the project root: .\tools\build_gui.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

& pyinstaller --noconfirm --onefile --windowed --name fch-editor `
    --paths "$root\src" `
    --add-data "$root\src\fch_editor\catalog\data\items.txt;fch_editor\catalog\data" `
    --distpath "$root\dist" --workpath "$root\build" --specpath "$root\build" `
    "$root\tools\gui_launcher.py"

Write-Output "Built: $root\dist\fch-editor.exe"
