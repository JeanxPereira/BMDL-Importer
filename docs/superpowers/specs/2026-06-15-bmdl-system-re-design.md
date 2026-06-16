# BMDL system — reverse engineering & documentation (Phase 1 design)

Status: approved approach (A). Phase 1 of a three-phase effort.

## Goal

Recover **100% of Darkspore's model (`.bmdl`) load system and architecture** from the Ghidra
database, validate it to certainty, and capture it as a **single authoritative struct schema** plus
derived documentation and Ghidra annotations. This becomes the verified foundation for the later
importer refactor (Phase 2) and the subsequent cleanup / performance / distribution work (Phase 3).

**Phase 1 changes no importer behaviour.** It only produces knowledge artifacts (schema, validator,
docs, Ghidra annotations).

## Scope

In scope:
- **Container**: file header, graph relocation (`BinaryBuffer::Relocate`), and the asset dispatch
  (`SP_RenderAsset::LoadAsset @ 004aeea0`) with its asset-type hash table.
- **bmdl v2 resource model** (`BinaryModel::ReadResourceModel @ 004a9220`): root/tbmdl, model/geometry,
  materials, skeleton, meshes + vertex declaration + vertex/index buffers, instances/renderables/LODs,
  collision mesh, tags.
- **Animations**: consolidate the already-verified findings and close any remaining binary gaps.
- **Alternative model formats**: GameModel versioned v8/v9 (`LoadGameModelVersioned @ 004aee10` →
  `FUN_004a47b0`, `FUN_004ae430`), `LoadSkinnedMesh @ 004a4490`, `LoadSkinData @ 004a4850`,
  `SP_RenderModel::Load` / `LoadStrided`, `LoadPrefab` — at least their on-disk structures and dispatch.
- **Runtime semantics** only where needed to disambiguate a parse (e.g. animation composition order,
  skinning palette layout, normal / vertex-colour decode swizzles).

Out of scope (later phases, each its own spec):
- Phase 2: refactor the importer onto the schema, replace the mesh heuristics with the exact layout,
  fix handedness/winding, fully decouple the parser.
- Phase 3: dead-code cleanup, performance/vectorization, distribution (extension publishing), and the
  faithful-rendering follow-ups (cubemap reflections, terrain splat blend, `labsPuddle` from
  `Levels.package`).

## Quality gate ("100% certain")

A struct/field is **confirmed** only when both hold:
1. **[binary]** it is read directly in the Ghidra decompilation of the function(s) that produce or
   consume it; and
2. **[measured]** it is verified against the real bytes of at least one `.bmdl` file.

In addition, the whole load path must pass:
3. **[sweep]** a standalone validation parser parses the full local `.bmdl` corpus using **only** the
   schema — no heuristics, no fallbacks — with zero parse errors, zero out-of-range pointers, and no
   leftover unexplained regions.

Anything that still requires a heuristic is, by definition, not yet understood and blocks
documentation of that area. Structs that only exist in files we do not have locally are marked
**[binary-only]** with the gap stated explicitly — never assumed silently.

## Approach (A): bottom-up, struct-by-struct, validate-as-you-go

Follow the real load code from the dispatcher down, extract one struct at a time, confirm each against
the gate, and immediately record it in the schema + Ghidra + docs before moving on. Stand up the
validation sweep early so every new struct is proven across hundreds of files as soon as it lands.

## Deliverables & architecture

1. **`bmdl_schema.py`** — pure-Python (no `bpy` / `mathutils`) declarative struct definitions. Each
   struct: `name`, `stride`, `fields = [(name, offset, ctype)]`, where `ctype` is from a small fixed
   set (`u8/u16/u32/i32/f32/ptr/cstr/float[16]/...` and references to other structs). Sufficient to
   parse a file and to generate the docs. **Single source of truth**: lives in the add-on package so the
   importer can consume it in Phase 2, and is importable standalone for the validator/tools.
