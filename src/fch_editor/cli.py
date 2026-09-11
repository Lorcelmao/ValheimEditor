"""`fch` command line: inspect and edit Valheim .fch saves.

Edit commands never write without an explicit destination (--out, --in-place)
and refuse any change the edit pipeline cannot prove is exactly the one asked for.

Exit codes: 0 success, 1 failure (read-only save, differences found, or error),
2 usage error (argparse).
"""
import argparse
import json
import sys
from pathlib import Path

from .catalog.enums import skill_name
from .catalog.items import ItemCatalog
from .diffing import diff
from .edits.pipeline import apply_edits, check_destination, write_result
from .edits.skills import ALL, SetSkillLevel, parse_level, parse_skill
from .errors import EditError, FchError
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


def cmd_skills_list(args) -> int:
    save = load_file(args.file)
    if save.profile is None or save.profile.player is None:
        print("cannot read skills: " + "; ".join(save.reasons), file=sys.stderr)
        return EXIT_FAIL
    print(f"{'skill':<16}{'level':>12}{'progress':>12}")
    for s in sorted(save.profile.player.skills, key=lambda s: skill_name(s.type)):
        print(f"{skill_name(s.type):<16}{s.level:>12g}{s.accumulator:>12g}")
    return EXIT_OK


def cmd_skills_set(args) -> int:
    edits, seen = [], set()
    for assignment in args.assignments:
        name, sep, level = assignment.partition("=")
        if not sep:
            raise EditError(f"expected SKILL=LEVEL, got {assignment!r}")
        skill = parse_skill(name)
        if skill in seen:
            raise EditError(f"{name.strip()} is given more than once")
        seen.add(skill)
        edits.append(SetSkillLevel(skill, parse_level(level), args.keep_progress))
    if ALL in seen and len(seen) > 1:
        raise EditError("'all' cannot be combined with individual skills")
    return _run_edits(args, edits)


def _run_edits(args, edits) -> int:
    """Shared tail of every edit command: plan, show the diff, then write."""
    if not args.dry_run:
        check_destination(args.file, args.out, args.in_place, args.force)
    save = load_file(args.file)
    for w in save.warnings:
        print(f"warning: {w}", file=sys.stderr)
    result = apply_edits(save, edits)
    if not result.changes:
        print("nothing to change: the save already has these values")
        return EXIT_OK
    print(diff_text(result.changes))
    if args.dry_run:
        print("dry run: nothing written")
        return EXIT_OK
    backup = write_result(result, args.file, args.out, args.in_place, args.force)
    target = args.file if args.in_place else args.out
    print(f"wrote {target}" + (f" (previous version backed up to {backup})" if backup else ""))
    return EXIT_OK


def _add_write_options(p: argparse.ArgumentParser) -> None:
    dest = p.add_mutually_exclusive_group(required=True)
    dest.add_argument("--out", type=Path, metavar="FILE", help="write the edited save to FILE")
    dest.add_argument("--in-place", action="store_true", help="overwrite the input (a backup is kept)")
    dest.add_argument("--dry-run", action="store_true", help="show the changes without writing")
    p.add_argument("--force", action="store_true",
                   help="write even if Valheim appears to be running or --out already exists (a backup is kept)")


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

    skills = sub.add_parser("skills", help="list or set skill levels").add_subparsers(dest="action", required=True)
    p = skills.add_parser("list", help="show every skill the character has")
    p.add_argument("file", type=Path)
    p.set_defaults(func=cmd_skills_list)
    p = skills.add_parser("set", help="set skill levels, e.g. Run=50 WoodCutting=25 or all=100 "
                                      "(any level >= 0; values above 100 are kept as-is)")
    p.add_argument("file", type=Path)
    p.add_argument("assignments", nargs="+", metavar="SKILL=LEVEL")
    p.add_argument("--keep-progress", action="store_true", help="keep progress toward the next level")
    _add_write_options(p)
    p.set_defaults(func=cmd_skills_set)
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
