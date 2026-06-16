"""Standalone (no bpy/mathutils) declarative layout of the Darkspore .bmdl container.
Single source of truth: the importer (Phase 2) and tools/validate_bmdl.py both read this.

ctype vocabulary:
  u8 u16 u32 i32 f32   - primitives (little-endian)
  ptr                  - u32 graph-relative offset (0 = null)
  cstr                 - u32 graph-relative offset to a NUL-terminated ASCII string
  f32x16               - 16 contiguous float32 (a 4x4 matrix)
A struct def is {"stride": int, "fields": [(name, offset, ctype), ...]}.
"""
import struct

_PRIM = {"u8": ("<B", 1), "u16": ("<H", 2), "u32": ("<I", 4),
         "i32": ("<i", 4), "f32": ("<f", 4), "ptr": ("<I", 4)}

STRUCTS = {}   # filled by later tasks

class Reader:
    def __init__(self, data):
        if data[4:8] != b"bmdl" or struct.unpack_from("<I", data, 8)[0] != 2:
            raise ValueError("not a bmdl v2 file")
        self.d = data
        self.base = struct.unpack_from("<I", data, 12)[0]
        self.graph_size = struct.unpack_from("<I", data, 16)[0]
        self.limit = self.base + self.graph_size

    def _abs(self, graphrel):
        return self.base + graphrel

    def cstr(self, graphrel):
        if not (0 < graphrel < self.graph_size):
            return None
        o = self._abs(graphrel)
        e = o
        while e < len(self.d) and self.d[e] != 0:
            e += 1
        return self.d[o:e].decode("ascii", "ignore")

    def field(self, ctype, abs_off):
        if ctype == "cstr":
            rel = struct.unpack_from("<I", self.d, abs_off)[0]
            return self.cstr(rel)
        if ctype == "f32x16":
            return struct.unpack_from("<16f", self.d, abs_off)
        fmt, _ = _PRIM[ctype]
        return struct.unpack_from(fmt, self.d, abs_off)[0]

    def read(self, struct_name, graphrel):
        """Parse one struct instance at a graph-relative pointer -> dict."""
        sd = STRUCTS[struct_name]
        o = self._abs(graphrel)
        if o + sd["stride"] > self.limit:
            raise ValueError(f"{struct_name} @ {graphrel} overruns graph")
        out = {}
        for name, off, ctype in sd["fields"]:
            out[name] = self.field(ctype, o + off)
        return out

    def read_array(self, struct_name, graphrel, count):
        sd = STRUCTS[struct_name]
        return [self.read(struct_name, graphrel + i * sd["stride"]) for i in range(max(0, count))]

    def in_range(self, graphrel):
        return 0 <= graphrel < self.graph_size