2. **`tools/validate_bmdl.py`** — standalone validator (no Blender). Loads `bmdl_schema`, walks a
   directory of `.bmdl`, parses every structure via the schema, and asserts: magic/version; all
   pointers in range; all counts sane; expected contiguity/relationships hold (e.g. anim `times` then
   `values` are contiguous); no fallback taken. Emits a coverage report (files parsed, structs seen,
   anomalies). This is the empirical gate (item 3 above).
3. **Docs (English)**:
   - **`docs/BMDL_FORMAT.md`** (new) — master spec: container & header, graph relocation, the
     `LoadAsset` dispatch table (asset-type hash → loader), the bmdl v2 structure tree, every struct
     layout (checked against the schema), and one section per alternative format. Mermaid diagrams for
     the container tree and the dispatch/call graph.
   - **`docs/BMDL_ANIMATION.md`** and **`docs/BMDL_MATERIALS.md`** remain as deep-dives, cross-linked
     from the master spec and updated to reference the schema.
4. **Ghidra annotation** — structs for every confirmed layout (`bmdl_*` prefix), function names for the
   load path and the alternative paths, and plate comments summarizing each loader. Applied only when
   certain (no speculation).
5. **Decoupling prerequisite** — split the pure byte-reading parser core from `bpy`/`mathutils` so the
   schema and validator run standalone. Kept behaviour-preserving; covered by a quick import smoke test.
   (This also de-risks Phase 2.)

## Work breakdown (order)

1. **Container & dispatch** — header, `BinaryBuffer::Relocate`, the `LoadAsset` asset-type hash table.
   Stand up the schema skeleton, the validator harness, and the sweep corpus.
2. **bmdl v2 geometry (the gap)** — model struct, meshes, vertex declaration (element types/usages),
   vertex buffer (stride, attribute decode incl. packed normal/colour swizzles), index buffer (16-bit,
   factor), instances/renderables/LODs, collision mesh, tags. This is where the current importer
   heuristics (index-mode scoring, densest-base-vertex search) get replaced by the exact layout.
3. **Consolidate animations & materials** — fold the already-verified anim/material structs into
   `bmdl_schema` and the master doc; close any remaining [binary] gaps (e.g. the animation sampler
   composition order, if it disambiguates anything).
4. **Alternative formats** — GameModel versioned (v8/v9), `LoadSkinnedMesh`, `LoadSkinData`,
   `SP_RenderModel::Load`/`LoadStrided`, `LoadPrefab`: document structs + dispatch.
5. **Runtime confirmations** — only the bits needed to remove ambiguity.

Each step: RE → confirm (binary + measured) → schema → validator passes on the sweep → doc → Ghidra.

## Acceptance criteria (Phase 1 done)

- `bmdl_schema.py` defines every struct in the load path with **no heuristic fields**.
- `tools/validate_bmdl.py` parses the full local `.bmdl` corpus (`BMDL_environments`, ~1234 files) with
  **0 errors and 0 heuristic/fallback usages**, and reports structs/coverage.
- `docs/BMDL_FORMAT.md` is complete (all structs + dispatch + alternative formats), the anim/materials
  deep-dives are cross-linked, everything is in English, with `[measured]`/`[binary]`/`[sweep]` tags.
- Ghidra: load-path and alternative-path structs and functions are named/commented.
- **No importer behaviour change** in Phase 1.

## Risks / mitigations

- **Files for a format are absent locally** → the sweep cannot exercise that path. Mitigation: mark
  those structs `[binary-only]` and state the gap; do not assume.
- **The GameModel-versioned path** may need files of that format; if absent, document from the binary
  and flag `[binary-only]`.
- **Decoupling the parser from mathutils** could touch importer code; keep it behaviour-preserving and
  guard with an import smoke test.

## Phases (context)

- **Phase 1 (this spec):** RE + schema + docs + Ghidra. No behaviour change.
- **Phase 2:** refactor the importer onto the schema (exact mesh parse, handedness/winding, full
  decoupling).
- **Phase 3:** cleanup (dead code, package rename), performance (vectorized decode), distribution
  (Blender extension), and faithful-rendering follow-ups.
