# BMDL Importer Refactor onto the Schema — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all `.bmdl` parsing run through the verified `bmdl_schema.py`, with `bmdl_core.py` a pure (no `bpy`/`mathutils`) parser returning plain structures; replace the mesh heuristics with the exact schema-driven geometry decode; fix coordinate handedness/winding — all guarded by golden+spec tests so animation and materials do not regress.

**Architecture:** Layered. `bmdl_schema.Reader` → `bmdl_core.parse()` (pure) → plain dict/array structures → the bpy build layer (`io_mesh`/`io_armature`/`io_anim`/`io_material`, the only modules using `mathutils`) → Blender objects. Migrate section-by-section; golden snapshots captured BEFORE the refactor guard the working parts at every step.

**Tech Stack:** Python 3 stdlib (parser/tests), Blender 5.1 `bpy`/`mathutils` (build layer + headless test runner), the local corpus at `C:\CodingProjects\Personal\Darkspore\Data\BMDL_environments`.

---

## Conventions

- Run standalone parser tests and the corpus validator with SYSTEM python: `python tools/validate_bmdl.py "<corpus>"`, `python tests/test_parser.py`.
- Run Blender-dependent tests headlessly via the Blender MCP `execute_python` (or `blender --background --python`). The fixtures live under the corpus.
- Commit after each task. English messages, no co-author / no "Generated with" trailer.
- The Phase 1 corpus validator (`tools/validate_bmdl.py`, fail=0 on 1234 files) must keep passing throughout — it is the parse gate.

## The parser data contract (the interface every task shares)

`bmdl_core.parse(data: bytes) -> dict` returns plain Python (no bpy/mathutils):

```
{
  "base": int, "graph_size": int,
  "model": {
    "name": str|None,
    "materials": [ {                       # one per bmdl material (by imat)
        "shader": str|None, "name_hash": int, "flags": int,
        "params": {name: float|tuple},     # resolved MatParam -> custom_floats slice
        "custom_floats": [float],
        "textures": [ {"key","key_hash","value","value_hash"} ],
        "streams":  [ {"key","key_hash","value","value_hash"} ],
    } ],
    "meshes": [ {                          # one per bmdl mesh (geometry)
        "name": str|None, "flags": int, "stride": int,
        "vertex_count": int, "index_count": int,
        "decl": [ {"stream","offset","type_id","usage","usage_index"} ],   # usage = D3DDECLUSAGE
        "positions":    [(x,y,z), ...],            # len == vertex_count
        "normals":      [(x,y,z), ...] | None,
        "uv_sets":      {usage_index: [(u,v), ...]},
        "colors":       [(r,g,b,a), ...] | None,   # 0..1
        "weights":      [(w0,w1,w2,w3), ...] | None,
        "bone_indices": [(i0,i1,i2,i3), ...] | None,
        "indices":      [int, ...],                # full 16-bit index buffer, len == index_count
        "instances": [ {                            # LODs referencing this mesh family
            "mesh_index": int,
            "renderables": [ {"material_index","index_start","index_count"} ],
        } ],
    } ],
  },
  "skeleton": [ {"name","name_hash","parent","inv_bind": (16 floats)} ] | None,
  "anims": [ {"name","duration",
              "tracks": [ {"bone_index","category","times":[float],"values":[tuple]} ]} ],
}
```

Notes:
- `decl.usage` is the D3DDECLUSAGE the engine assigns from `type_id` via the switch (see `bmdl_schema.read_vdecl`); the parser maps the on-disk element to (usage, usage_index, type_id, offset) so the build layer never re-guesses.
- Vertex attributes are decoded ONCE per mesh over `vertex_count` vertices at the schema-confirmed stride; renderables are pure `(index_start, index_count)` ranges into `indices`. No base-vertex search, no index-mode scoring.
- `anims[].tracks[].values`: POS/SCALE → list of 3-tuples; ROT → list of 4-tuples in **wxyz** (already normalised with shortest-arc continuity, as the current `_decode_animation` does). No `mathutils`.

---

## File structure

