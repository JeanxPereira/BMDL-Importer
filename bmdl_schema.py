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

STRUCTS["TbmdlRoot"] = {"stride": 16, "fields": [
    ("model_ptr", 0, "ptr"), ("skeleton_ptr", 4, "ptr"),
    ("num_anims", 8, "i32"), ("anims_ptr", 12, "ptr")]}

STRUCTS["Skeleton"] = {"stride": 8, "fields": [
    ("num_bones", 0, "i32"), ("bones_ptr", 4, "ptr")]}

STRUCTS["Bone"] = {"stride": 80, "fields": [
    ("name_ptr", 0, "cstr"), ("name_hash", 4, "u32"), ("parent_index", 8, "i32"),
    ("pad", 12, "u32"), ("inv_bind", 16, "f32x16")]}

STRUCTS["AnimHeader"] = {"stride": 20, "fields": [
    ("name_ptr", 0, "cstr"), ("name_hash", 4, "u32"), ("duration", 8, "f32"),
    ("num_tracks", 12, "u32"), ("tracks_ptr", 16, "ptr")]}

STRUCTS["AnimTrack"] = {"stride": 20, "fields": [
    ("bone_index", 0, "i32"), ("category", 4, "u32"), ("num_keys", 8, "u32"),
    ("times_ptr", 12, "ptr"), ("values_ptr", 16, "ptr")]}
# category: 1=POS(dim3) 2=ROT(dim4 quaternion xyzw) 3=SCALE(dim3)

STRUCTS["Material"] = {"stride": 44, "fields": [
    ("name_ptr", 0, "cstr"), ("name_hash", 4, "u32"), ("flags", 8, "u32"),
    ("num_params", 12, "i32"), ("params_ptr", 16, "ptr"),
    ("num_floats", 20, "i32"), ("floats_ptr", 24, "ptr"),
    ("num_textures", 28, "i32"), ("textures_ptr", 32, "ptr"),
    ("num_streams", 36, "i32"), ("streams_ptr", 40, "ptr")]}

STRUCTS["MatParam"] = {"stride": 16, "fields": [
    ("name_ptr", 0, "cstr"), ("name_hash", 4, "u32"),
    ("float_offset", 8, "u32"), ("dimension", 12, "u32")]}

STRUCTS["TexBinding"] = {"stride": 16, "fields": [
    ("key_ptr", 0, "cstr"), ("key_hash", 4, "u32"),
    ("value_ptr", 8, "cstr"), ("value_hash", 12, "u32")]}

STRUCTS["Model"] = {"stride": 0x48, "fields": [
    ("name_ptr", 0x20, "cstr"),
    ("num_materials", 0x28, "i32"), ("materials_ptr", 0x2c, "ptr"),
    ("num_meshes", 0x30, "i32"), ("meshes_ptr", 0x34, "ptr"),
    ("num_instances", 0x38, "i32"), ("instances_ptr", 0x3c, "ptr"),
    ("num_tags", 0x40, "i32"), ("tags_ptr", 0x44, "ptr")]}

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
