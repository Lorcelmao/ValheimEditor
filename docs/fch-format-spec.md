# Valheim `.fch` Player Profile Format

Authoritative layout used by the editor's codec. Written from two independent sources:

- **Bytes**: sample save (`Save/lorce.fch`, 37,245 B) parsed and re-serialized byte-identically.
- **Game code**: local read-only decompile of the installed game (Valheim **1.0.7**, `assembly_valheim.dll`
  SHA-256 in `docs/spec-fingerprints.json`). No game code is stored in this repo; regenerate with
  `tools/decompile_save_code.ps1` and check drift with `py -3.13 tools/spec_fingerprint.py`.

Confidence tags: **[B+C]** bytes and code agree · **[C]** code only (branch absent from sample) · **[B]** bytes only.

## 1. Version table

| Section | Constant in game | Value | Notes |
|---------|------------------|-------|-------|
| Profile | `Version.Player.DeepNorth` | **46** | oldest loadable: 27 |
| Player data | `Version.PlayerData.ChunkedNorth` | **33** | |
| Inventory items | `Version.Item.ChunksNCheats` | **109** | compact records since 108 (`Smaller`) |
| Skills | literal | **2** | |
| Map | `Version.Map.PinsAuthor` | **8** | compressed since 7 |

The editor writes only when profile, player data, inventory and skills match this table, and re-encoding
reproduces the original payload byte-for-byte. Anything else opens read-only. Map blobs pass through
untouched, so their version only gates map inspection and editing.

## 2. Primitives [B+C]

Little-endian throughout (`BinaryWriter` via `ZPackage`).

| Name | Encoding |
|------|----------|
| `i32 / i64 / f32` | 4 / 8 / 4 bytes LE |
| `u16 / u8` | 2 / 1 bytes |
| `bool` | 1 byte (0/1) |
| `vec3` | 3 × f32 |
| `string` | .NET 7-bit varint byte length + UTF-8 |
| `bytes` | i32 length + raw bytes |
| `numItems` | 1 byte if < 128; else 2 bytes: high byte `(n >> 8)` with bit 0x80 set, then `n & 0xFF` (max 32767) |
| `dict<string,f32>` | i32 count, count × (string, f32) |

## 3. Container [B+C]

```
i32    payloadLength
byte   payload[payloadLength]
i32    hashLength          (64)
byte   hash[64]            SHA-512(payload)
```

- No compression or encryption at this level.
- **The game does not verify the hash on load** (it reads and discards it). The editor still recomputes it.
- The game writes `<name>.fch.new`, then rotates: previous file → `<name>.fch.old`, `.new` → `.fch`.
- Load errors are swallowed: a malformed payload loads *partially* instead of failing. The editor's own
  validation is therefore the only guard against corruption.

## 4. Profile payload (v46) [B+C]

| Field | Type | Notes |
|-------|------|-------|
| version | i32 | 46 |
| statCount | i32 | 205 (`PlayerStatType` values) |
| statBlockCount | i32 | 10 (`DifficultyRequirement` values) |
| statBlocks | 10 × StatBlock | see 4.1 |
| firstSpawn | bool | |
| worldCount | i32 | |
| worlds | worldCount × WorldData | see 4.2 |
| playerName | string | display name; file name on disk is separate |
| playerId | i64 | also used as item crafterId |
| startSeed | string | |
| usedCheats | bool | |
| dateCreated | i64 | Unix seconds; game keeps date only (local midnight) |
| hasPlayerData | bool | |
| playerData | bytes | present if hasPlayerData; see §5 |

### 4.1 StatBlock [B+C]

Block index = `DifficultyRequirement`: 0 RawStats, 1 Any, 2 Hammer, 3 Casual, 4 VeryEasy, 5 Easy, 6 Default,
7 Hard, 8 VeryHard, 9 Hardcore. The game updates block 0 and the block of the world's combat difficulty.

