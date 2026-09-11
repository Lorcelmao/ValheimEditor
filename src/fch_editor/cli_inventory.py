"""`fch inv` subcommand: list, set, remove and add inventory items.

Shares its write tail (`run_edits`) and destination flags with `cli_edits.py`.
"""
import argparse
from pathlib import Path

from .catalog.items import ItemCatalog
from .cli_edits import EXIT_FAIL, EXIT_OK, add_write_options, player_or_fail, run_edits
from .edits import inventory as inv
from .errors import EditError
from .render import item_line


def _catalog(args) -> ItemCatalog:
    return ItemCatalog.load(args.items or [])


def cmd_list(args) -> int:
    _, player = player_or_fail(args)
    if player is None:
        return EXIT_FAIL
    width, height = inv.grid_size(player)
    print(f"grid: {width}x{height}  ({len(player.items)} items)")
    catalog = _catalog(args)  # loaded once for the whole listing, not per item
    for it in sorted(player.items, key=lambda i: (i.y, i.x)):
        print("  " + item_line(it, catalog))
    return EXIT_OK


def cmd_set(args) -> int:
    edit = inv.SetItemField(inv.parse_slot(args.slot), stack=args.stack, durability=args.durability)
    return run_edits(args, [edit])


def cmd_remove(args) -> int:
    return run_edits(args, [inv.RemoveItem(inv.parse_slot(args.slot))])


def cmd_add(args) -> int:
    catalog = _catalog(args)
    if args.name not in catalog and not args.allow_unknown_item:
        raise EditError(
            f"{args.name!r} is not a known item prefab; check spelling, or pass --allow-unknown-item "
            "if it's a valid item from a newer game update (a wrong name makes the game delete it on load)")
    edit = inv.AddItem(
        prefab_name=args.name, prefab_hash=inv.parse_prefab_hash(args.name), stack=args.stack,
        slot=inv.parse_slot(args.slot) if args.slot else None, durability=args.durability,
        crafted_by_me=args.crafted_by_me,
    )
    return run_edits(args, [edit])


def register(sub) -> None:
    """Add the `inv` subcommand to the main parser's subparsers."""
    items_opt = argparse.ArgumentParser(add_help=False)
    items_opt.add_argument("--items", action="append", type=Path, metavar="FILE",
                           help="extra item prefab names, one per line (repeatable)")
    inv_p = sub.add_parser("inv", help="list or edit inventory items").add_subparsers(dest="action", required=True)

    p = inv_p.add_parser("list", parents=[items_opt], help="show every item, its slot, stack and durability")
    p.add_argument("file", type=Path)
    p.set_defaults(func=cmd_list)

    p = inv_p.add_parser("set", help="change stack and/or durability of the item at a slot")
    p.add_argument("file", type=Path)
    p.add_argument("--slot", required=True, metavar="X,Y", help="grid position, e.g. 3,0")
    p.add_argument("--stack", type=int, metavar="N", help="new stack size (1-65535)")
    p.add_argument("--durability", type=float, metavar="D", help="new durability (as shown by 'fch info')")
    add_write_options(p)
    p.set_defaults(func=cmd_set)

    p = inv_p.add_parser("remove", help="remove the item at a slot")
    p.add_argument("file", type=Path)
    p.add_argument("--slot", required=True, metavar="X,Y")
    add_write_options(p)
    p.set_defaults(func=cmd_remove)

    p = inv_p.add_parser("add", parents=[items_opt], help="add an item by prefab name")
    p.add_argument("file", type=Path)
    p.add_argument("name", help="prefab name, e.g. Wood, Coins (case-sensitive; see the bundled item list)")
    p.add_argument("--stack", type=int, default=1, metavar="N", help="stack size (default 1)")
    p.add_argument("--durability", type=float, default=inv.DEFAULT_DURABILITY, metavar="D",
                   help=f"durability (default {inv.DEFAULT_DURABILITY:g}; tools/weapons may need a different value "
                        "since max durability isn't stored in the save)")
    p.add_argument("--slot", metavar="X,Y", help="grid position (default: first free slot)")
    p.add_argument("--crafted-by-me", action="store_true", help="mark the item as crafted by this character")
    p.add_argument("--allow-unknown-item", action="store_true",
                   help="add a name not in the item catalog (risk: the game deletes it on load if the name is wrong)")
    add_write_options(p)
    p.set_defaults(func=cmd_add)
