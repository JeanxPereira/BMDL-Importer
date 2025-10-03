import bpy
import os
import time
import re
from mathutils import Vector
from .bmdl_core import _extract_params
from .utils import darkspore_hash


def palette_color(i):
    x = (i * 1103515245 + 12345) & 0xFFFFFFFF
    return ((x >> 16) & 255) / 255.0, ((x >> 8) & 255) / 255.0, (x & 255) / 255.0, 1.0


def ensure_empty_material(name):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    if hasattr(m, "blend_method"):
        m.blend_method = "OPAQUE"
    if hasattr(m, "shadow_method"):
        m.shadow_method = "OPAQUE"
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m


def ensure_uv_debug_material(uv_name):
    mat = bpy.data.materials.get("DS_DEBUG_UV") or bpy.data.materials.new("DS_DEBUG_UV")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    emis = nt.nodes.new("ShaderNodeEmission")
    emis.location = (200, 0)
    uvn = nt.nodes.new("ShaderNodeUVMap")
    uvn.uv_map = uv_name
    uvn.location = (-400, 0)
    chk = nt.nodes.new("ShaderNodeTexChecker")
    chk.location = (-150, 0)
    nt.links.new(uvn.outputs["UV"], chk.inputs["Vector"])
    nt.links.new(chk.outputs["Color"], emis.inputs["Color"])
    nt.links.new(emis.outputs["Emission"], out.inputs["Surface"])
    return mat


def _iter_with_depth(root, max_depth):
    root = os.path.normpath(root)
    base_depth = root.count(os.sep)
    for cur, dirs, files in os.walk(root):
        if cur.count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
        yield cur, files


def find_image_limited(tex_dir, hint, max_depth=2):
    if not tex_dir or not hint:
        return None
    hn = os.path.basename(hint).replace("\\", "/").split("/")[-1]
    candidates = [hn, hn.lower(), hn.upper()]
    name, ext = os.path.splitext(hn)
    for alt in (name + ".dds", name + ".png", name + ".tga", name + ".jpg", name + ".jpeg", name + ".tif", name + ".exr"):
        candidates.extend([alt, alt.lower(), alt.upper()])
    for cur, files in _iter_with_depth(tex_dir, max_depth):
        s = {f.lower(): f for f in files}
        for c in candidates:
            lc = c.lower()
            if lc in s:
                return os.path.join(cur, s[lc])
    return None


def _load_image_cached(path, img_cache):
    ap = os.path.abspath(path)
    if ap in img_cache:
        return img_cache[ap]
    try:
        img = bpy.data.images.load(ap)
        try:
            img.filepath = bpy.path.relpath(ap)
        except Exception:
            img.filepath = ap
        img_cache[ap] = img
        return img
    except Exception:
        return None


def _find_by_stem(stem, search_dirs, img_cache, max_depth=5):
    if not stem:
        return None, None
    stems = [stem] if os.path.splitext(stem)[1] else [stem + ext for ext in (".dds",".png",".tga",".jpg",".jpeg",".tif",".exr")]
    for sd in search_dirs:
        for cur, files in _iter_with_depth(sd, max_depth):
            s = {f.lower(): f for f in files}
            for st in stems:
                lc = os.path.basename(st).lower()
                if lc in s:
                    path = os.path.join(cur, s[lc])
                    img = _load_image_cached(path, img_cache)
                    return img, path
    return None, None

def _find_by_hash(value_hash, search_dirs, img_cache, max_depth=5):
    if value_hash is None:
        return None, None
    hx = f"{int(value_hash) & 0xFFFFFFFF:08X}"
    for sd in search_dirs:
        for cur, files in _iter_with_depth(sd, max_depth):
            for fname in files:
                stem, _ext = os.path.splitext(fname)
                s = stem.upper()
                if s == hx or s == f"0X{hx}" or hx in s:
                    path = os.path.join(cur, fname)
                    img = _load_image_cached(path, img_cache)
                    if img:
                        return img, path
    return None, None

