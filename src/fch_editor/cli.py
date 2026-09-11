"""`fch` command line: inspect Valheim .fch saves (read-only commands).

Exit codes: 0 success, 1 failure (read-only save, differences found, or error),
2 usage error (argparse).
"""
import argparse
import json
import sys
from pathlib import Path

from .catalog.items import ItemCatalog
from .diffing import diff
from .errors import FchError
from .load import load_file
from .render import diff_text, info_text, to_json

EXIT_OK, EXIT_FAIL = 0, 1


def _catalog(args) -> ItemCatalog:
    return ItemCatalog.load(args.items or [])


def cmd_info(args) -> int:
    print(info_text(load_file(args.file), _catalog(args)))
    return EXIT_OK


def cmd_dump(args) -> int:
    doc = to_json(load_file(args.file), _catalog(args), args.section)
    print(json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False))
    return EXIT_OK


def cmd_verify(args) -> int:
    save = load_file(args.file)
    print(f"hash      : {'ok' if save.hash_ok else 'mismatch (ignored by the game; rewritten on save)'}")
    print(f"round trip: {'identical' if save.writable else 'not verified (see below)'}")
    for r in save.reasons:
        print(f"read-only : {r}")
    for w in save.warnings:
        print(f"warning   : {w}")
    print("OK: safe to edit" if save.writable else "FAIL: save is read-only for this editor")
    return EXIT_OK if save.writable else EXIT_FAIL


def cmd_diff(args) -> int:
    a, b = load_file(args.a), load_file(args.b)
    if a.profile is None or b.profile is None:
        print("cannot diff: " + "; ".join(a.reasons + b.reasons), file=sys.stderr)
        return EXIT_FAIL
    changes = diff(a.profile, b.profile)
    print(diff_text(changes))
    return EXIT_OK if not changes else EXIT_FAIL


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--items", action="append", type=Path, metavar="FILE",
                        help="extra item prefab names, one per line (repeatable)")
    ap = argparse.ArgumentParser(prog="fch", description="Inspect Valheim .fch character saves.")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("info", parents=[common], help="summary of a save")
    p.add_argument("file", type=Path)
    p.set_defaults(func=cmd_info)
    p = sub.add_parser("dump", parents=[common], help="full contents as JSON")
    p.add_argument("file", type=Path)
    p.add_argument("--section", choices=["stats", "worlds", "player", "inventory", "skills"])
    p.set_defaults(func=cmd_dump)
    p = sub.add_parser("verify", help="check the save is intact and safe to edit (exit 1 if not)")
    p.add_argument("file", type=Path)
    p.set_defaults(func=cmd_verify)
    p = sub.add_parser("diff", help="field-level differences between two saves (exit 1 if any)")
    p.add_argument("a", type=Path)
    p.add_argument("b", type=Path)
    p.set_defaults(func=cmd_diff)
    return ap


def _utf8_streams() -> None:
    # Saves hold free text (names, pins); Windows redirects default to cp1252.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FchError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_FAIL
    except OSError as e:
        print(f"error: {e.strerror or e}: {e.filename}", file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