- Modify (rewrite): `bmdl_core.py` — pure parser producing the contract above; no `bpy`/`mathutils`; no heuristics.
- Modify: `bmdl_schema.py` — add pure decode helpers (`half_to_float`, vertex-attribute decoders) if not already present.
- Modify: `__init__.py` — call `bmdl_core.parse()`; drop the mode-scoring/base-vertex loop; feed the build layer.
- Modify: `io_mesh.py`, `io_armature.py`, `io_anim.py`, `io_material.py` — consume the contract; `mathutils` confined here; handedness applied here.
- Create: `tests/capture_golden.py` — dumps the CURRENT importer output to JSON fixtures (run before refactor).
- Create: `tests/golden/` — JSON snapshots (committed).
- Create: `tests/test_parser.py` — standalone (no Blender) assertions on `bmdl_core.parse()`.
- Create: `tests/run_blender_tests.py` — headless import + assert-against-golden harness.

Fixture set (4 files, under the corpus): `CreatureEditor_EL/creatureeditor_el_anime_arm.bmdl` (anim+chrome+skeleton), `scaldron/scaldron_terrain_a.bmdl` (supermix/submix/generic terrain), `Cryos/cryos_stalactite.bmdl` (crystal), `effects/beam_down_column.bmdl` (unlit FX).

---

## Task 1: Golden capture of current importer output (safety net)

**Files:** Create `tests/capture_golden.py`, `tests/golden/*.json`.

- [ ] **Step 1: Write `tests/capture_golden.py`**

It imports each fixture with the CURRENT importer and writes a JSON snapshot per file. Run it inside Blender (MCP `execute_python` or `blender --background`). It must capture, per imported object: `name`, `vertex_count` (`len(mesh.vertices)`), `tri_count` (`len(mesh.loop_triangles)` after `calc_loop_triangles()`), sorted `uv_layers` names, sorted `color_attributes` names, and per material slot `(shader_family, has_diffuse_image)`; and per Action: `name` and total fcurve count; and for the creature fixture, the world-space deformation quaternion angle of bone `head_rota` at frames 0 and 340 (rounded 3 dp).

