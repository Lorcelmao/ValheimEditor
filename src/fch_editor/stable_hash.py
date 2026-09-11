"""Port of Valheim's string.GetStableHashCode(), used as item prefab identity."""


def _i32(x: int) -> int:
    x &= 0xFFFFFFFF
    return x - 0x1_0000_0000 if x & 0x8000_0000 else x


def stable_hash(name: str) -> int:
    """Return the signed 32-bit hash the game stores for a prefab name.

    Iterates UTF-16 code units like the C# original and stops at the first NUL.
    """
    raw = name.encode("utf-16-le")
    units = [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]
    a = b = 5381
    i = 0
    while i < len(units) and units[i] != 0:
        a = _i32(((a << 5) + a) ^ units[i])
        if i == len(units) - 1 or units[i + 1] == 0:
            break
        b = _i32(((b << 5) + b) ^ units[i + 1])
        i += 2
    return _i32(a + b * 1566083941)
