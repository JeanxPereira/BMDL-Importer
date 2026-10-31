#!/bin/sh
# CI check of the built extension, without the game: Blender's own manifest/zip validation, then a
# headless install + enable (register() must run clean on a machine with no Darkspore data).
#   tools/ci_blender.sh BLENDER_EXE ZIP
set -eu
B="$1"; ZIP="$2"
export BLENDER_USER_RESOURCES="$(mktemp -d)"
"$B" --factory-startup --command extension validate "$ZIP"
"$B" -b --factory-startup --command extension install-file -r user_default -e "$ZIP"
"$B" -b --factory-startup --python-exit-code 1 --python-expr '
import addon_utils, bpy
mod = "bl_ext.user_default.io_darkspore"
addon_utils.enable(mod, default_set=True, handle_error=None)
assert mod in bpy.context.preferences.addons, "extension did not register"
for op in ("io_darkspore", "darkspore_pick_textures"):
    assert hasattr(bpy.ops.import_scene, op), op
print("EXTENSION OK", bpy.app.version_string)
'
