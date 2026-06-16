<div align="center">
  <img src="res/icon.png" alt="Darkspore BMDL Importer" width="256" />
</div>

<h1 align="center">Darkspore BMDL Importer</h1>
<p align="center">Blender add-on to import Darkspore <code>.bmdl</code> models, materials, skinning, and embedded animations.</p>

## Overview

`.bmdl` is Darkspore's model container: a relocatable graph holding the geometry, the
skeleton, the materials, and the embedded animations. This add-on parses that container and
rebuilds it in Blender — meshes, a weighted armature, materials, and baked actions.

The material and animation behaviour is reconstructed from the game's actual data and shader
math (recovered by reverse engineering), not approximated. See the documents under `docs/` for
the full format and the reasoning behind every field.

## Features

- Imports `.bmdl` meshes, auto-detecting index size and triangle layout.
- Builds an armature from the file's skeleton and binds meshes with vertex weights.
- Imports embedded animations as actions (location / rotation / scale per bone), using a
  closed-form bake that matches the game's parent-relative local transforms.
- Reconstructs materials data-driven from the per-material parameters, covering all of
  Darkspore's labs shader families (lit, chrome/reflective, crystal, terrain mix, foliage,
  unlit/FX, and more).
- Resolves textures by filename and by Darkspore FNV-1 hash, with a bounded folder search.
- Writes detailed per-mesh, texture, and animation logs next to the imported file.

## Requirements

- Blender 4.4 or newer (tested on 5.1). The new slotted Action system is used, with a fallback
  for legacy actions.
- License: GPL-3.0-or-later.
- Authors: JeanxPereira, foehammer.

## Installation

1. Clone or download this repository.
2. Zip the add-on folder so the archive root contains `__init__.py` and the other modules.
3. In Blender: Edit > Preferences > Add-ons > Install, and select the zip.
4. Enable "Darkspore BMDL Importer".
5. Import via File > Import > Darkspore (.bmdl).

Developer install: copy or symlink the add-on folder into your Blender
`scripts/addons` (or `scripts/addons_core`) directory.

## Usage

### From the UI

1. File > Import > Darkspore (.bmdl).
2. Select one or more `.bmdl` files.
3. Optionally enable Import Textures and either keep the default search (nearby
   `~animations` / `animations~` folders) or set a custom texture directory.
4. Optionally enable Import Animations to bake actions onto the created armature.
5. Import.

### From Python

```python
import bpy

bpy.ops.import_scene.io_darkspore(
    filepath="D:/Darkspore/models/example.bmdl",
    import_textures=True,
    use_custom_texture_dir=True,
    textures_dir="D:/Darkspore/textures",
    import_animations_opt=True,
    join_renderables=True,
    flip_v=True,
)
```

## Importer options

- Import Textures: resolve and link textures (by name or FNV-1 hash). With Use Custom Texture
  Path, search a chosen directory; otherwise search candidate folders near the `.bmdl`.
- Import Animations: bake the embedded actions onto the generated armature.
- Join Renderables: merge a mesh's renderable slots into one object (material slots preserved).
- Flip V: flip the V coordinate on UV write (correct for most DDS/TGA sources).
- Apply Custom Normals: inject decoded vertex normals as split normals (skipped on very large meshes).
- Preview UV (Checker): assign a UV-checker material for inspection.
- Axis Forward / Axis Up / Apply Axis to Vertices: orientation conversion for geometry and animation.
- Debug Log / Dry Run: diagnostics; Dry Run scores index modes without building meshes.

## Materials

Each material names a shader (for example `labsChromeVertColor`) plus a packed parameter block
and a set of texture and vertex-stream bindings. The importer reads those parameters and builds
a node graph per shader family:

- Lit / terrain shaders use a Principled BSDF with the packed normal map decoded correctly
  (the normal map stores gloss in R, normal X/Y in A/G, spec exponent in B), roughness from
  gloss, specular from the material's specular tint and level, and emission from the diffuse
  alpha (the glow mask).
- Reflective shaders (chrome, tech) add a gloss-masked environment reflection.
- Crystal shaders use glass-like transmission with fresnel reflection.
- The terrain SuperMix shader blends four layers as a weighted sum driven by the normalised
  vertex-colour channels, each layer with its own tiling and tint.
- Unlit and FX shaders use an Emission shader (additive or alpha-blended as appropriate).

The full format, the 33-shader catalog with exact per-shader math, and the known limitations are
documented in [docs/BMDL_MATERIALS.md](docs/BMDL_MATERIALS.md).

## Animations

Animation tracks store parent-relative local transforms (translation / quaternion rotation /
scale) per bone, sampled at keyframe times. The importer composes these up the bone hierarchy
and bakes the result onto the armature's pose bones. The format and the bake math are documented
in [docs/BMDL_ANIMATION.md](docs/BMDL_ANIMATION.md).

## Logs

Each import writes sidecar logs next to the source file:

- `<file>.darkspore_import.log.txt` — per-mesh scan: chosen index mode, vertex counts, segments.
- `<file>.darkspore_import.missing_textures.log.txt` — which hints/hashes were searched and resolved.
- `<file>.darkspore_anim.log.txt` — animation parsing summary.

## Known limitations

- Darkspore is a deferred renderer; Blender's forward shading approximates the lit term using
  scene lights.
- Per-material environment maps are stored as 6-face cubemap strips, which Blender cannot sample
  natively as a cube; the reflection is approximated.
- Terrain SubMix decal layers blend softly through the deferred decal pass; imported as separate
  opaque meshes they show hard polygon edges. The geometry and textures are faithful.

## Project layout

- `bmdl_core.py` — binary parsing: header/graph, model, skeleton, meshes, materials, animation decode.
- `io_mesh.py` — mesh build (geometry, UVs, vertex colours, normals).
- `io_material.py` — data-driven material builder (all labs shader families) and texture search.
- `io_armature.py` — armature creation, bind-pose transforms, skinning.
- `io_anim.py` — closed-form animation bake.
- `utils.py` — axis-matrix helper and Darkspore FNV-1 hash.

## Credits

- foehammer — specs and prior research into Darkspore formats.
- Community research on Darkspore/Spore file structures and hashing.

---

Menu path: File > Import > Darkspore (.bmdl)
Issue tracker: https://github.com/JeanxPereira/BMDL-Importer/issues/
