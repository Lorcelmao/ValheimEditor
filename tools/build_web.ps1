# Builds the fch_editor wheel and copies it next to the static web assets, so
# `web/` is a self-contained, servable directory (see web/index.html, which
# loads the wheel by its exact filename via micropip). Run from the project
# root: .\tools\build_web.ps1
#
# Requires: pip install build (a build-time tool only; the app itself stays
# stdlib-only, and the wheel it produces is never committed -- see
# .gitignore -- so this script must be run fresh before every deploy).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$distDir = "$root\.local\web-dist"
$python = "$root\.venv\Scripts\python.exe"

if (Test-Path $distDir) { Remove-Item -Recurse -Force $distDir }

# setuptools' build_py stages sources into <root>\build\lib incrementally and
# does not prune files deleted from src\ -- a stale build\ directory from an
# earlier build can silently ship a file that no longer exists in source
# (caught here once: a deleted src\fch_editor\gui\state.py leaked back into
# this very wheel from a build\ directory left over from an earlier phase's
# build). Wheel builds must start clean, always.
foreach ($stale in @("$root\build", (Get-ChildItem "$root\src\*.egg-info" -Directory -ErrorAction SilentlyContinue))) {
    if ($stale -and (Test-Path $stale)) { Remove-Item -Recurse -Force $stale }
}

& $python -m build --wheel --outdir $distDir "$root"
if ($LASTEXITCODE -ne 0) { throw "wheel build failed" }

$wheel = Get-ChildItem "$distDir\*.whl" | Select-Object -First 1
if (-not $wheel) { throw "no wheel produced in $distDir" }

# Remove any previously copied wheel first: micropip resolves the wheel by
# its exact filename, so a stale second .whl left behind by a version bump
# would be ambiguous.
Get-ChildItem "$root\web\*.whl" -ErrorAction SilentlyContinue | Remove-Item -Force
Copy-Item $wheel.FullName "$root\web\"

# app.js learns the wheel's exact filename from this manifest instead of
# hardcoding a version string that pyproject.toml's own version would
# silently drift away from on the next bump. Written without a BOM: Windows
# PowerShell 5.1's `-Encoding utf8` adds one, which browsers tolerate but
# plenty of JSON consumers (Node's JSON.parse included) do not.
$json = @{ file = $wheel.Name } | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText("$root\web\wheel.json", $json, [System.Text.UTF8Encoding]::new($false))

$sizeKb = [math]::Round((Get-Item "$root\web\$($wheel.Name)").Length / 1KB, 1)
Write-Output "Built: web\$($wheel.Name) ($sizeKb KB)"
