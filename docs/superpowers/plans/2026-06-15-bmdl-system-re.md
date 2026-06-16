# BMDL System Reverse Engineering — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover the full `.bmdl` load layout from Ghidra and capture it as a single standalone struct schema, proven by a validator that parses the whole local corpus with zero heuristics/errors, plus derived docs and Ghidra annotations. No importer behaviour change.

**Architecture:** A pure-Python `bmdl_schema.py` (no `bpy`/`mathutils`) holds declarative struct definitions plus a tiny reader engine. A standalone `tools/validate_bmdl.py` parses every `.bmdl` via the schema and asserts structural invariants — this is the empirical "100% certain" gate. Structs are added bottom-up from the real load code (`LoadAsset` → `ReadResourceModel`), each confirmed `[binary]` (Ghidra) + `[measured]` (bytes) + `[sweep]` (validator) before moving on. Docs (`docs/BMDL_FORMAT.md`) and Ghidra annotations are derived from the verified schema.

**Tech Stack:** Python 3 (stdlib `struct` only), Ghidra MCP for RE, the local corpus at `C:\CodingProjects\Personal\Darkspore\Data\BMDL_environments` (~1234 `.bmdl`).

---

## Conventions for every task

- **Corpus path:** `C:/CodingProjects/Personal/Darkspore/Data/BMDL_environments`.
- **Run the validator** with the system Python (NOT Blender's): `python tools/validate_bmdl.py <corpus>`.
- `[binary]` = read in the Ghidra decompilation; `[measured]` = matches real bytes of ≥1 file; `[sweep]` = validator passes on the corpus.
- A field is only added to the schema once it is `[binary]` + `[measured]`. If a struct cannot be exercised by any local file, tag it `[binary-only]` in the docs and exclude it from the validator's hard assertions.
- Commit after each task. Commit messages in English, no co-author.

---

## File structure

- Create: `bmdl_schema.py` — type system, `Reader` engine, `STRUCTS` declarations. Pure stdlib, importable outside Blender. Single source of truth for the load layout.
- Create: `tools/validate_bmdl.py` — standalone sweep validator + coverage report. Imports `bmdl_schema`.
- Create: `docs/BMDL_FORMAT.md` — master spec, derived from the verified schema.
- Modify: `docs/BMDL_ANIMATION.md`, `docs/BMDL_MATERIALS.md` — add a cross-link to the master spec and a note that the layouts now live in `bmdl_schema.py`.
- Ghidra (no repo files): structs/function names/plate comments via the Ghidra MCP.

`bmdl_core.py` (the importer's existing parser, which imports `mathutils`) is **not modified** in Phase 1; the standalone schema supersedes it in Phase 2.

---

## Task 1: Schema engine + validator harness (scaffolding)

**Files:**
- Create: `bmdl_schema.py`
- Create: `tools/validate_bmdl.py`

- [ ] **Step 1: Create `bmdl_schema.py` with the type system, Reader, and an empty STRUCTS**

```python
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
```

- [ ] **Step 2: Create `tools/validate_bmdl.py` (header-only sweep first)**

```python
"""Standalone validator: parse every .bmdl via bmdl_schema and assert structural
invariants. Run: python tools/validate_bmdl.py <dir>. Exit 0 iff all files pass."""
import os, sys, glob, struct
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bmdl_schema as S

def validate_file(path):
    data = open(path, "rb").read()
    problems = []
    try:
        r = S.Reader(data)
    except Exception as e:
        return [f"header: {e}"], {}
    seen = {}
    # later tasks extend this with: walk(r, seen, problems)
    if WALK:
        WALK(r, seen, problems)
    return problems, seen

WALK = None   # set by later tasks

def main(root):
    files = glob.glob(os.path.join(root, "**", "*.bmdl"), recursive=True)
    ok = bad = 0
    agg = {}
    for f in files:
        problems, seen = validate_file(f)
        for k, v in seen.items():
            agg[k] = agg.get(k, 0) + v
        if problems:
            bad += 1
            if bad <= 30:
                print(f"FAIL {os.path.relpath(f, root)}: {problems[0]}")
        else:
            ok += 1
    print(f"\nfiles={len(files)} ok={ok} fail={bad}")
    print("struct coverage:", {k: agg[k] for k in sorted(agg)})
    return 0 if bad == 0 else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
```

- [ ] **Step 3: Run the harness to confirm it loads the corpus**

Run: `python tools/validate_bmdl.py "C:/CodingProjects/Personal/Darkspore/Data/BMDL_environments"`
Expected: prints `files=1234 ok=... fail=...` where failures are only non-v2/odd files (header check). No Python tracebacks.

- [ ] **Step 4: Commit**

```bash
git add bmdl_schema.py tools/validate_bmdl.py
git commit -m "feat(re): standalone bmdl schema engine + validator harness"
```

---

## Task 2: Root + skeleton + bone (already confirmed structs)

**Files:**
- Modify: `bmdl_schema.py` (add structs)
- Modify: `tools/validate_bmdl.py` (add `walk` + set `WALK`)

These layouts are already confirmed `[binary]` (`ReadResourceModel`) + `[measured]` (`creatureeditor_el_anime_arm.bmdl`) earlier in the project; this task records them and gates them on the sweep.

- [ ] **Step 1: Add the structs to `STRUCTS` in `bmdl_schema.py`**

```python
STRUCTS["TbmdlRoot"] = {"stride": 16, "fields": [
    ("model_ptr", 0, "ptr"), ("skeleton_ptr", 4, "ptr"),
    ("num_anims", 8, "i32"), ("anims_ptr", 12, "ptr")]}

STRUCTS["Skeleton"] = {"stride": 8, "fields": [
    ("num_bones", 0, "i32"), ("bones_ptr", 4, "ptr")]}

STRUCTS["Bone"] = {"stride": 80, "fields": [
    ("name_ptr", 0, "cstr"), ("name_hash", 4, "u32"), ("parent_index", 8, "i32"),
    ("pad", 12, "u32"), ("inv_bind", 16, "f32x16")]}
```

- [ ] **Step 2: Add the `walk` function to `tools/validate_bmdl.py` and wire `WALK`**

Replace `WALK = None` with:

```python
def walk(r, seen, problems):
    def bump(name): seen[name] = seen.get(name, 0) + 1
    root = r.read("TbmdlRoot", 0); bump("TbmdlRoot")
    # skeleton
    sk = root["skeleton_ptr"]
    if sk:
        if not r.in_range(sk): problems.append(f"skeleton_ptr {sk} oor")
        else:
            skel = r.read("Skeleton", sk); bump("Skeleton")
            n, bp = skel["num_bones"], skel["bones_ptr"]
            if 0 < n < 4096 and r.in_range(bp):
                for b in r.read_array("Bone", bp, n):
                    bump("Bone")
                    if b["parent_index"] < -1 or b["parent_index"] >= n:
                        problems.append(f"bone parent {b['parent_index']} oor")

WALK = walk
```

- [ ] **Step 3: Run the validator**

Run: `python tools/validate_bmdl.py "C:/CodingProjects/Personal/Darkspore/Data/BMDL_environments"`
Expected: `fail=0` for all files that have a skeleton; `struct coverage` shows non-zero `Bone`/`Skeleton` counts. Investigate and fix any FAIL line (a real FAIL means a wrong offset/stride).

- [ ] **Step 4: Commit**

```bash
git add bmdl_schema.py tools/validate_bmdl.py
git commit -m "feat(re): root/skeleton/bone structs in schema, validated on corpus"
```

---

## Task 3: Animations (header + track) + contiguity invariant

**Files:**
- Modify: `bmdl_schema.py`
- Modify: `tools/validate_bmdl.py`

Confirmed earlier `[measured]` across 70 tracks × 4 anims; record + gate.

- [ ] **Step 1: Add anim structs**

```python
STRUCTS["AnimHeader"] = {"stride": 20, "fields": [
    ("name_ptr", 0, "cstr"), ("name_hash", 4, "u32"), ("duration", 8, "f32"),
    ("num_tracks", 12, "u32"), ("tracks_ptr", 16, "ptr")]}

STRUCTS["AnimTrack"] = {"stride": 20, "fields": [
    ("bone_index", 0, "i32"), ("category", 4, "u32"), ("num_keys", 8, "u32"),
    ("times_ptr", 12, "ptr"), ("values_ptr", 16, "ptr")]}
# category: 1=POS(dim3) 2=ROT(dim4 quaternion xyzw) 3=SCALE(dim3)
```

- [ ] **Step 2: Extend `walk` with anims + the contiguity check**

Inside `walk`, after the skeleton block, add:

```python
    na, ap = root["num_anims"], root["anims_ptr"]
    dims = {1: 3, 2: 4, 3: 3}
    if 0 < na < 4096 and r.in_range(ap):
        for h in r.read_array("AnimHeader", ap, na):
            bump("AnimHeader")
            nt, tp = h["num_tracks"], h["tracks_ptr"]
            if not (0 < nt < 65536 and r.in_range(tp)):
                continue
            for t in r.read_array("AnimTrack", tp, nt):
                bump("AnimTrack")
                nk, tpt, vpt = t["num_keys"], t["times_ptr"], t["values_ptr"]
                if nk == 0:
                    continue
                # invariant: times[] (num_keys floats) are immediately followed by values[]
                if vpt - tpt != nk * 4:
                    problems.append(f"track contiguity: vpt-tpt={vpt-tpt} != num_keys*4={nk*4}")
                if t["category"] not in dims:
                    problems.append(f"track category {t['category']} unknown")
```

- [ ] **Step 3: Run the validator**

Run: `python tools/validate_bmdl.py "C:/CodingProjects/Personal/Darkspore/Data/BMDL_environments"`
Expected: `fail=0`; coverage shows `AnimHeader`/`AnimTrack` counts. Any contiguity/category FAIL is a real finding — investigate in Ghidra before assuming.

- [ ] **Step 4: Commit**

```bash
git add bmdl_schema.py tools/validate_bmdl.py
git commit -m "feat(re): anim header/track structs + contiguity invariant, validated"
```

---

## Task 4: Model + material structs (already confirmed)

**Files:**
- Modify: `bmdl_schema.py`
- Modify: `tools/validate_bmdl.py`

`bmdl_Material`/`MatParam`/`TexBinding` are confirmed `[binary]` (`ReadResourceModel`/`ApplyMaterialParams`) + `[measured]`.

- [ ] **Step 1: Add structs**

```python
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

# The model struct header: ptr fields read by ReadResourceModel as src[...]:
# name@0x20, num_materials@0x28, materials_ptr@0x2c, num_meshes@0x30, meshes_ptr@0x34,
# num_instances@0x38, instances_ptr@0x3c, num_tags@0x40, tags_ptr@0x44.
STRUCTS["Model"] = {"stride": 0x48, "fields": [
    ("name_ptr", 0x20, "cstr"),
    ("num_materials", 0x28, "i32"), ("materials_ptr", 0x2c, "ptr"),
    ("num_meshes", 0x30, "i32"), ("meshes_ptr", 0x34, "ptr"),
    ("num_instances", 0x38, "i32"), ("instances_ptr", 0x3c, "ptr"),
    ("num_tags", 0x40, "i32"), ("tags_ptr", 0x44, "ptr")]}
```

- [ ] **Step 2: Extend `walk` with model + materials**

Inside `walk`, after `root = r.read(...)`, add:

```python
    mp = root["model_ptr"]
    if mp and r.in_range(mp):
        mdl = r.read("Model", mp); bump("Model")
        nm, matp = mdl["num_materials"], mdl["materials_ptr"]
        if 0 < nm < 4096 and r.in_range(matp):
            for mat in r.read_array("Material", matp, nm):
                bump("Material")
                if mat["num_params"] > 0 and r.in_range(mat["params_ptr"]):
                    nf = mat["num_floats"]
                    for prm in r.read_array("MatParam", mat["params_ptr"], mat["num_params"]):
                        bump("MatParam")
                        if prm["float_offset"] + prm["dimension"] > nf:
                            problems.append(f"matparam slice {prm['float_offset']}+{prm['dimension']} > {nf}")
                for arr in ("textures", "streams"):
                    n = mat[f"num_{arr}"]; p = mat[f"{arr}_ptr"]
                    if n > 0 and r.in_range(p):
                        r.read_array("TexBinding", p, n); bump("TexBinding")
```

- [ ] **Step 3: Run the validator**

Run: `python tools/validate_bmdl.py "C:/CodingProjects/Personal/Darkspore/Data/BMDL_environments"`
Expected: `fail=0`; coverage shows `Model`/`Material`/`MatParam`/`TexBinding`. Fix any FAIL (real layout error).

- [ ] **Step 4: Commit**

```bash
git add bmdl_schema.py tools/validate_bmdl.py
git commit -m "feat(re): model/material/param/texbinding structs, validated"
```

---

## Task 5: bmdl v2 geometry — the gap (RE the exact mesh layout)

This replaces the importer's heuristics. The layout is currently only known approximately. RE it
exactly from `BinaryModel::ReadResourceModel @ 004a9220` (the mesh-copy loop that reads `src[0xd]`
entries) and the vertex-declaration walk.

**Files:**
- Modify: `bmdl_schema.py`
- Modify: `tools/validate_bmdl.py`

- [ ] **Step 1: RE the mesh entry struct in Ghidra**

Using the Ghidra MCP, re-read `ReadResourceModel @ 004a9220`, focusing on the loop guarded by
`if (0 < src[0xc])` (meshes). For each mesh entry it reads fields at `byteOff + src[0xd]`: name (+0x20),
flags (+0x2c), vdecl ptr (+0x30), vertex count (+0x3c), index ptr (+0x38), index count (+0x40),
vertex data ptr (+0x34). Record the exact offsets/types **as read in the decompilation** (`[binary]`)
and the mesh entry stride (the loop increment `byteOff += 0x44`). Cross-check each offset against the
bytes of `scaldron/scaldron_terrain_a.bmdl` (`[measured]`).

- [ ] **Step 2: RE the vertex-declaration element struct**

In the same function, the decl walk reads 8-byte elements: `stream:u16, offset:u16, type:u8, method:u8,
usage:u8, usage_index:u8`, terminated by `stream == 0xFF`. The `switch` on the element type maps the
on-disk type id to a D3D declaration type (0→FLOAT1.. case table). Record the type-id → meaning table
verbatim from the switch (`[binary]`).

- [ ] **Step 3: RE the instance + renderable structs**

Read the instances loop and the renderables it points to. Confirm the instance fields (imesh,
num_renderables, renderables_ptr) and the renderable fields (imat, start, count) and their strides,
exactly as the decompilation indexes them (`[binary]`); cross-check on `scaldron_terrain_a.bmdl`
(`[measured]`).

- [ ] **Step 4: Add the confirmed structs to `bmdl_schema.py`**

Add `Mesh`, `VDeclElem`, `Instance`, `Renderable` (and `CollisionMesh`/`Tag` if confirmed) using the
offsets/strides established in Steps 1–3. (Exact field lists are produced by the RE; do not invent
fields that are not read in the decompilation.) Add a small helper `read_vdecl(r, ptr)` that walks
8-byte elements until `stream == 0xFF`.

- [ ] **Step 5: Extend `walk` to parse meshes/vdecl/instances/renderables with invariants**

For each mesh: assert `vdecl_ptr`, `vb_ptr`, `ib_ptr` in range; assert the declaration terminates with
`0xFF` within the graph; assert the declared stride (pitch) is `> 0` and `% 4 == 0` and matches the sum
of declaration element sizes; for each renderable assert `start`/`count` reference index data inside
the graph and that all triangle indices are `< vertex_count`. These replace the old "score the index
mode" heuristic with hard checks.

- [ ] **Step 6: Run the validator on the full corpus**

Run: `python tools/validate_bmdl.py "C:/CodingProjects/Personal/Darkspore/Data/BMDL_environments"`
Expected: `fail=0` across all ~1234 files; coverage shows `Mesh`/`Instance`/`Renderable`. Every FAIL is
a misread field — return to Ghidra and correct before continuing. **Do not add a fallback to make it
pass.**

- [ ] **Step 7: Commit**

```bash
git add bmdl_schema.py tools/validate_bmdl.py
git commit -m "feat(re): exact bmdl v2 geometry layout (mesh/vdecl/instance/renderable), validated"
```

---

## Task 6: Full-corpus sweep gate

**Files:**
- Modify: `tools/validate_bmdl.py` (reporting only)

- [ ] **Step 1: Add a `--report` summary**

Add an optional second arg that, when present, also prints: total structs parsed, min/max counts per
struct, and the list of files (if any) that exercised zero meshes or zero anims (candidates that may
need other formats). No new assertions.

- [ ] **Step 2: Run the gate**

Run: `python tools/validate_bmdl.py "C:/CodingProjects/Personal/Darkspore/Data/BMDL_environments" --report`
Expected: `fail=0`. Capture the printed coverage numbers — they go into the doc.

- [ ] **Step 3: Commit**

```bash
git add tools/validate_bmdl.py
git commit -m "feat(re): validator coverage report; full corpus sweep is the gate"
```

---

## Task 7: Master document `docs/BMDL_FORMAT.md`

**Files:**
- Create: `docs/BMDL_FORMAT.md`
- Modify: `docs/BMDL_ANIMATION.md`, `docs/BMDL_MATERIALS.md` (cross-link)

- [ ] **Step 1: Write `docs/BMDL_FORMAT.md`**

Sections (English): (1) Container & header; (2) graph relocation (`BinaryBuffer::Relocate`);
(3) `LoadAsset` dispatch table (asset-type hash → loader) as a table + mermaid; (4) the bmdl v2
structure tree (mermaid) + a layout table for **every** struct now in `bmdl_schema.py`, each row tagged
`[measured]`/`[binary]`/`[sweep]`; (5) one subsection per alternative format (filled by Task 8);
(6) the corpus coverage numbers from Task 6. State that `bmdl_schema.py` is the source of truth and the
tables are checked against it.

- [ ] **Step 2: Cross-link the deep-dives**

Add to the top of `docs/BMDL_ANIMATION.md` and `docs/BMDL_MATERIALS.md`: a line linking to
`docs/BMDL_FORMAT.md` and noting that the struct layouts are defined in `bmdl_schema.py`.

- [ ] **Step 3: Commit**

```bash
git add docs/BMDL_FORMAT.md docs/BMDL_ANIMATION.md docs/BMDL_MATERIALS.md
git commit -m "docs: master BMDL_FORMAT.md derived from the validated schema"
```

---

## Task 8: Alternative formats (RE + document)

**Files:**
- Modify: `bmdl_schema.py` (structs where local files exist), `docs/BMDL_FORMAT.md`

- [ ] **Step 1: Map the dispatch branches in Ghidra**

From `LoadAsset @ 004aeea0`, list every asset-type branch and its loader:
`0x72047de2 ReadResourceModel`, `0xe6bce5 LoadGameModelVersioned`, `0x2f4e681c SP_RenderModel::Load`,
`0x2f7d0004 LoadStrided`, `0x17952e6c LoadSkinnedMesh`, `0x2cb4f2f LoadSkinData`,
`0x2f4e681b LoadPrefab`. Confirm each hash + target (`[binary]`).

- [ ] **Step 2: RE the GameModel versioned path**

Decompile `LoadGameModelVersioned @ 004aee10`, `FUN_004a47b0`, `FUN_004ae430`. Record the streamed
layout (it uses `BinaryReader` reads rather than relocation): index buffers, vertex declarations,
vertex buffers, materials, morph/asset refs. Document the on-disk order/sizes (`[binary]`). If any
local file uses this format, add structs + validate; otherwise tag `[binary-only]`.

- [ ] **Step 3: RE LoadSkinnedMesh / LoadSkinData / SP_RenderModel::Load / LoadStrided / LoadPrefab**

Decompile each, record their structures and dispatch. Add to the schema only where a local file
exercises them (`[measured]`+`[sweep]`); otherwise document `[binary-only]` in `BMDL_FORMAT.md`.

- [ ] **Step 4: Run the validator (regression)**

Run: `python tools/validate_bmdl.py "C:/CodingProjects/Personal/Darkspore/Data/BMDL_environments"`
Expected: `fail=0` (no regression from added structs).

- [ ] **Step 5: Commit**

```bash
git add bmdl_schema.py docs/BMDL_FORMAT.md
git commit -m "docs(re): alternative model formats (GameModel v8/9, skinned, prefab) documented"
```

---

## Task 9: Ghidra annotation pass

**Files:** none in repo (Ghidra MCP only).

- [ ] **Step 1: Create/confirm structs in Ghidra**

Ensure `bmdl_*` structs exist for every confirmed layout (root, skeleton, bone, anim header/track,
model, material, matparam, texbinding, mesh, vdecl elem, instance, renderable, + alt-format structs).
Several already exist; create the missing ones with exact fields from `bmdl_schema.py`.

- [ ] **Step 2: Name functions + add plate comments**

Confirm/name the load-path functions and add a one-paragraph plate comment to each
(`ReadResourceModel`, `LoadAsset`, `LoadGameModelVersioned`, `FUN_004a47b0`, `FUN_004ae430`,
`LoadSkinnedMesh`, `LoadSkinData`) summarizing what it reads and which `bmdl_*` structs it uses. Only
when certain (no speculation).

- [ ] **Step 3: Save the Ghidra program** (via the MCP `save_program`).

No git commit (Ghidra DB is external).

---

## Self-review

- **Spec coverage:** schema (Tasks 1–5, 8) ✓; standalone validator/sweep gate (Tasks 1,6) ✓;
  `BMDL_FORMAT.md` + deep-dive cross-links (Task 7) ✓; alternative formats (Task 8) ✓; Ghidra annotation
  (Task 9) ✓; decoupling — satisfied by `bmdl_schema.py` being pure stdlib and `bmdl_core.py` untouched
  (noted in File structure) ✓; no importer behaviour change ✓.
- **Placeholders:** the RE tasks (5, 8) specify the exact Ghidra functions/offsets to confirm and the
  validation gate rather than inventing unknown fields — this is intended for discovery work, not a
  placeholder; all *code* steps contain complete code.
- **Type consistency:** `Reader.read`/`read_array`/`in_range`/`cstr`/`field`, the `STRUCTS` dict, and
  `WALK`/`walk(r, seen, problems)` are used consistently across Tasks 1–5; struct names
  (`TbmdlRoot`, `Skeleton`, `Bone`, `AnimHeader`, `AnimTrack`, `Model`, `Material`, `MatParam`,
  `TexBinding`, `Mesh`, `VDeclElem`, `Instance`, `Renderable`) are stable.
