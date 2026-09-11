# Decompiles the Valheim types involved in .fch serialization into .local/decompiled/.
# Output is for local format research only and must never be committed (see .gitignore).
param(
    [string]$GameDir = 'D:\SteamLibrary\steamapps\common\Valheim',
    [string]$OutDir = (Join-Path $PSScriptRoot '..\.local\decompiled')
)
$ErrorActionPreference = 'Stop'

$managed = Join-Path $GameDir 'valheim_Data\Managed'
if (-not (Test-Path (Join-Path $managed 'assembly_valheim.dll'))) { throw "assembly_valheim.dll not found under $managed" }

$ilspy = Join-Path $env:USERPROFILE '.dotnet\tools\ilspycmd.exe'
if (-not (Test-Path $ilspy)) { throw 'ilspycmd not installed: dotnet tool install -g ilspycmd --version 9.1.0.7988' }

# Types whose Save/Load code defines the player profile layout.
# Nested types (Skills.SkillType, Minimap.PinData, Player.Food...) are emitted with their parent.
# Entries are 'Type' (assembly_valheim) or 'assembly_name:Type'.
$types = @(
    'PlayerProfile', 'Player', 'Inventory', 'ItemDrop', 'Skills', 'Minimap', 'BuildUi',
    'PlayerStatType', 'DifficultyRequirement', 'ZPackage', 'Version', 'GameVersion', 'ExtensionMethods',
    'assembly_utils:Utils', 'assembly_utils:StringExtensionMethods'
)

New-Item -ItemType Directory -Force $OutDir | Out-Null
foreach ($entry in $types) {
    $dll, $t = if ($entry -match ':') { $entry.Split(':') } else { 'assembly_valheim', $entry }
    $file = Join-Path $OutDir ($t + '.cs')
    & $ilspy (Join-Path $managed "$dll.dll") -t $t -r $managed 2>$null | Out-File -Encoding utf8 $file
    if ($LASTEXITCODE -ne 0) { throw "ilspycmd failed for $entry (exit $LASTEXITCODE)" }
    $lines = (Get-Content $file | Measure-Object -Line).Lines
    Write-Output ("{0,-28} {1,6} lines" -f $entry, $lines)
}
