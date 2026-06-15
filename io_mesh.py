import bpy as _bpy
import os as _os
import time as _time
from mathutils import Vector as _Vector

# palette_color kept here (used for debug/material-less cases)

def palette_color(i):
    x = (i * 1103515245 + 12345) & 0xFFFFFFFF
    return ((x >> 16) & 255) / 255.0, ((x >> 8) & 255) / 255.0, (x & 255) / 255.0, 1.0


def build_mesh(context, name, verts, inds, uvsets, nrms, vcols, mat_slots, mats_index, flip_v, xform=None, preview_uv_index=None, apply_custom_normals=False, mat_objects=None):
    if xform is not None:
        for i in range(0, len(verts), 3):
            v = xform @ _Vector((verts[i], verts[i + 1], verts[i + 2]))
            verts[i], verts[i + 1], verts[i + 2] = v.x, v.y, v.z
        if nrms is not None:
            for i in range(0, len(nrms), 3):
                v = xform @ _Vector((nrms[i], nrms[i + 1], nrms[i + 2]))
                nrms[i], nrms[i + 1], nrms[i + 2] = v.x, v.y, v.z
    nv = len(verts) // 3
    ni = len(inds)
    nt = ni // 3
    me = _bpy.data.meshes.new(name or "BMDL")
    me.vertices.add(nv)
    me.vertices.foreach_set("co", verts)
    me.loops.add(ni)
    me.loops.foreach_set("vertex_index", inds)
    me.polygons.add(nt)
    me.polygons.foreach_set("loop_start", [i * 3 for i in range(nt)])
    me.polygons.foreach_set("loop_total", [3] * nt)
    if uvsets:
        for idx, uvs in uvsets.items():
            lyr = me.uv_layers.new(name=f"UV{idx}")
            luv = [0.0] * (ni * 2)
            for t in range(nt):
                a, b, c = inds[t * 3 : (t + 1) * 3]
                ua, va = uvs[a * 2 : a * 2 + 2]
                ub, vb = uvs[b * 2 : b * 2 + 2]
                uc, vc = uvs[c * 2 : c * 2 + 2]
                if flip_v:
                    va = 1.0 - va
                    vb = 1.0 - vb
                    vc = 1.0 - vc
                k = t * 6
                luv[k : k + 6] = [ua, va, ub, vb, uc, vc]
            lyr.data.foreach_set("uv", luv)
    if vcols is not None:
        col = me.color_attributes.new("Col", "BYTE_COLOR", "CORNER")
        c_loop = [0.0] * (ni * 4)
        for t in range(nt):
            a, b, c = inds[t * 3 : (t + 1) * 3]
            ra, ga, ba, aa = vcols[a * 4 : a * 4 + 4]
            rb, gb, bb, ab = vcols[b * 4 : b * 4 + 4]
            rc, gc, bc, ac = vcols[c * 4 : c * 4 + 4]
            k = t * 12
            c_loop[k : k + 12] = [ra, ga, ba, aa, rb, gb, bb, ab, rc, gc, bc, ac]
        col.data.foreach_set("color", c_loop)
    if mat_objects is not None:
        for m in mat_objects:
            me.materials.append(m)
    else:
        for imat in mat_slots:
            from .io_material import ensure_empty_material as _ensure_empty_material
            me.materials.append(_ensure_empty_material(f"SLOT_{int(imat):02d}"))
    if mats_index:
        me.polygons.foreach_set("material_index", mats_index)
    big = ni > 2_000_000
    if apply_custom_normals and nrms is not None and ni > 0 and not big:
        loop_normals = [0.0] * (ni * 3)
        for t in range(nt):
            a, b, c = inds[t * 3 : (t + 1) * 3]
            ax, ay, az = nrms[a * 3 : a * 3 + 3]
            bx, by, bz = nrms[b * 3 : b * 3 + 3]
            cx, cy, cz = nrms[c * 3 : c * 3 + 3]
            k = t * 9
            loop_normals[k : k + 9] = [ax, ay, az, bx, by, bz, cx, cy, cz]
        try:
            me.use_auto_smooth = True
            me.normals_split_custom_set([_Vector((loop_normals[i], loop_normals[i + 1], loop_normals[i + 2])) for i in range(0, len(loop_normals), 3)])
            me.polygons.foreach_set("use_smooth", [True] * nt)
        except Exception:
            pass
    obj = _bpy.data.objects.new(me.name, me)
    context.scene.collection.objects.link(obj)
    if preview_uv_index is not None:
        uv_name = f"UV{preview_uv_index}"
        if uv_name in [l.name for l in me.uv_layers]:
            from .io_material import ensure_uv_debug_material as _ensure_uv_debug_material
            m = _ensure_uv_debug_material(uv_name)
            if m.name not in [x.name for x in me.materials]:
                me.materials.append(m)
            obj.active_material = m
    me.validate(clean_customdata=False)
    me.update()
    return obj
