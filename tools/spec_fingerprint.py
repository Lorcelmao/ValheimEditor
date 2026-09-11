"""Fingerprint the game methods that define the .fch layout.

Hashes (never stores) the decompiled bodies of each serializer method so a game
update that touches the save format is detected. Run after
tools/decompile_save_code.ps1:

    py -3.13 tools/spec_fingerprint.py            # compare with docs/spec-fingerprints.json
    py -3.13 tools/spec_fingerprint.py --write    # record current game build as reviewed
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECOMPILED = ROOT / ".local" / "decompiled"
FINGERPRINTS = ROOT / "docs" / "spec-fingerprints.json"
GAME_DLL = Path(r"D:\SteamLibrary\steamapps\common\Valheim\valheim_Data\Managed\assembly_valheim.dll")

# (decompiled file, unique signature substring) for every method the codec mirrors.
METHODS = [
    ("PlayerProfile.cs", "private bool SavePlayerToDisk()"),
    ("PlayerProfile.cs", "private bool LoadPlayerFromDisk()"),
    ("PlayerProfile.cs", "private ZPackage LoadPlayerDataFromDisk()"),
    ("Player.cs", "public void Save(ZPackage pkg)"),
    ("Player.cs", "public void Load(ZPackage pkg)"),
    ("Inventory.cs", "public void Save(ZPackage pkg)"),
    ("Inventory.cs", "public void Load(ZPackage pkg)"),
    ("ItemDrop.cs", "public void Save(ZPackage pkg)"),
    ("ItemDrop.cs", "public static int Load(ZPackage pkg, ItemData itemData, Version.Item itemVersion)"),
    ("Skills.cs", "public void Save(ZPackage pkg)"),
    ("Skills.cs", "public void Load(ZPackage pkg)"),
    ("Skills.cs", "public enum SkillType"),
    ("Minimap.cs", "private byte[] GetMapData()"),
    ("Minimap.cs", "private void SetMapData(byte[] data)"),
    ("BuildUi.cs", "public byte[] SaveToBinary()"),
    ("ZPackage.cs", "public void WriteNumItems(int numItems)"),
    ("ZPackage.cs", "public void Write(string data)"),
    ("StringExtensionMethods.cs", "public static int GetStableHashCode(this string str)"),
    ("PlayerStatType.cs", "public enum PlayerStatType"),
    ("DifficultyRequirement.cs", "public enum DifficultyRequirement"),
    ("Version.cs", "public abstract class Version"),
]


def extract_block(text: str, signature: str) -> str:
    """Return the signature line through its matching closing brace."""
    start = text.find(signature)
    if start < 0:
        raise KeyError(signature)
    open_at = text.index("{", start)
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError(f"unbalanced braces after {signature!r}")


def current() -> dict:
    methods = {}
    for file, sig in METHODS:
        try:
            body = extract_block((DECOMPILED / file).read_text(encoding="utf-8-sig"), sig)
        except (FileNotFoundError, KeyError, ValueError):
            # Renamed/removed by a game update: reported as changed, not a crash.
            methods[f"{file}::{sig}"] = "MISSING"
            continue
        normalized = "\n".join(line.strip() for line in body.splitlines() if line.strip())
        methods[f"{file}::{sig}"] = hashlib.sha256(normalized.encode()).hexdigest()
    dll = GAME_DLL.read_bytes()
    return {
        "game": {"assembly_valheim_sha256": hashlib.sha256(dll).hexdigest(), "size": len(dll)},
        "methods": methods,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="record current fingerprints as reviewed")
    args = ap.parse_args()
    now = current()
    if args.write:
        missing = [k for k, h in now["methods"].items() if h == "MISSING"]
        if missing:
            print("refusing to record: methods not found:\n  " + "\n  ".join(missing))
            return 1
        FINGERPRINTS.write_text(json.dumps(now, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {FINGERPRINTS.relative_to(ROOT)} ({len(now['methods'])} methods)")
        return 0
    reviewed = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))
    changed = [k for k, h in now["methods"].items() if reviewed["methods"].get(k) != h]
    if now["game"] != reviewed["game"]:
        print("game assembly differs from reviewed build")
    for k in changed:
        print(f"CHANGED: {k}")
    print("format-relevant code unchanged" if not changed else f"{len(changed)} method(s) need re-review")
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