```
f32               stats[statCount]          index = PlayerStatType (Appendix A)
dict<string,f32>  knownWorlds               world name → seconds played
dict<string,f32>  knownWorldKeys            "<globalkey> <value|default>" → seconds
dict<string,f32>  knownCommands
i32               enemyStatCount            always 5
dict<string,f32>  enemyStats[enemyStatCount]
dict<string,f32>  itemPickupStats
dict<string,f32>  itemCraftStats
dict<string,f32>  pickableStats
dict<string,f32>  foodEatenStats
dict<string,f32>  piecesPlacedStats
```

### 4.2 WorldData [B+C]

```
i64 worldUid
bool haveCustomSpawn; vec3 spawnPoint
bool haveLogout;      vec3 logoutPoint
bool haveDeath;       vec3 deathPoint
vec3 homePoint
bool hasMap; if hasMap: bytes mapData      (§7)
```

## 5. Player data blob (v33) [B+C]

| Field | Type | Notes |
|-------|------|-------|
| version | i32 | 33 |
| maxHealth | f32 | |
| health | f32 | on load, ≤0 / >max / NaN → reset to max |
| maxStamina | f32 | also initial stamina on load |
| timeSinceDeath | f32 | |
| guardianPower | string | power name, "" = none |
| guardianPowerCooldown | f32 | seconds |
| inventory | Inventory | §6 |
| knownRecipes | i32 + string[] | |
| knownStations | i32 + (string, i32 level)[] | |
| knownMaterials | i32 + string[] | |
| shownTutorials | i32 + string[] | |
| uniques | i32 + string[] | includes `invrows N` (inventory height) |
| trophies | i32 + string[] | |
| knownBiomes | i32 + string[] | names (were int enum before v33) |
| knownTexts | i32 + (string, string)[] | game strips U+0016 (SYN) on save |
| beard | string | prefab name, e.g. `BeardNone` |
| hair | string | prefab name, e.g. `Hair24` |
| skinColor | vec3 | |
| hairColor | vec3 | |
| modelIndex | i32 | body type |
| foods | i32 + (string name, f32 time)[] | **[C]** (empty in sample) |
| skills | Skills | §5.1 |
| customData | i32 + (string, string)[] | **[C]** (empty in sample) |
| stamina | f32 | clamped to [0, maxStamina] on load |
| maxEitr | f32 | |
| eitr | f32 | clamped to [0, maxEitr] on load |
| buildUiState | bytes | opaque: build menu recent/favorite pieces; game resets it if unparseable |

### 5.1 Skills [B+C]

```
i32 skillsVersion (2); i32 count
count × (i32 skillType, f32 level, f32 accumulator)
```

- The game caps level at 100 (`c_MaxSkillLevel`) when raising skills, but does **not** clamp on load.
- Unknown skill types are ignored on load.
- SkillType: 1 Swords, 2 Knives, 3 Clubs, 4 Polearms, 5 Spears, 6 Blocking, 7 Axes, 8 Bows, 9 ElementalMagic,
  10 BloodMagic, 11 Unarmed, 12 Pickaxes, 13 WoodCutting, 14 Crossbows, 100 Jump, 101 Sneak, 102 Run,
  103 Swim, 104 Fishing, 105 Cooking, 106 Farming, 107 Crafting, 108 Dodge, 110 Ride.
- Levels above 100 are valid: the game stores and displays them. Only progression stops at 100, and the
  gameplay effect is clamped at 100 (`GetSkillFactor`). The sample has Crafting 1000 and Sneak 700.
  The editor accepts any finite level ≥ 0 and imposes **no upper limit** (user decision 2026-09-11).

## 6. Inventory (v109) [B+C]

```
i32 inventoryVersion (109)
u16 itemCount
itemCount × ItemRecord
```

ItemRecord:

| Field | Type | Present when |
|-------|------|--------------|
| durabilityX100 | i32 | always; `(int)(durability * 100f)`, truncated |
| gridX, gridY | u8, u8 | always |
| worldLevel | u8 | always |
| flags | u8 | always |
| quality | u16 | `flags & 0x04` (quality ≠ 1) |
| stack | u16 | `flags & 0x08` (stack ≠ 1) |
| variant | i32 | `flags & 0x10` (variant ≠ 0) |
| crafterId, crafterName | i64, string | `flags & 0x20` (crafterId ≠ 0) |
| prefabHash | i32 | `flags & 0x40` (prefab known) |
| customData | numItems + (string, string)[] | `flags & 0x80` |
| extraFlags | u8 | always (v109+); bit 0 = cheated |

