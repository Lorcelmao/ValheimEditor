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

# PyInstaller writes its progress log to stderr, and Windows PowerShell turns
# any stderr line from a native command into a terminating NativeCommandError
# while $ErrorActionPreference is 'Stop' -- so the build died on the very first
# banner line, having built nothing, with an error that looked like a
# PyInstaller crash rather than a shell artifact. Relax the preference for the
# call itself; $LASTEXITCODE below is the actual success signal.
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    & $pyinstaller --noconfirm --onefile --windowed --name fch-editor `
        --paths "$root\src" `
        --add-data "$root\src\fch_editor\catalog\data\items.txt;fch_editor\catalog\data" `
        --distpath "$root\dist" --workpath "$root\build" --specpath "$root\build" `
        "$root\tools\gui_launcher.py"
} finally {
    $ErrorActionPreference = $previousPreference
}
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed with exit code $LASTEXITCODE" }

Write-Output "Built: $root\dist\fch-editor.exe"