def _force_ignore_alpha(img):
    try:
        img.use_alpha = False
    except Exception:
        pass
    try:
        # Blender 4.x: 'STRAIGHT' | 'PREMUL' | 'CHANNEL_PACKED'
        img.alpha_mode = 'CHANNEL_PACKED'
    except Exception:
        # fallback (old version with 'NONE')
        try:
            img.alpha_mode = 'NONE'
        except Exception:
            pass

def make_principled_material(name, mat_entries, streams, uv_name, search_dirs, img_cache, mat_cache, missing_log, debug=False, mesh_name=None, cache_id=None, override_base=None, override_norm=None, logger=None):
    key = (cache_id or name or "BMDL_MAT", uv_name or "", tuple(search_dirs))
    m = mat_cache.get(key)
    if m and m.users >= 0:
        return m
    def _fmt_f(x):
        try:
            return f"{float(x):.3g}"
        except Exception:
            return str(x)
    def _fmt_pair(v, default=(0.0, 0.0)):
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            a, b = v[0], v[1]
        elif isinstance(v, (int, float)):
            a = b = v
        else:
            a, b = default
        return f"({_fmt_f(a)},{_fmt_f(b)})"
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name or "BMDL_MAT")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (900, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (500, 0)
    nt.links.new(bsdf.outputs.get("BSDF"), out.inputs.get("Surface"))
    if hasattr(m, "blend_method"):  m.blend_method  = "OPAQUE"
    if hasattr(m, "shadow_method"): m.shadow_method = "OPAQUE"
    uvn = mapn = None
    if uv_name:
        uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.uv_map = uv_name; uvn.location = (-1100, 0)
        mapn = nt.nodes.new("ShaderNodeMapping"); mapn.location = (-900, 0)
        nt.links.new(uvn.outputs["UV"], mapn.inputs["Vector"])
    base_keys = {"diffusemap","albedomap","basecolormap","albedo","basecolor","colormap","color","diffuse"}
    norm_keys = {"normalmap","bumpmap","normal"}

    def _collect_candidates(keys, override_val):
        c = []
        if override_val:
            c.append({"value": override_val, "value_hash": None, "key": "override"})
        for e in (mat_entries or []):
            k = (e.get("key") or "").lower()
            if k in keys:
                c.append({"value": e.get("value") or None, "value_hash": e.get("value_hash"), "key": k})
        return c

    def _resolve_chain(kind, candidates, map_node, color_space, link_to):
        resolved = None
        used_name = None
        used_hash = None
        for ent in candidates:
            stem = ent.get("value") or None
            vh = ent.get("value_hash")
            if stem:
                img, path = _find_by_stem(stem, search_dirs, img_cache)
                if img:
                    try:
                        img.use_alpha = False
                        img.alpha_mode = "NONE"
                    except Exception:
                        pass
                    try:
                        img.colorspace_settings.name = "sRGB"
                    except Exception:
                        pass
                    map_node.image = img
                    nt.links.new(img_base.outputs["Color"], bsdf.inputs.get("Base Color"))
                    link_to(img)
                    if debug and logger:
                        logger(f'  [mat] resolved {kind} via name="{stem}" -> {os.path.basename(path)}')
                    resolved = os.path.basename(path)
                    used_name = stem
                    break
                else:
                    if missing_log is not None:
                        missing_log.append((f"{kind}(name)", stem, [*search_dirs], name, False))
            if vh is not None:
                img2, path2 = _find_by_hash(vh, search_dirs, img_cache)
                if img2:
                    try:
                        img2.use_alpha = False; img2.alpha_mode = "NONE"
                    except Exception:
                        pass
                    try:
                        img2.colorspace_settings.name = color_space
                    except Exception:
                        pass
                    map_node.image = img2
                    link_to(img2)
                    if missing_log is not None:
                        missing_log.append((f"{kind}(hash)", f"0x{int(vh)&0xFFFFFFFF:08X}", [*search_dirs], name, True))
                    if debug and logger:
                        if stem:
                            logger(f'  [mat] resolved {kind} via hash=0x{int(vh)&0xFFFFFFFF:08X} (name="{stem}") -> {os.path.basename(path2)}')
                        else:
                            logger(f'  [mat] resolved {kind} via hash=0x{int(vh)&0xFFFFFFFF:08X} -> {os.path.basename(path2)}')
                    resolved = os.path.basename(path2)
                    used_hash = vh
                    break
        return resolved, used_name, used_hash

    img_base = nt.nodes.new("ShaderNodeTexImage"); img_base.location = (-450, 220)
    if mapn: nt.links.new(mapn.outputs["Vector"], img_base.inputs["Vector"])
    base_candidates = _collect_candidates(base_keys, override_base)
    base_name_resolved, _, _ = _resolve_chain(
        "albedo",
        base_candidates,
        img_base,
        "sRGB",
        lambda img: (
            _force_ignore_alpha(img),
            nt.links.new(img_base.outputs["Color"], bsdf.inputs.get("Base Color"))
        )
    )
    if base_name_resolved is None and missing_log is not None and not base_candidates:
        missing_log.append(("albedo", "(no-candidates)", [*search_dirs], name, False))

    img_norm = nt.nodes.new("ShaderNodeTexImage"); img_norm.location = (-450, -40)
    nmap = nt.nodes.new("ShaderNodeNormalMap"); nmap.location = (120, -60)
    if mapn: nt.links.new(mapn.outputs["Vector"], img_norm.inputs["Vector"])
    norm_candidates = _collect_candidates(norm_keys, override_norm)
    norm_name_resolved, _, _ = _resolve_chain(
        "normal",
        norm_candidates,
        img_norm,
        "Non-Color",
        lambda img: (nt.links.new(img_norm.outputs["Color"], nmap.inputs.get("Color")), nt.links.new(nmap.outputs.get("Normal"), bsdf.inputs.get("Normal")))
    )
    if norm_name_resolved is None and missing_log is not None and not norm_candidates:
        missing_log.append(("normal", "(no-candidates)", [*search_dirs], name, False))

    def _stem_sanitized(fname: str) -> str:
        st = os.path.splitext(fname)[0]
        st = re.sub(r'([._-])?[DN]$', '', st, flags=re.IGNORECASE)
        return st

    prefer = base_name_resolved or norm_name_resolved
    if prefer:
        try:
            m.name = _stem_sanitized(prefer)
        except Exception:
            pass

    params = _extract_params(streams)
    diff_level = float(params.get("difflevel", 1.0)) if isinstance(params.get("difflevel", 1.0), (int,float)) else 1.0
    spec_level = float(params.get("speclevel", 8.0)) if isinstance(params.get("speclevel", 8.0), (int,float)) else 8.0
    refl_level = float(params.get("reflectlevel", 0.5)) if isinstance(params.get("reflectlevel", 0.5), (int,float)) else 0.5
    norm_level = float(params.get("normallevel", 1.0)) if isinstance(params.get("normallevel", 1.0), (int,float)) else 1.0
    emis_level = float(params.get("emissivelevel", 0.0)) if isinstance(params.get("emissivelevel", 0.0), (int,float)) else 0.0
    glow_level = float(params.get("glowlevel", 0.0)) if isinstance(params.get("glowlevel", 0.0), (int,float)) else 0.0
    tile = params.get("tileuv", (1.0, 1.0))
    ofs  = params.get("offsetuv", (0.0, 0.0))
    if isinstance(tile, (int,float)): tile = (float(tile), float(tile))
    if isinstance(ofs,  (int,float)): ofs  = (float(ofs),  float(ofs))
    if mapn:
        try:
            mapn.inputs["Scale"].default_value[0]    = float(tile[0]) if len(tile)>=2 else 1.0
            mapn.inputs["Scale"].default_value[1]    = float(tile[1]) if len(tile)>=2 else 1.0
            mapn.inputs["Location"].default_value[0] = float(ofs[0])  if len(ofs)>=2  else 0.0
            mapn.inputs["Location"].default_value[1] = float(ofs[1])  if len(ofs)>=2  else 0.0
        except Exception:
            pass
    try:
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = max(emis_level, glow_level) * max(diff_level, 0.0)
    except Exception:
        pass
    try: bsdf.inputs["Specular"].default_value = max(0.0, min(1.0, refl_level))
    except Exception: pass
    try:
        # rgh = (2.0 / (spec_level + 2.0)) ** 0.5
        rgh = 2.0
        bsdf.inputs["Roughness"].default_value = max(0.0, min(1.0, rgh))
    except Exception:
        pass
    try: nmap.inputs["Strength"].default_value = float(norm_level)
    except Exception: pass
    if debug and logger:
        logger(f"[mat] {name} | uv={uv_name or '(none)'}")
    mat_cache[key] = m
    return m

def build_mesh(context, name, verts, inds, uvsets, nrms, vcols, mat_slots, mats_index, flip_v, xform=None, preview_uv_index=None, apply_custom_normals=False, mat_objects=None):
    if xform is not None:
        for i in range(0, len(verts), 3):
            v = xform @ Vector((verts[i], verts[i + 1], verts[i + 2]))
            verts[i], verts[i + 1], verts[i + 2] = v.x, v.y, v.z
        if nrms is not None:
            for i in range(0, len(nrms), 3):
                v = xform @ Vector((nrms[i], nrms[i + 1], nrms[i + 2]))
                nrms[i], nrms[i + 1], nrms[i + 2] = v.x, v.y, v.z
    nv = len(verts) // 3
    ni = len(inds)
    nt = ni // 3
    me = bpy.data.meshes.new(name or "BMDL")
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
            me.materials.append(ensure_empty_material(f"SLOT_{int(imat):02d}"))
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
            me.normals_split_custom_set([Vector((loop_normals[i], loop_normals[i + 1], loop_normals[i + 2])) for i in range(0, len(loop_normals), 3)])
            me.polygons.foreach_set("use_smooth", [True] * nt)
        except Exception:
            pass
    obj = bpy.data.objects.new(me.name, me)
    context.scene.collection.objects.link(obj)
    if preview_uv_index is not None:
        uv_name = f"UV{preview_uv_index}"
        if uv_name in [l.name for l in me.uv_layers]:
            m = ensure_uv_debug_material(uv_name)
            if m.name not in [x.name for x in me.materials]:
                me.materials.append(m)
            obj.active_material = m
    me.validate(clean_customdata=False)
    me.update()
    return obj


def search_roots_for(p, settings):
    roots = []
    if not settings.get("import_textures"):
        return roots
    if settings.get("use_custom_texture_dir"):
        td = settings.get("textures_dir") or ""
        if td:
            ap = os.path.abspath(td)
            if os.path.isdir(ap):
                roots.append(ap)
    base = os.path.abspath(os.path.dirname(p))
    cand_names = ["~animations", "animations~"]
    candidates = []
    for up in ["", "..", os.path.join("..",".."), os.path.join("..","..","..")]:
        updir = os.path.abspath(os.path.normpath(os.path.join(base, up)))
        for nm in cand_names:
            candidates.append(os.path.join(updir, nm))
    for c in candidates:
        ac = os.path.abspath(os.path.normpath(c))
        if os.path.isdir(ac):
            roots.append(ac)
    seen = set()
    uniq = []
    for r in roots:
        if r not in seen:
            uniq.append(r)
            seen.add(r) 
    return uniq


def write_missing_log(base_path, missings):
    if not missings:
        return
    log_dir = os.path.dirname(base_path)
    stem = os.path.splitext(os.path.basename(base_path))[0]
    log_path = os.path.join(log_dir, stem + ".darkspore_import.missing_textures.log.txt")
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] file={os.path.basename(base_path)}\n")
            found = 0
            missing = 0
            for kind, hint, roots, matname, resolved in missings:
                roots_s = "[" + ", ".join(roots) + "]"
                if resolved:
                    found += 1
                    f.write(f'material="{matname}" resolved="{kind}" hint="{hint}" searched_in={roots_s}\n')
                else:
                    missing += 1
                    f.write(f'material="{matname}" missing="{kind}" hint="{hint}" searched_in={roots_s}\n')
            f.write(f"-- totals: found={found} missing={missing}\n")
    except Exception:
        pass