```python
import bpy, os, sys, types, importlib.util, json, math
ADDON = r"C:\Program Files\Blender Foundation\Blender 5.1\5.1\scripts\addons_core\BMDL-Importer"
CORPUS = r"C:\CodingProjects\Personal\Darkspore\Data\BMDL_environments"
FIXTURES = {
    "creature": "CreatureEditor_EL/creatureeditor_el_anime_arm.bmdl",
    "scaldron": "scaldron/scaldron_terrain_a.bmdl",
    "crystal":  "Cryos/cryos_stalactite.bmdl",
    "unlitfx":  "effects/beam_down_column.bmdl",
}

def load_addon():
    for k in [m for m in list(sys.modules) if m.startswith("bmdlpkg")]:
        del sys.modules[k]
    pkg = types.ModuleType("bmdlpkg"); pkg.__path__ = [ADDON]; pkg.__package__ = "bmdlpkg"
    sys.modules["bmdlpkg"] = pkg
    for mod in ["bmdl_schema", "bmdl_core", "utils", "io_mesh", "io_material", "io_armature", "io_anim"]:
        spec = importlib.util.spec_from_file_location("bmdlpkg." + mod, os.path.join(ADDON, mod + ".py"))
        m = importlib.util.module_from_spec(spec); sys.modules["bmdlpkg." + mod] = m; spec.loader.exec_module(m)
    spec = importlib.util.spec_from_file_location("bmdlpkg.__init__", os.path.join(ADDON, "__init__.py"))
    init = importlib.util.module_from_spec(spec); sys.modules["bmdlpkg.__init__"] = init; spec.loader.exec_module(init)
    return init

def shader_family(mat):
    try:
        from bmdlpkg import io_material as IM
        return IM._classify((mat.name or "").rstrip("0123456789_"))
    except Exception:
        return "?"

def snapshot(init, key, rel):
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    m3 = init.make_axis_m3(True, "-Z", "Y")
    settings = {"import_textures": True, "use_custom_texture_dir": False, "convert_axes": True,
                "axis_forward": "-Z", "axis_up": "Y", "axis_m3": m3, "join_renderables": True,
                "flip_v": True, "import_animations": True, "debug_log": False, "preview_uv": False}
    init.run_import_from_paths(bpy.context, [os.path.join(CORPUS, rel.replace("/", os.sep))], settings)
    objs = []
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        me = o.data; me.calc_loop_triangles()
        slots = []
        for s in o.material_slots:
            mt = s.material
            has_img = bool(mt and mt.node_tree and any(n.type == "TEX_IMAGE" and n.image for n in mt.node_tree.nodes))
            slots.append([shader_family(mt) if mt else None, has_img])
        objs.append({"name": o.name.split(".")[0], "verts": len(me.vertices),
                     "tris": len(me.loop_triangles),
                     "uv": sorted(l.name for l in me.uv_layers),
                     "col": sorted(c.name for c in me.color_attributes),
                     "slots": slots})
    objs.sort(key=lambda d: (d["name"], d["verts"]))
    acts = sorted([[a.name, sum(len(cb.fcurves) for L in a.layers for st in L.strips
                               for cb in st.channelbags)] for a in bpy.data.actions])
    snap = {"objects": objs, "actions": acts}
    if key == "creature":
        arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
        if arm:
            arm.animation_data.action = bpy.data.actions.get("idle")
            defs = {}
            for fr in (0, 340):
                bpy.context.scene.frame_set(fr); bpy.context.view_layer.update()
                pb = arm.pose.bones.get("head_rota")
                ml = arm.data.bones["head_rota"].matrix_local
                q = (pb.matrix @ ml.inverted()).to_quaternion()
                defs[str(fr)] = round(math.degrees(q.angle), 3)
            snap["head_rota_deg"] = defs
    return snap

def main():
    init = load_addon()
    os.makedirs(os.path.join(ADDON, "tests", "golden"), exist_ok=True)
    for key, rel in FIXTURES.items():
        snap = snapshot(init, key, rel)
        with open(os.path.join(ADDON, "tests", "golden", key + ".json"), "w") as f:
            json.dump(snap, f, indent=2, sort_keys=True)
        print(key, "captured:", len(snap["objects"]), "objs", len(snap["actions"]), "actions")

main()
```

- [ ] **Step 2: Run it inside Blender to capture the baseline**

Run via Blender MCP `execute_python` with the file's contents (or `blender --background --python tests/capture_golden.py`).
Expected: prints a captured line per fixture; `tests/golden/{creature,scaldron,crystal,unlitfx}.json` created with non-empty objects/actions.

- [ ] **Step 3: Commit the golden baseline**

```bash
git add tests/capture_golden.py tests/golden/
git commit -m "test: capture golden snapshots of current importer output (pre-refactor baseline)"
```

---

## Task 2: Pure parser — model, materials, skeleton, animations

**Files:** Modify `bmdl_core.py`, `bmdl_schema.py`. Create `tests/test_parser.py`.

This moves the already-correct material/skeleton/anim decoding onto `bmdl_schema` and removes the `mathutils` dependency. Do NOT change the decoding maths — only its plumbing (read via the schema; return plain structures).

- [ ] **Step 1: Write the failing standalone parser test**

```python
# tests/test_parser.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bmdl_core

CORPUS = r"C:\CodingProjects\Personal\Darkspore\Data\BMDL_environments"

def test_creature_model_skeleton_anims():
    data = open(os.path.join(CORPUS, "CreatureEditor_EL", "creatureeditor_el_anime_arm.bmdl"), "rb").read()
    m = bmdl_core.parse(data)
    assert m["skeleton"] is not None and len(m["skeleton"]) == 24
    assert m["skeleton"][1]["name"] == "Root" and m["skeleton"][2]["parent"] == 1
    names = sorted(a["name"] for a in m["anims"])
    assert names == ["activate", "idle", "retract", "up"]
    idle = next(a for a in m["anims"] if a["name"] == "idle")
    assert len(idle["tracks"]) == 70
    assert len(m["model"]["materials"]) == 5
    assert m["model"]["materials"][0]["shader"] == "labsChromeVertColor"

if __name__ == "__main__":
    test_creature_model_skeleton_anims()
    print("OK")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python tests/test_parser.py`
