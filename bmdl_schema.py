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

# --- Geometry (RE-confirmed in BinaryModel::ReadResourceModel @ 004a9220) ---
# Mesh array: Model.meshes_ptr, Model.num_meshes entries, stride 0x44 (loop `byteOff += 0x44`).
# First 0x20 bytes are a bounding box (8 floats: min[3], pad, max[3], pad/volume) — not used here.
# +0x30 vdecl_ptr -> 0xFF-terminated array of 8-byte vertex-decl elements (see read_vdecl).
# +0x34 vb_data_ptr (raw VB bytes), +0x38 ib_data_ptr (16-bit indices),
# +0x3c vertex_count, +0x40 index_count.
# CreateVertexBuffer(decl, vertex_count); CreateIndexBuffer(.,2,index_count,.,.); ib memcpy = index_count*2 (16-bit).
STRUCTS["Mesh"] = {"stride": 0x44, "fields": [
    ("name_ptr", 0x20, "cstr"), ("flags", 0x2c, "u32"),
    ("vdecl_ptr", 0x30, "ptr"), ("vb_data_ptr", 0x34, "ptr"), ("ib_data_ptr", 0x38, "ptr"),
    ("vertex_count", 0x3c, "u32"), ("index_count", 0x40, "u32")]}

# Instance/LOD array: Model.instances_ptr, Model.num_instances entries, stride 0x2c (loop `byteOff += 0x24`
# on the smaller GPU-side copy; source stride is 0x2c, confirmed by LayoutBuilder AddField `byteOff += 0x2c`).
# First 0x18 bytes = bbox (6 floats). +0x20 mesh_index (u32, selects which Mesh's VB/IB this LOD draws),
# +0x24 num_renderables, +0x28 renderables_ptr.
STRUCTS["Instance"] = {"stride": 0x2c, "fields": [
    ("mesh_index", 0x20, "u32"),
    ("num_renderables", 0x24, "i32"), ("renderables_ptr", 0x28, "ptr")]}

# Renderable (sub-draw) array: Instance.renderables_ptr, Instance.num_renderables entries, stride 0x2c
# (loop `subSrcByteOff += 0x2c`). First 0x18 = bbox (6 floats).
# +0x20 material_index (i32; engine does material_index * 0x30 + materials_base),
# +0x24 index_start (offset into the owning mesh's 16-bit index buffer),
# +0x28 index_count. start+count partitions the mesh's index_count (measured on scaldron).
STRUCTS["Renderable"] = {"stride": 0x2c, "fields": [
    ("material_index", 0x20, "i32"),
    ("index_start", 0x24, "u32"), ("index_count", 0x28, "u32")]}


def read_vdecl(r, graphrel):
    """Walk the 0xFF-terminated vertex-declaration array at a graph-relative ptr.
    Each element is 8 bytes; the list terminates at an element whose stream (u16 @0) == 0xFF.

    On-disk element layout (confirmed in 004a9220, asm @004a9d0e/004a9da7/004a9e09/004a9e26):
      @0 stream    : u16   (0xFFFF/0xFF == terminator; `CMP word ptr [EAX], 0xff`)
      @2 offset    : u16   (byte offset of this element within the vertex)
      @4 d3d_usage : u8    (copied verbatim to the D3DVERTEXELEMENT9.Usage slot, decl+4)
      @5           : u8    (unused / padding)
      @6 type_id   : u8    (switch selector -> D3DDECLTYPE, written to decl+8)
      @7 usage_idx : u8    (copied verbatim to D3DVERTEXELEMENT9.UsageIndex, decl+7)
    type_id -> D3DDECLTYPE (from the switch at 004a9db1):
      0->0x00 FLOAT1   1->0x02 FLOAT3   2->0x13 (19)   3->0x14 (20)
      4->0x06 UBYTE4   5->0x03 FLOAT4   6->0x0F        7->0x0E   default->0xFFFFFFFF UNUSED
    Returns a list of element dicts; raises ValueError if it runs off the graph
    or fails to terminate within a sane bound."""
    elems = []
    o = r._abs(graphrel)
    if not r.in_range(graphrel):
        raise ValueError(f"vdecl_ptr {graphrel} out of range")
    for _ in range(256):
        if o + 8 > r.limit:
            raise ValueError(f"vdecl @ {graphrel} overruns graph before terminator")
        stream = struct.unpack_from("<H", r.d, o)[0]
        if stream == 0xFF:
            return elems
        elems.append({
            "stream": stream,
            "offset": struct.unpack_from("<H", r.d, o + 2)[0],
            "d3d_usage": r.d[o + 4],
            "type_id": r.d[o + 6],
            "usage_index": r.d[o + 7],
        })
        o += 8
    raise ValueError(f"vdecl @ {graphrel} did not terminate within 256 elements")

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
