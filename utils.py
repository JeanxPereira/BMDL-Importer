from bpy_extras.io_utils import axis_conversion

def make_axis_m3(convert_axes, axis_forward, axis_up):
    if not convert_axes:
        return None
    return axis_conversion(from_forward=axis_forward, from_up=axis_up).to_3x3()

# --- Darkspore FNV-1 (32-bit) string hash ---
# mode: 0 = direct, 1 = lowercase-normalized, 2 = uppercase-normalized
def _ds_lookup_tables():
    lower = list(range(256))
    upper = list(range(256))
    for i in range(256):
        # 'A'..'Z' -> 'a'..'z'
        lower[i] = i + 32 if 65 <= i <= 90 else i
        # 'a'..'z' -> 'A'..'Z'
        upper[i] = i - 32 if 97 <= i <= 122 else i
    return lower, upper

_LOWER_TABLE, _UPPER_TABLE = _ds_lookup_tables()

def darkspore_hash(text: str, initial_value: int = 0x811C9DC5, mode: int = 1) -> int:
    """
    Compute the 32-bit FNV-1 hash used by Darkspore.

    Args:
        text: Input string (usually the filename stem without extension).
        initial_value: FNV offset basis (defaults to 0x811C9DC5).
        mode: 0 = direct bytes, 1 = lowercase normalization, 2 = uppercase normalization.

    Returns:
        Unsigned 32-bit integer hash.
    """
    h = initial_value & 0xFFFFFFFF
    for ch in text:
        b = ord(ch)
        if mode == 1:
            b = _LOWER_TABLE[b]
        elif mode == 2:
            b = _UPPER_TABLE[b]
        h = ((h * 16777619) & 0xFFFFFFFF) ^ b
    return h

def darkspore_hash_le_bytes(text: str, initial_value: int = 0x811C9DC5, mode: int = 1) -> bytes:
    """Return the hash as 4 little-endian bytes."""
    return darkspore_hash(text, initial_value, mode).to_bytes(4, "little", signed=False)