Expected: FAIL — `AttributeError: module 'bmdl_core' has no attribute 'parse'` (or the current `bmdl_core` still imports `mathutils`/has no `parse`).

- [ ] **Step 3: Add the pure model/skeleton/anim parse to `bmdl_core.py`**

Rewrite `bmdl_core.py` so that, at the top, it `import struct` and `import bmdl_schema as _S` (NO `from mathutils import ...`). Implement:
- `parse(data)` builds an `_S.Reader(data)`, reads `TbmdlRoot` at 0, and assembles the contract dict. For this task, fill `base`, `graph_size`, `model.name`, `model.materials`, `skeleton`, `anims` (leave `model.meshes = []` — Task 3 fills it).
- Materials: for each `Material` (via `_S` structs) resolve params with the existing `_mat_params` logic (already on the schema in `BMDLv2._mat_params`); textures/streams via the `TexBinding` struct into the dict shape above; `params` via the existing slice resolution.
- Skeleton: read `Skeleton` + `Bone[]`; `inv_bind` is the 16 floats; `parent` = `parent_index`.
- Anims: move `_enumerate_anim_headers`, `_read_tracks`, `_decode_animation` logic here, but make `_decode_animation` return the plain `tracks` list of `{bone_index, category, times, values}` (POS/SCALE 3-tuples, ROT wxyz 4-tuples) — keep the existing normalisation/continuity maths verbatim, and **delete the `Quaternion(...).to_euler` branch** (euler conversion, if ever needed, belongs in `io_anim`). Keep `_half_to_float` here (pure) and also expose it from `bmdl_schema` as `half_to_float` for the build layer.

Keep the old `BMDLv2` class and the `_decode_*`/`AnimHeader`/`ResolvedAnim` symbols for now (Task 4/5 remove them) so nothing breaks mid-refactor — but `parse()` must not depend on `mathutils`.

- [ ] **Step 4: Run the test to confirm it passes**

Run: `python tests/test_parser.py`
Expected: `OK`.

- [ ] **Step 5: Confirm the corpus validator still passes**

Run: `python tools/validate_bmdl.py "C:/CodingProjects/Personal/Darkspore/Data/BMDL_environments"`
Expected: `files=1234 ok=1234 fail=0`.

- [ ] **Step 6: Commit**

```bash
git add bmdl_core.py bmdl_schema.py tests/test_parser.py
git commit -m "refactor: pure bmdl_core.parse() for model/materials/skeleton/anims on the schema"
```

---

## Task 3: Pure parser — meshes (exact geometry decode)

**Files:** Modify `bmdl_core.py`, `bmdl_schema.py`. Modify `tests/test_parser.py`.

This is the heuristic-killer: decode each mesh's vertices once via the vertex declaration, read the full 16-bit index buffer, and list instances/renderables — all from the schema, no scoring.

- [ ] **Step 1: Add the failing geometry assertions to `tests/test_parser.py`**

```python
def test_scaldron_geometry():
    import os
    data = open(os.path.join(CORPUS, "scaldron", "scaldron_terrain_a.bmdl"), "rb").read()
    m = bmdl_core.parse(data)
    meshes = m["model"]["meshes"]
    assert len(meshes) == 11
    for me in meshes:
        assert len(me["positions"]) == me["vertex_count"]
        assert len(me["indices"]) == me["index_count"]
        assert max(me["indices"]) < me["vertex_count"]      # exact, not heuristic
        for inst in me["instances"]:
            for r in inst["renderables"]:
                assert r["index_start"] + r["index_count"] <= me["index_count"]
```

(Append this and call it from `__main__`.)

- [ ] **Step 2: Run to confirm it fails**

Run: `python tests/test_parser.py`
Expected: FAIL — `meshes` is empty (Task 2 left it `[]`).

- [ ] **Step 3: Implement the mesh decode in `bmdl_core.py`**

