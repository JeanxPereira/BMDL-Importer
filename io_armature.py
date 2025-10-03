import bpy
from mathutils import Matrix, Vector


def apply_axis_to_bind(mat_bind, m3):
    if m3 is None:
        return mat_bind
    r3 = Matrix((mat_bind[0][:3], mat_bind[1][:3], mat_bind[2][:3]))
    t  = Vector((mat_bind[3][0], mat_bind[3][1], mat_bind[3][2]))
    if m3 is not None:
        m3i = m3.inverted_safe()
        r_out = m3 @ r3 # @ m3i
        t_out = m3 @ t
    else:
        r_out = r3
        t_out = t
    out = Matrix.Identity(4)
    out[0][0], out[0][1], out[0][2] = r_out[0][0], r_out[0][1], r_out[0][2]
    out[1][0], out[1][1], out[1][2] = r_out[1][0], r_out[1][1], r_out[1][2]
    out[2][0], out[2][1], out[2][2] = r_out[2][0], r_out[2][1], r_out[2][2]
    out[3][0], out[3][1], out[3][2] = t_out.x, t_out.y, t_out.z
    return out


def build_armature(context, bones, name, axis_m3=None):
    arm = bpy.data.armatures.new(f"{name}")
    arm_obj = bpy.data.objects.new(arm.name, arm)
    context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    ebones = []
    for b in bones:
        m = Matrix(((b["inv_bind"][0], b["inv_bind"][1], b["inv_bind"][2], b["inv_bind"][3]),
                    (b["inv_bind"][4], b["inv_bind"][5], b["inv_bind"][6], b["inv_bind"][7]),
                    (b["inv_bind"][8], b["inv_bind"][9], b["inv_bind"][10], b["inv_bind"][11]),
                    (b["inv_bind"][12], b["inv_bind"][13], b["inv_bind"][14], b["inv_bind"][15])))
        bind = m.inverted_safe()
        bind = apply_axis_to_bind(bind, axis_m3)
        eb = arm.edit_bones.new(b["name"] or f"bone_{b['index']}")
        head = Vector((bind[3][0], bind[3][1], bind[3][2]))
        eb.head = head
        eb.tail = head + bind.to_3x3() @ Vector((0.0, 0.05, 0.0))
        ebones.append(eb)
    for i, b in enumerate(bones):
        p = b["parent"]
        if 0 <= p < len(bones):
            ebones[i].parent = ebones[p]
    child_map = {i: [] for i in range(len(bones))}
    for i, b in enumerate(bones):
        p = b["parent"]
        if 0 <= p < len(bones):
            child_map[p].append(i)
    for i, eb in enumerate(ebones):
        ch = child_map.get(i, [])
        if ch:
            v = ebones[ch[0]].head
            if (v - eb.head).length > 1e-6:
                eb.tail = v
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm_obj, [b["name"] or f"bone_{b['index']}" for b in bones]


def _find_skin_streams(decl):
    w_off = w_type = None
    i_off = i_type = None
    for e in decl:
        if e["stream"] == 0 and e["usage"] == 6 and e["usage_index"] == 0:
            w_off, w_type = e["offset"], e["type"]
        if e["stream"] == 0 and e["usage"] == 7 and e["usage_index"] == 0:
            i_off, i_type = e["offset"], e["type"]
    return (w_off, w_type, i_off, i_type)