Flag bits: `0x01` pickedUp · `0x02` equipped · `0x04` quality · `0x08` stack · `0x10` variant · `0x20` crafter ·
`0x40` prefab · `0x80` customData. All 8 bits are defined, so there are no unknown bits in v109. Unknown
`extraFlags` bits must still be preserved.

- **Item identity** is `GetStableHashCode(prefabName)`. There are no names in the file.
- The loader skips records with hash 0 or a hash that is not a known prefab. An invalid hash therefore
  deletes the item on the next game save.
- **Grid**: width 8; height from unique `invrows N` (clamped 0–9, default 4). The game drops items outside
  the grid.
- Max stack and max durability live in prefab data, not in the save or `assembly_valheim.dll`.

### 6.1 Stable hash [C, verified on 17 sample items]

```
a = b = 5381                                  # int32 arithmetic with wrap-around
for i in 0, 2, 4, ... while i < len and s[i] != '\0':
    a = ((a << 5) + a) ^ s[i]
    if i == len-1 or s[i+1] == '\0': break
    b = ((b << 5) + b) ^ s[i+1]
return a + b * 1566083941
```

`s[i]` are **UTF-16 code units** (C# `char`). Prefab names are ASCII in practice.

## 7. Map data (v8) [B+C]

```
i32 mapVersion (8)
bytes gzipInner              gzip, .NET GZipStream CompressionLevel.Fastest
inner:
  i32 textureSize            must equal the game's minimap size (2048), else the load throws
  u8  explored[size*size]
  u8  exploredShared[size*size]
  i32 pinCount
  pinCount × (string name, vec3 pos, i32 type, bool checked, i64 ownerId, string author)
  bool publicReferencePosition
```

Re-compressing with another gzip implementation gives different bytes that are still valid. The editor keeps
the original blob unless the map is edited.

## 8. Differences vs pre-1.0 formats (e.g. VPE-era, profile ≤ 43)

- Items: string names and fixed fields → hash + flag-driven compact records (item v108+).
- Stats: a single stats array (v38+) → 10 difficulty-scoped blocks with 13 dicts each (v46).
- firstSpawn moved from the player blob to the profile (v40 / playerData v28).
- Known biomes: int → string (playerData v33).
- New trailing `buildUiState` bytes (playerData v33).

## Appendix A: PlayerStatType (index → name)

0 Deaths, 1 CraftsOrUpgrades, 2 Builds, 3 Jumps, 4 Cheats, 5 EnemyHits, 6 EnemyKills, 7 EnemyKillsLastHits,
8 PlayerHits, 9 PlayerKills, 10 HitsTakenEnemies, 11 HitsTakenPlayers, 12 ItemsPickedUp, 13 Crafts,
14 Upgrades, 15 PortalsUsed, 16 DistanceTraveled, 17 DistanceWalk, 18 DistanceRun, 19 DistanceSail,
20 DistanceAir, 21 TimeInBase, 22 TimeOutOfBase, 23 Sleep, 24 ItemStandUses, 25 ArmorStandUses,
26 WorldLoads, 27 TreeChops, 28 Tree, 29–34 TreeTier0–5, 35 LogChops, 36 Logs, 37 MineHits, 38 Mines,
39–44 MineTier0–5, 45 RavenHits, 46 RavenTalk, 47 RavenAppear, 48 CreatureTamed, 49 FoodEaten,
50 SkeletonSummons, 51 ArrowsShot, 52 TombstonesOpenedOwn, 53 TombstonesOpenedOther, 54 TombstonesFit,
55 DeathByUndefined, 56 DeathByEnemyHit, 57 DeathByPlayerHit, 58 DeathByFall, 59 DeathByDrowning,
60 DeathByBurning, 61 DeathByFreezing, 62 DeathByPoisoned, 63 DeathBySmoke, 64 DeathByWater,
65 DeathByEdgeOfWorld, 66 DeathByImpact, 67 DeathByCart, 68 DeathByTree, 69 DeathBySelf,
70 DeathByStructural, 71 DeathByTurret, 72 DeathByBoat, 73 DeathByStalagtite, 74 DoorsOpened,
75 DoorsClosed, 76 BeesHarvested, 77 SapHarvested, 78 TurretAmmoAdded, 79 TurretTrophySet, 80 TrapArmed,
81 TrapTriggered, 82 PlaceStacks, 83 PortalDungeonIn, 84 PortalDungeonOut, 85 BossKills, 86 BossLastHits,
87 SetGuardianPower, 88 SetPowerEikthyr, 89 SetPowerElder, 90 SetPowerBonemass, 91 SetPowerModer,
92 SetPowerYagluth, 93 SetPowerQueen, 94 SetPowerAshlands, 95 SetPowerDeepNorth, 96 UseGuardianPower,
97 UsePowerEikthyr, 98 UsePowerElder, 99 UsePowerBonemass, 100 UsePowerModer, 101 UsePowerYagluth,
102 UsePowerQueen, 103 UsePowerAshlands, 104 UsePowerDeepNorth, 105 DeathByCatapult, 106 DeathByCinderFire,
107 DeathByAshlandsOcean, 108 DeathByIncinerator, 109 CraftFood, 110 CraftFoodBonus, 111 CraftGrill,
112 CraftGrillBurnt, 113 CraftGrillBonus, 114 CraftWeapon, 115 CraftArmor, 116 CraftTrinket, 117 CraftAmmo,
118 CraftMaterial, 119 CraftTool, 120 CraftTorch, 121 CraftBait, 122 CraftOther, 123 HarvestCrop,
124 HarvestBerry, 125 HarvestMushroom, 126 HarvestVine, 127 HarvestBonus, 128 ConsecutiveDaysSurvived,
129 ConsecutiveDaysSurvivedMax, 130 MaxBuildingHeight, 131 MaxBuildingHeightWorld, 132 MaxComfort,
133 TreasureBuriedFound, 134 TreasureDungeonFound, 135 TreasureLocationFound, 136 LeviathanSink,
137 LavaLeviathanSink, 138 ExploreNorth, 139 ExploreSouth, 140 ExploreEast, 141 ExploreWest,
142 ExploreNorthNoMap, 143 ExploreSouthNoMap, 144 ExploreEastNoMap, 145 ExploreWestNoMap,
146 BossKillMultiplayer, 147 BossKillSolo, 148 VillagePointsMax, 149 DeepestDungeon, 150 DistanceSailHelm,
151 PlayerSpawn, 152–157 DeathByTreeTier0–5, 158 FishHooked, 159 FishLost, 160 FishCaught,
161–167 FishCaughtTier0–6, 168 BuiltPieces, 169 BuiltPiecesNoDebt, 170 BuildPiecesRemoved,
171 BuildClusterMisc, 172 BuildClusterCrafting, 173 BuildClusterBuilding, 174 BuildClusterFloor,
175 BuildClusterWall, 176 BuildClusterRoof, 177 BuildClusterArchitecture, 178 BuildClusterFurniture,
179 BuildClusterLighting, 180 BuildClusterDecor, 181 BuildClusterStorage, 182 BuildClusterTransport,
183 BuildClusterFood, 184 BuildClusterMeads, 185 BuildClusterFeasts, 186 BuildClusterDefense,
187 BuildClusterStacks, 188 BuildClusterStairs, 189 BuildClusterDoors, 190 BuildClusterSeasonal,
191 TamedPetting, 192 TamedCommand, 193 TreeFir, 194 TreeOak, 195 TreePine, 196 TreeAshlands,
197 TreeYggdrasilShoot, 198 TreeSwamp, 199 TreeBeech, 200 TreeBirch, 201 TreeSnowFir, 202 TreeSnowPine,
203 DeathByDrawBridge, 204 DeathByAshlandsLava.