Add `bmdl_schema` decode helpers and the mesh parse. In `bmdl_schema.py` add pure helpers:
`half_to_float(h)` (IEEE half → float), and a generic `decode_attr(reader, vb_ptr, stride, count, offset, type_id, n_comp)` that reads `count` vertices at `vb_ptr + i*stride + offset` and decodes by `type_id` (1=FLOAT3, 5=FLOAT4, 4=UBYTE4 [normalise /255 for colours, raw ints for bone indices], the half types → `half_to_float`), returning a list of tuples. Use the Phase-1 `type_id → D3DDECLTYPE` table (already in `read_vdecl`'s docstring) for sizes.

In `bmdl_core.parse()`, fill `model.meshes`: for each `Mesh` struct, `read_vdecl` the declaration; compute `stride` from the declaration (max element offset + size, aligned) or the mesh field if present; decode the per-usage attributes (`usage 0`=position→`positions`, `usage 1`=normal→`normals` [if a packed/UBYTE4 normal, decode the packed form — reuse the same packing the materials path documented], `usage 4`=texcoord→`uv_sets[usage_index]`, `usage 5`=color→`colors`, `usage 6`=blendweight→`weights`, `usage 7`=blendindices→`bone_indices`); read the full index buffer (`index_count` × u16) from `ib_data_ptr`; and assemble `instances`/`renderables` from the `Instance`/`Renderable` structs.

Then DELETE the now-dead heuristic helpers from `bmdl_core.py`: `mesh_flexible`, `_score_mode`, `_scan_max_for_mode`, `_read_renderable_indices`, `_expected_tris`, `_compute_vb_cap`, `_validate_decl`, `_infer_stride_bytes`, and the per-renderable `_decode_*` decoders that the new `parse()` replaces. (Leave anything still imported by the build layer until Task 4 rewires it; note what you leave.)

- [ ] **Step 4: Run the test to confirm it passes**

Run: `python tests/test_parser.py`
Expected: `OK` (both tests).

- [ ] **Step 5: Corpus validator still green**

Run: `python tools/validate_bmdl.py "C:/CodingProjects/Personal/Darkspore/Data/BMDL_environments"`
Expected: `files=1234 ok=1234 fail=0`.

- [ ] **Step 6: Commit**

```bash
git add bmdl_core.py bmdl_schema.py tests/test_parser.py
git commit -m "refactor: exact schema-driven mesh decode in bmdl_core.parse() (removes heuristics)"
```

---

## Task 4: Rewire the build layer to consume `parse()`

**Files:** Modify `__init__.py`, `io_mesh.py`, `io_armature.py`, `io_anim.py`, `io_material.py`. Create `tests/run_blender_tests.py`.

- [ ] **Step 1: Write the golden-comparison harness `tests/run_blender_tests.py`**

It re-uses `capture_golden.snapshot()` to produce a fresh snapshot per fixture and compares against `tests/golden/*.json`, asserting equality of the fields that must not regress: `actions`, each object's `uv`, `col`, and `slots`; and `head_rota_deg` for the creature. It prints PASS/FAIL per fixture and a diff for any mismatch. (Geometry `verts`/`tris` are compared too but a mismatch there is reported as "GEOMETRY CHANGED — review" rather than a hard fail, since the exact decode may legitimately differ from the heuristic.)

```python
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capture_golden as G
ADDON = G.ADDON

def compare(key, fresh, golden):
    diffs = []
    if fresh["actions"] != golden["actions"]:
        diffs.append(("actions", golden["actions"], fresh["actions"]))
    if key == "creature" and fresh.get("head_rota_deg") != golden.get("head_rota_deg"):
        diffs.append(("head_rota_deg", golden.get("head_rota_deg"), fresh.get("head_rota_deg")))
    fo = {o["name"]: o for o in fresh["objects"]}; go = {o["name"]: o for o in golden["objects"]}
    soft = []
    for nm, g in go.items():
        f = fo.get(nm)
        if not f:
            diffs.append((f"object {nm} missing", True, False)); continue
        for fld in ("uv", "col", "slots"):
            if f[fld] != g[fld]:
                diffs.append((f"{nm}.{fld}", g[fld], f[fld]))
        for fld in ("verts", "tris"):
            if f[fld] != g[fld]:
                soft.append((f"{nm}.{fld}", g[fld], f[fld]))
    return diffs, soft

def main():
    init = G.load_addon()
    bad = 0
    for key, rel in G.FIXTURES.items():
        golden = json.load(open(os.path.join(ADDON, "tests", "golden", key + ".json")))
        fresh = G.snapshot(init, key, rel)
        diffs, soft = compare(key, fresh, golden)
        if soft:
            print(f"[{key}] GEOMETRY CHANGED (review): {soft}")
        if diffs:
            bad += 1
            print(f"[{key}] FAIL: {diffs}")
        else:
            print(f"[{key}] PASS")
    print("REGRESSIONS:", bad)
    return bad
main()
```

- [ ] **Step 2: Rewire `__init__.py` and the build layer**

In `__init__.py`, replace the per-mesh heuristic block (the `modes`/`stats`/`choice` scoring loop and the per-renderable `base_v`/`useB` search, roughly the body of the `for mi in range(...)` mesh loop) with: `model = bmdl_core.parse(data)`, then for each `model["model"]["meshes"]` build one object via `io_mesh.build_mesh` using the mesh's decoded `positions`/`normals`/`uv_sets`/`colors`/`indices`, and assign material slots from the mesh's `instances[].renderables[].material_index` (one slot per distinct `material_index`, faces partitioned by each renderable's `index_start..index_count`). Skinning uses the mesh's `weights`/`bone_indices`. Animations: pass `model["anims"]` + `model["skeleton"]` to `io_anim.import_animations` (adapt its signature to take the parsed structures instead of `ds`/`tb`). Materials: build via `io_material.make_material` from `model["model"]["materials"][imat]` (shader/params/textures/streams already in the dict). Keep the operator and its options unchanged.

`io_anim.py`/`io_armature.py`/`io_material.py`: change their inputs from the old `BMDLv2`/raw-pointer calls to the parsed structures. The bake maths (closed-form anim), the material node graphs, and skinning are unchanged — only their data source changes. `io_armature.build_armature` already takes a `bones` list; feed it `model["skeleton"]`.

- [ ] **Step 3: Run the golden harness in Blender**

Run `tests/run_blender_tests.py` via Blender MCP `execute_python` (or `blender --background --python`).
Expected: `[creature] PASS`, `[scaldron] PASS`, `[crystal] PASS`, `[unlitfx] PASS`, `REGRESSIONS: 0`. Geometry "review" lines are acceptable (exact decode may change vert/tri counts); investigate only if a model visibly breaks.

- [ ] **Step 4: Run the standalone parser tests + corpus validator**

Run: `python tests/test_parser.py` (Expected `OK`) and `python tools/validate_bmdl.py "<corpus>"` (Expected `fail=0`).

- [ ] **Step 5: Commit**

```bash
git add __init__.py io_mesh.py io_armature.py io_anim.py io_material.py tests/run_blender_tests.py
git commit -m "refactor: build layer consumes bmdl_core.parse(); heuristic mesh path removed"
```

---

## Task 5: Decouple and remove dead code

**Files:** Modify `bmdl_core.py`, `__init__.py`, others as needed.

- [ ] **Step 1: Remove dead code**

Delete from `bmdl_core.py` everything no longer used after Task 4: the `BMDLv2` class, the old `_decode_*` decoders, `AnimHeader`/`RawTrack`/`ResolvedAnim` (if the build layer no longer imports them), `_extract_params` (if unused), and any heuristic helper not already removed. In `__init__.py` remove the now-unused imports and the `slot_stem_base`/`slot_stem_norm`/`base_keys`/`norm_keys` leftovers.

- [ ] **Step 2: Verify the decoupling**

Run: `python -c "import ast,sys; t=ast.parse(open('bmdl_core.py').read()); mods=[n.module or '' for n in ast.walk(t) if isinstance(n,(ast.Import,ast.ImportFrom)) for _ in [0]]; print([m for m in mods if 'bpy' in m or 'mathutils' in m])"`
Expected: `[]` (bmdl_core imports neither bpy nor mathutils). Also `grep -n "import bpy\|mathutils" bmdl_core.py` → no matches.

- [ ] **Step 3: Re-run all gates**

`python tests/test_parser.py` (OK), `python tools/validate_bmdl.py "<corpus>"` (fail=0), and `tests/run_blender_tests.py` in Blender (REGRESSIONS: 0).

- [ ] **Step 4: Commit**

```bash
git add bmdl_core.py __init__.py
git commit -m "refactor: remove dead heuristic/duplicate code; bmdl_core fully decoupled from bpy/mathutils"
```

---

## Task 6: Handedness / winding fix

**Files:** Modify the build layer (`io_mesh.py` and/or `__init__.py` where the axis transform is applied).

- [ ] **Step 1: Determine the correct convention**

Confirm whether Darkspore's vertices are left-handed (D3D) and the triangle winding order. Cross-check: import a fixture, and compare orientation/normals against the game (the user is the visual reference). Decide the exact fix = the axis matrix already used (`make_axis_m3`) PLUS, when that matrix mirrors (determinant < 0) or when LH→RH requires it, a triangle-winding reversal (swap index b/c per triangle) and a consistent normal sign. Document the chosen convention in a comment.

- [ ] **Step 2: Apply the fix in one place**

In `io_mesh.build_mesh` (or the geometry assembly in `__init__`), apply the winding reversal and normal handling consistently with the axis transform, controlled by a single helper so it is trivial to flip. Do not scatter the logic.

- [ ] **Step 3: Visual verification**

Re-import the fixtures in Blender; confirm with the user that orientation is correct and normals face outward (no inside-out shading). Iterate Step 1-2 if the user reports it is still flipped/mirrored.

- [ ] **Step 4: Confirm no regression elsewhere**

Run `tests/run_blender_tests.py` (REGRESSIONS: 0 — the golden fields are orientation-independent; geometry "review" lines expected). `python tests/test_parser.py` (OK).

- [ ] **Step 5: Commit**

```bash
git add io_mesh.py __init__.py
git commit -m "fix: correct D3D->Blender handedness/winding (single consistent transform)"
```

---

## Task 7: Final verification

**Files:** none (verification + a short doc note).

- [ ] **Step 1: Full gate run**

`python tests/test_parser.py` (OK); `python tools/validate_bmdl.py "<corpus>"` (files=1234 fail=0); `tests/run_blender_tests.py` in Blender (REGRESSIONS: 0).

- [ ] **Step 2: Spot-check imports visually**

Import the four fixtures via the real operator (reload the add-on first) and confirm meshes, materials, animation, and orientation all look correct.

- [ ] **Step 3: Note the refactor in the docs**

Append a short "Phase 2: importer refactored onto `bmdl_schema`; `bmdl_core` is now a pure parser; handedness fixed" note to `docs/BMDL_FORMAT.md` (a few lines, English).

- [ ] **Step 4: Commit**

```bash
git add docs/BMDL_FORMAT.md
git commit -m "docs: note Phase 2 importer refactor onto the schema"
```

---

## Self-review

- **Spec coverage:** pure `bmdl_core` on schema (Tasks 2,3,5) ✓; remove heuristics (Task 3) ✓; decouple from bpy/mathutils (Task 5, verified) ✓; handedness/winding (Task 6) ✓; golden+spec tests, no regression (Tasks 1,4 + gates each task) ✓; corpus validator stays green (every task) ✓; operator interface unchanged (Task 4) ✓.
- **Placeholder scan:** Tasks 2/3/4 reference existing functions to move/rewire precisely (named symbols, named maths to keep verbatim) rather than vague instructions; new code (parser contract, decode helpers, tests) is shown. No "TBD"/"add error handling".
- **Type consistency:** the `parse()` contract dict (keys: `base/graph_size/model{name,materials,meshes}/skeleton/anims`, mesh keys, track keys) is defined once and referenced identically by Tasks 2,3,4 and the tests. `capture_golden.snapshot()`/`load_addon()` are defined in Task 1 and reused by Task 4's harness. Helper names (`half_to_float`, `decode_attr`, `read_vdecl`) are consistent.