def _decode_weights_indices(d, base, vb_ptr, vstart, count, stride, w_off, w_type, i_off, i_type):
    import struct
    W = [[0.0, 0.0, 0.0, 0.0] for _ in range(count)]
    I = [[0, 0, 0, 0] for _ in range(count)]
    if w_off is None or i_off is None:
        return W, I
    for i in range(count):
        o = base + vb_ptr + (vstart + i) * stride
        if w_type == 3:
            w0, w1, w2, w3 = struct.unpack_from("<ffff", d, o + w_off)
        elif w_type == 16:
            h0, h1, h2, h3 = struct.unpack_from("<HHHH", d, o + w_off)
            w0, w1, w2, w3 = _half_to_float(h0), _half_to_float(h1), _half_to_float(h2), _half_to_float(h3)
        elif w_type == 8:
            b0, b1, b2, b3 = struct.unpack_from("<BBBB", d, o + w_off)
            w0, w1, w2, w3 = b0/255.0, b1/255.0, b2/255.0, b3/255.0
        else:
            w0, w1, w2, w3 = 0.0, 0.0, 0.0, 0.0
        if i_type == 5:
            i0, i1, i2, i3 = struct.unpack_from("<BBBB", d, o + i_off)
        elif i_type == 7:
            i0, i1, i2, i3 = struct.unpack_from("<hhhh", d, o + i_off)
            i0, i1, i2, i3 = max(0,i0), max(0,i1), max(0,i2), max(0,i3)
        else:
            i0, i1, i2, i3 = 0, 0, 0, 0
        s = w0 + w1 + w2 + w3
        if s > 1e-8:
            w0, w1, w2, w3 = w0/s, w1/s, w2/s, w3/s
        W[i][0], W[i][1], W[i][2], W[i][3] = w0, w1, w2, w3
        I[i][0], I[i][1], I[i][2], I[i][3] = int(i0), int(i1), int(i2), int(i3)
    return W, I


def apply_skin_to_object(obj, ds, m, decl, base_v, vcount_r, stride, bones_count, bone_names, arm_obj, axis_m3=None):
    from .bmdl_core import _half_to_float
    w_off, w_type, i_off, i_type = _find_skin_streams(decl)
    if w_off is None or i_off is None:
        return False
    W, I = _decode_weights_indices(ds.d, ds.base, m["vb_ptr"], base_v, vcount_r, stride, w_off, w_type, i_off, i_type)
    vg_map = {}
    for bi in range(bones_count):
        n = bone_names[bi] if bi < len(bone_names) else f"bone_{bi}"
        vg = obj.vertex_groups.get(n) or obj.vertex_groups.new(name=n)
        vg_map[bi] = vg
    mod = obj.modifiers.get("Armature") or obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm_obj
    me = obj.data
    for vi in range(vcount_r):
        w4 = W[vi]
        i4 = I[vi]
        for k in range(4):
            bw = float(w4[k])
            bi = int(i4[k])
            if bw > 0.0 and 0 <= bi < bones_count:
                vg_map[bi].add([vi], bw, 'REPLACE')
    obj.parent = arm_obj
    return True


def apply_skin_joined(obj, ds, m, decl, stride, segments, bones_count, bone_names, arm_obj, axis_m3=None):
    from .bmdl_core import _half_to_float
    w_off, w_type, i_off, i_type = _find_skin_streams(decl)
    if w_off is None or i_off is None:
        return False
    vg_map = {}
    for bi in range(bones_count):
        n = bone_names[bi] if bi < len(bone_names) else f"bone_{bi}"
        vg = obj.vertex_groups.get(n) or obj.vertex_groups.new(name=n)
        vg_map[bi] = vg
    mod = obj.modifiers.get("Armature") or obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm_obj
    voff = 0
    for seg in segments:
        base_v = seg["base"]
        vcount_r = seg["vcount"]
        W, I = _decode_weights_indices(ds.d, ds.base, m["vb_ptr"], base_v, vcount_r, stride, w_off, w_type, i_off, i_type)
        for local_i in range(vcount_r):
            global_i = voff + local_i
            w4 = W[local_i]
            i4 = I[local_i]
            for k in range(4):
                bw = float(w4[k])
                bi = int(i4[k])
                if bw > 0.0 and 0 <= bi < bones_count:
                    vg_map[bi].add([global_i], bw, 'REPLACE')
        voff += vcount_r
    obj.parent = arm_obj
    return True
