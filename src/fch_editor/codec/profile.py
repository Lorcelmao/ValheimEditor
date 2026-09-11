"""Profile payload, version 46 (spec §4)."""
from .. import versions
from ..errors import FormatError, UnsupportedVersion
from ..model import Profile, StatBlock, WorldData
from ..reader import Reader
from ..writer import Writer
from .lists import read_string_floats, write_string_floats
from .player import decode_player, encode_player

PAYLOAD_OFFSET = 4  # payload starts after the envelope's i32 length; errors report file offsets


def _decode_stat_block(r: Reader, stat_count: int) -> StatBlock:
    # One read per statement: the file order is the contract, not argument order.
    stats = [r.f32() for _ in range(stat_count)]
    known_worlds = read_string_floats(r)
    known_world_keys = read_string_floats(r)
    known_commands = read_string_floats(r)
    enemy_stats = [read_string_floats(r) for _ in range(r.count(4))]
    item_pickup = read_string_floats(r)
    item_craft = read_string_floats(r)
    pickable = read_string_floats(r)
    food_eaten = read_string_floats(r)
    pieces_placed = read_string_floats(r)
    return StatBlock(stats=stats, known_worlds=known_worlds, known_world_keys=known_world_keys,
                     known_commands=known_commands, enemy_stats=enemy_stats, item_pickup=item_pickup,
                     item_craft=item_craft, pickable=pickable, food_eaten=food_eaten,
                     pieces_placed=pieces_placed)


def _encode_stat_block(w: Writer, b: StatBlock, stat_count: int) -> None:
    if len(b.stats) != stat_count:
        raise ValueError(f"stat block has {len(b.stats)} stats, profile declares {stat_count}")
    for v in b.stats:
        w.f32(v)
    for d in (b.known_worlds, b.known_world_keys, b.known_commands):
        write_string_floats(w, d)
    w.i32(len(b.enemy_stats))
    for d in b.enemy_stats:
        write_string_floats(w, d)
    for d in (b.item_pickup, b.item_craft, b.pickable, b.food_eaten, b.pieces_placed):
        write_string_floats(w, d)


def _decode_world(r: Reader) -> WorldData:
    uid = r.i64()
    have_custom_spawn, spawn = r.bool(), r.vec3()
    have_logout, logout = r.bool(), r.vec3()
    have_death, death = r.bool(), r.vec3()
    home = r.vec3()
    map_data = r.bytes_() if r.bool() else None
    return WorldData(uid, have_custom_spawn, spawn, have_logout, logout, have_death, death, home, map_data)


def _encode_world(w: Writer, wd: WorldData) -> None:
    w.i64(wd.uid)
    w.bool(wd.have_custom_spawn)
    w.vec3(wd.spawn_point)
    w.bool(wd.have_logout)
    w.vec3(wd.logout_point)
    w.bool(wd.have_death)
    w.vec3(wd.death_point)
    w.vec3(wd.home_point)
    w.bool(wd.map_data is not None)
    if wd.map_data is not None:
        w.bytes_(wd.map_data)


def decode_profile(payload: bytes) -> Profile:
    """Decode a payload. A player blob that fails to decode is kept raw and
    reported in `player_error` so the rest of the save stays inspectable."""
    r = Reader(payload, PAYLOAD_OFFSET)
    version = r.i32()
    if version != versions.PROFILE:
        raise UnsupportedVersion(f"profile version {version}, supported {versions.PROFILE}")
    stat_count = r.count(4)
    blocks = []
    for i in range(r.count()):
        with r.scope(f"stat_blocks[{i}]"):
            blocks.append(_decode_stat_block(r, stat_count))
    first_spawn = r.bool()
    worlds = []
    for i in range(r.count(46)):
        with r.scope(f"worlds[{i}]"):
            worlds.append(_decode_world(r))
    name, player_id, start_seed = r.string(), r.i64(), r.string()
    used_cheats, date_created = r.bool(), r.i64()
    player_raw = player_at = None
    if r.bool():
        player_at = r.offset + 4
        player_raw = r.bytes_()
    if not r.at_end():
        raise r.error(f"{r.remaining} unexpected bytes after profile")
    profile = Profile(version, stat_count, blocks, first_spawn, worlds, name, player_id, start_seed,
                      used_cheats, date_created, player=None, player_raw=player_raw)
    if player_raw is not None:
        try:
            profile.player = decode_player(player_raw, player_at)
        except (FormatError, UnsupportedVersion) as e:
            profile.player_error = str(e)
    return profile


def encode_profile(p: Profile) -> bytes:
    w = Writer()
    w.i32(p.version)
    w.i32(p.stat_count)
    w.i32(len(p.stat_blocks))
    for b in p.stat_blocks:
        _encode_stat_block(w, b, p.stat_count)
    w.bool(p.first_spawn)
    w.i32(len(p.worlds))
    for wd in p.worlds:
        _encode_world(w, wd)
    w.string(p.name)
    w.i64(p.player_id)
    w.string(p.start_seed)
    w.bool(p.used_cheats)
    w.i64(p.date_created)
    player_bytes = encode_player(p.player) if p.player is not None else p.player_raw
    w.bool(player_bytes is not None)
    if player_bytes is not None:
        w.bytes_(player_bytes)
    return w.to_bytes()
