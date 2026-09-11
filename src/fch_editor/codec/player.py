"""Embedded player blob, player-data version 33 (spec §5)."""
from .. import versions
from ..errors import UnsupportedVersion
from ..model import Food, PlayerData
from ..reader import Reader
from ..writer import Writer
from .inventory import decode_inventory, encode_inventory
from .lists import read_string_pairs, read_strings, write_string_pairs, write_strings
from .skills import decode_skills, encode_skills


def decode_player(data: bytes, base_offset: int = 0) -> PlayerData:
    r = Reader(data, base_offset)
    with r.scope("player"):
        version = r.i32()
        if version != versions.PLAYER:
            raise UnsupportedVersion(f"player data version {version}, supported {versions.PLAYER}")
        max_health = r.f32()
        health = r.f32()
        max_stamina = r.f32()
        time_since_death = r.f32()
        guardian_power = r.string()
        guardian_power_cooldown = r.f32()
        with r.scope("inventory"):
            inventory_version, items = decode_inventory(r)
        known_recipes = read_strings(r)
        with r.scope("known_stations"):
            known_stations = [(r.string(), r.i32()) for _ in range(r.count(5))]
        known_materials = read_strings(r)
        shown_tutorials = read_strings(r)
        uniques = read_strings(r)
        trophies = read_strings(r)
        known_biomes = read_strings(r)
        known_texts = read_string_pairs(r)
        beard = r.string()
        hair = r.string()
        skin_color = r.vec3()
        hair_color = r.vec3()
        model_index = r.i32()
        with r.scope("foods"):
            foods = [Food(r.string(), r.f32()) for _ in range(r.count(5))]
        with r.scope("skills"):
            skills_version, skills = decode_skills(r)
        custom_data = read_string_pairs(r)
        stamina = r.f32()
        max_eitr = r.f32()
        eitr = r.f32()
        build_ui_state = r.bytes_()
        if not r.at_end():
            raise r.error(f"{r.remaining} unexpected bytes after player data")
    return PlayerData(
        version=version, max_health=max_health, health=health, max_stamina=max_stamina,
        time_since_death=time_since_death, guardian_power=guardian_power,
        guardian_power_cooldown=guardian_power_cooldown, inventory_version=inventory_version,
        items=items, known_recipes=known_recipes, known_stations=known_stations,
        known_materials=known_materials, shown_tutorials=shown_tutorials, uniques=uniques,
        trophies=trophies, known_biomes=known_biomes, known_texts=known_texts, beard=beard,
        hair=hair, skin_color=skin_color, hair_color=hair_color, model_index=model_index,
        foods=foods, skills_version=skills_version, skills=skills, custom_data=custom_data,
        stamina=stamina, max_eitr=max_eitr, eitr=eitr, build_ui_state=build_ui_state,
    )


def encode_player(p: PlayerData) -> bytes:
    w = Writer()
    w.i32(p.version)
    for v in (p.max_health, p.health, p.max_stamina, p.time_since_death):
        w.f32(v)
    w.string(p.guardian_power)
    w.f32(p.guardian_power_cooldown)
    encode_inventory(w, p.inventory_version, p.items)
    write_strings(w, p.known_recipes)
    w.i32(len(p.known_stations))
    for name, level in p.known_stations:
        w.string(name)
        w.i32(level)
    for lst in (p.known_materials, p.shown_tutorials, p.uniques, p.trophies, p.known_biomes):
        write_strings(w, lst)
    write_string_pairs(w, p.known_texts)
    w.string(p.beard)
    w.string(p.hair)
    w.vec3(p.skin_color)
    w.vec3(p.hair_color)
    w.i32(p.model_index)
    w.i32(len(p.foods))
    for food in p.foods:
        w.string(food.name)
        w.f32(food.time)
    encode_skills(w, p.skills_version, p.skills)
    write_string_pairs(w, p.custom_data)
    for v in (p.stamina, p.max_eitr, p.eitr):
        w.f32(v)
    w.bytes_(p.build_ui_state)
    return w.to_bytes()
