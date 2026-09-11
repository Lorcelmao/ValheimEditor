"""Golden tests: the codec must reproduce real saves byte-for-byte."""
from fch_editor.codec.map_blob import decode_map, decode_map_inner, encode_map, encode_map_inner, split_map
from fch_editor.load import encode_save, load_bytes


def test_sample_is_writable_and_roundtrips(sample_bytes):
    save = load_bytes(sample_bytes)
    assert save.writable, save.reasons
    assert save.hash_ok
    assert encode_save(save.profile) == sample_bytes


def test_sample_decodes_to_expected_values(sample_bytes):
    p = load_bytes(sample_bytes).profile
    assert (p.version, p.stat_count, len(p.stat_blocks)) == (46, 205, 10)
    assert p.name == "Lorce" and p.player_id == 2434692871
    assert len(p.worlds) == 2 and all(w.map_data for w in p.worlds)
    pd = p.player
    assert (pd.version, pd.inventory_version, pd.skills_version) == (33, 109, 2)
    assert len(pd.items) == 19 and len(pd.skills) == 13
    assert pd.known_biomes == ["Meadows", "Black Forest"]
    assert (pd.beard, pd.hair) == ("BeardNone", "Hair24")
    assert len(pd.build_ui_state) == 1089
    # Every sample item was spawned from a prefab, so all carry a hash.
    assert all(item.prefab_hash != 0 for item in pd.items)
    wood = [i for i in pd.items if i.prefab_hash == int.from_bytes(bytes.fromhex("c324f3f6"), "little", signed=True)]
    assert sorted(i.stack for i in wood) == [6, 16, 50]


def test_map_inner_roundtrips(sample_bytes):
    p = load_bytes(sample_bytes).profile
    for world in p.worlds:
        version, inner = split_map(world.map_data)
        m = decode_map_inner(inner, version)
        assert m.texture_size == 2048
        assert encode_map_inner(m) == inner


def test_map_reencode_is_semantically_identical(sample_bytes):
    world = load_bytes(sample_bytes).profile.worlds[1]
    m = decode_map(world.map_data)
    assert [pin.name for pin in m.pins] == ["$enemy_eikthyr", "$hud_mapday 2"]
    # Our gzip bytes differ from the game's, but decode to the same map.
    assert decode_map(encode_map(m)) == m
