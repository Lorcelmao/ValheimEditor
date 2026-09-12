"""Edit subcommands (`skills`, `char`) for the `fch` command line.

Every edit command shares one tail (`run_edits`): validate the destination,
build typed edits, run them through the verified pipeline, print the exact
field changes, then write (unless --dry-run). `cli_inventory.py` reuses these
same helpers for the `inv` subcommand.
"""
import argparse
import sys
from pathlib import Path

from .catalog.appearance import GUARDIAN_POWERS
from .catalog.enums import skill_name
from .edits import character as ch
from .edits.pipeline import apply_edits
from .edits.skills import ALL, SetSkillLevel, parse_level, parse_skill
from .edits.values import parse_number
from .edits.write import check_destination, write_result
from .errors import EditError
from .load import load_file
from .render import diff_text, f32_text

EXIT_OK, EXIT_FAIL = 0, 1


def run_edits(args, edits) -> int:
    if not edits:
        raise EditError("nothing to do: give at least one field to change")
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


def player_or_fail(args):
    save = load_file(args.file)
    if save.profile is None or save.profile.player is None:
        print("cannot read player data: " + "; ".join(save.reasons), file=sys.stderr)
        return None, None
    return save.profile, save.profile.player


def add_write_options(p: argparse.ArgumentParser) -> None:
    dest = p.add_mutually_exclusive_group(required=True)
    dest.add_argument("--out", type=Path, metavar="FILE", help="write the edited save to FILE")
    dest.add_argument("--in-place", action="store_true", help="overwrite the input (a backup is kept)")
    dest.add_argument("--dry-run", action="store_true", help="show the changes without writing")
    p.add_argument("--force", action="store_true",
                   help="write even if Valheim appears to be running or --out already exists (a backup is kept)")


def cmd_skills_list(args) -> int:
    _, player = player_or_fail(args)
    if player is None:
        return EXIT_FAIL
    print(f"{'skill':<16}{'level':>12}{'progress':>12}")
    for s in sorted(player.skills, key=lambda s: skill_name(s.type)):
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
    return run_edits(args, edits)


def cmd_char_show(args) -> int:
    profile, p = player_or_fail(args)
    if p is None:
        return EXIT_FAIL
    power = GUARDIAN_POWERS.get(p.guardian_power, p.guardian_power) if p.guardian_power else "none"
    rgb = lambda v: ",".join(f32_text(c) for c in v)  # noqa: E731  exact stored values
    for label, value in (("name", profile.name), ("model", p.model_index), ("beard", p.beard),
                         ("hair", p.hair), ("skin color", rgb(p.skin_color)), ("hair color", rgb(p.hair_color)),
                         ("guardian power", f"{power} (cooldown {p.guardian_power_cooldown:g}s)")):
        print(f"{label:<15}: {value}")
    return EXIT_OK


def cmd_char_set(args) -> int:
    edits = []
    if args.name is not None:
        edits.append(ch.SetName(args.name))
    if args.beard is not None:
        edits.append(ch.SetBeard(args.beard, args.allow_unknown_style))
    if args.hair is not None:
        edits.append(ch.SetHair(args.hair, args.allow_unknown_style))
    if args.skin is not None:
        edits.append(ch.SetColor("skin_color", ch.parse_color(args.skin)))
    if args.hair_color is not None:
        edits.append(ch.SetColor("hair_color", ch.parse_color(args.hair_color)))
    if args.model is not None:
        edits.append(ch.SetModel(args.model))
    if args.guardian_power is not None:
        edits.append(ch.SetGuardianPower(ch.parse_guardian_power(args.guardian_power)))
    if args.gp_cooldown is not None:
        edits.append(ch.SetGuardianCooldown(parse_number(args.gp_cooldown, "guardian power cooldown")))
    return run_edits(args, edits)


def register(sub) -> None:
    """Add the `skills` and `char` subcommands to the main parser's subparsers."""
    skills = sub.add_parser("skills", help="list or set skill levels").add_subparsers(dest="action", required=True)
    p = skills.add_parser("list", help="show every skill the character has")
    p.add_argument("file", type=Path)
    p.set_defaults(func=cmd_skills_list)
    p = skills.add_parser("set", help="set skill levels, e.g. Run=50 WoodCutting=25 or all=100 "
                                      "(any level >= 0; values above 100 are kept as-is)")
    p.add_argument("file", type=Path)
    p.add_argument("assignments", nargs="+", metavar="SKILL=LEVEL")
    p.add_argument("--keep-progress", action="store_true", help="keep progress toward the next level")
    add_write_options(p)
    p.set_defaults(func=cmd_skills_set)

    char = sub.add_parser("char", help="show or set name and appearance").add_subparsers(dest="action", required=True)
    p = char.add_parser("show", help="name, body, beard, hair, colors, guardian power")
    p.add_argument("file", type=Path)
    p.set_defaults(func=cmd_char_show)
    p = char.add_parser("set", help="change name, appearance or guardian power")
    p.add_argument("file", type=Path)
    p.add_argument("--name", help="display name (the file name on disk is not changed)")
    p.add_argument("--beard", help="beard style, e.g. BeardNone, Beard5")
    p.add_argument("--hair", help="hair style, e.g. HairNone, Hair24")
    p.add_argument("--skin", metavar="R,G,B", help="skin color, e.g. 0.8,0.8,0.8")
    p.add_argument("--hair-color", metavar="R,G,B", help="hair color, e.g. 0.1,0.05,0.03")
    p.add_argument("--model", type=int, choices=(0, 1), help="body model")
    p.add_argument("--guardian-power", metavar="POWER",
                   help="Eikthyr, TheElder, Bonemass, Moder, Yagluth, Queen, Fader (Ashlands), DeepNorth, or none")
    p.add_argument("--gp-cooldown", metavar="SECONDS", help="guardian power cooldown in seconds")
    p.add_argument("--allow-unknown-style", action="store_true",
                   help="accept beard/hair names not in the known list (newer game versions)")
    add_write_options(p)
    p.set_defaults(func=cmd_char_set)
