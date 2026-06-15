import bpy
import os
import re
import time
from .bmdl_core import _extract_params

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
        img.alpha_mode = 'CHANNEL_PACKED'
    except Exception:
        try:
            img.alpha_mode = 'NONE'
        except Exception:
            pass

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

def _ensure_group_rnm():
    name = "DS_RNM_Combine"
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]
    ng = bpy.data.node_groups.new(name, "ShaderNodeTree")
    inp = ng.nodes.new("NodeGroupInput")
    out = ng.nodes.new("NodeGroupOutput")
    inp.location = (-400, 0)
    out.location = (400, 0)
    ng.inputs.new("NodeSocketVector", "N1")
    ng.inputs.new("NodeSocketVector", "N2")
    ng.outputs.new("NodeSocketVector", "OUT")
    sep1 = ng.nodes.new("ShaderNodeSeparateXYZ")
    sep2 = ng.nodes.new("ShaderNodeSeparateXYZ")
    sep1.location = (-200, 120)
    sep2.location = (-200, -80)
    ng.links.new(inp.outputs["N1"], sep1.inputs[0])
    ng.links.new(inp.outputs["N2"], sep2.inputs[0])
    mulx = ng.nodes.new("ShaderNodeMath"); mulx.operation = "MULTIPLY"
    muly = ng.nodes.new("ShaderNodeMath"); muly.operation = "MULTIPLY"
    addx = ng.nodes.new("ShaderNodeMath"); addx.operation = "ADD"
    addy = ng.nodes.new("ShaderNodeMath"); addy.operation = "ADD"
    mulx.location = (0, 220); muly.location = (0, 100); addx.location = (180, 220); addy.location = (180, 100)
    ng.links.new(sep1.outputs["X"], mulx.inputs[0]); ng.links.new(sep2.outputs["X"], mulx.inputs[1])
    ng.links.new(sep1.outputs["Y"], muly.inputs[0]); ng.links.new(sep2.outputs["Y"], muly.inputs[1])
    addxy = ng.nodes.new("ShaderNodeMath"); addxy.operation = "ADD"; addxy.location = (360, 160)
    ng.links.new(addx.outputs[0], addxy.inputs[0]); ng.links.new(addy.outputs[0], addxy.inputs[1])
    dot = ng.nodes.new("ShaderNodeVectorMath"); dot.operation = "DOT_PRODUCT"; dot.location = (0, -60)
    ng.links.new(inp.outputs["N1"], dot.inputs[0]); ng.links.new(inp.outputs["N2"], dot.inputs[1])
    sN2 = ng.nodes.new("ShaderNodeVectorMath"); sN2.operation = "SCALE"; sN2.location = (180, -60)
    ng.links.new(inp.outputs["N2"], sN2.inputs[0]); ng.links.new(dot.outputs[1], sN2.inputs[3])
    sN1z = ng.nodes.new("ShaderNodeCombineXYZ"); sN1z.location = (0, -220)
    sN1z.inputs["X"].default_value = 0.0; sN1z.inputs["Y"].default_value = 0.0
    sN1z.inputs["Z"].default_value = 1.0
    sub = ng.nodes.new("ShaderNodeVectorMath"); sub.operation = "SUBTRACT"; sub.location = (360, -60)
    ng.links.new(sN2.outputs[0], sub.inputs[0]); ng.links.new(sN1z.outputs[0], sub.inputs[1])
    mulv = ng.nodes.new("ShaderNodeVectorMath"); mulv.operation = "MULTIPLY"; mulv.location = (560, 40)
    ng.links.new(inp.outputs["N1"], mulv.inputs[0]); ng.links.new(sub.outputs[0], mulv.inputs[1])
    norm = ng.nodes.new("ShaderNodeVectorMath"); norm.operation = "NORMALIZE"; norm.location = (760, 40)
    ng.links.new(mulv.outputs[0], norm.inputs[0])
    ng.links.new(norm.outputs[0], out.inputs["OUT"])
    ng.links.new(sep1.outputs["X"], addx.inputs[0]); ng.links.new(sep2.outputs["X"], addx.inputs[1])
    ng.links.new(sep1.outputs["Y"], addy.inputs[0]); ng.links.new(sep2.outputs["Y"], addy.inputs[1])
    return ng

def _mk_attr_color(nt, names, loc):
    node = None
    if bpy.types.ShaderNodeVertexColor.is_registered_node_type():
        vc = nt.nodes.new("ShaderNodeVertexColor")
        vc.location = loc
        vc.layer_name = names[0]
        node = vc
    else:
        att = nt.nodes.new("ShaderNodeAttribute")
        att.location = loc
        att.attribute_name = names[0]
        node = att
    return node

def _set_attr_name(node, names):
    for nm in names:
        try:
            if hasattr(node, "layer_name"):
                node.layer_name = nm
            elif hasattr(node, "attribute_name"):
                node.attribute_name = nm
            return True
        except Exception:
            pass
    return False

def _make_img_node(nt, search_dirs, img_cache, missing_log, key_list, override_val, color_space, map_node, link_socket, logger, matname, debug):
    candidates = []
    if override_val:
        candidates.append({"value": override_val, "value_hash": None})
    for e in key_list or []:
        k = (e.get("key") or "").lower()
        v = e.get("value") or None
        if v:
            candidates.append({"value": v, "value_hash": e.get("value_hash")})
    img_node = nt.nodes.new("ShaderNodeTexImage")
    if map_node:
        nt.links.new(map_node.outputs["Vector"], img_node.inputs["Vector"])
    resolved = None
    used = None
    used_hash = None
    for ent in candidates:
        stem = ent.get("value")
        vh = ent.get("value_hash")
        if stem:
            img, path = _find_by_stem(stem, search_dirs, img_cache)
            if img:
                try:
                    img.colorspace_settings.name = color_space
                except Exception:
                    pass
                img_node.image = img
                if link_socket:
                    link_socket(img_node)
                resolved = os.path.basename(path)
                used = stem
                break
            else:
                if missing_log is not None:
                    missing_log.append(("name", stem, [*search_dirs], matname, False))
        if vh is not None:
            img2, path2 = _find_by_hash(vh, search_dirs, img_cache)
            if img2:
                try:
                    img2.colorspace_settings.name = color_space
                except Exception:
                    pass
                img_node.image = img2
                if link_socket:
                    link_socket(img_node)
                resolved = os.path.basename(path2)
                used_hash = vh
                if missing_log is not None:
                    missing_log.append(("hash", f"0x{int(vh)&0xFFFFFFFF:08X}", [*search_dirs], matname, True))
                break
    return img_node, resolved, used, used_hash

def _mk_mapping(nt, uv_name, loc):
    uvn = None
    mapn = None
    if uv_name:
        uvn = nt.nodes.new("ShaderNodeUVMap")
        uvn.uv_map = uv_name
        uvn.location = (loc[0], loc[1])
        mapn = nt.nodes.new("ShaderNodeMapping")
        mapn.location = (loc[0] + 180, loc[1])
        nt.links.new(uvn.outputs["UV"], mapn.inputs["Vector"])
    return mapn

def _apply_tile_ofs(mapn, tile, ofs):
    if not mapn:
        return
    try:
        sx = float(tile[0]) if isinstance(tile, (tuple, list)) and len(tile) >= 2 else float(tile)
    except Exception:
        sx = 1.0
    try:
        sy = float(tile[1]) if isinstance(tile, (tuple, list)) and len(tile) >= 2 else float(tile)
    except Exception:
        sy = 1.0
    try:
        ox = float(ofs[0]) if isinstance(ofs, (tuple, list)) and len(ofs) >= 2 else float(ofs)
    except Exception:
        ox = 0.0
    try:
        oy = float(ofs[1]) if isinstance(ofs, (tuple, list)) and len(ofs) >= 2 else float(ofs)
    except Exception:
        oy = 0.0
    try:
        mapn.inputs["Scale"].default_value[0] = sx
        mapn.inputs["Scale"].default_value[1] = sy
        mapn.inputs["Location"].default_value[0] = ox
        mapn.inputs["Location"].default_value[1] = oy
    except Exception:
        pass

def _build_supermix(nt, m, bsdf, uv_name, entries, streams, search_dirs, img_cache, missing_log, debug, logger, matname):
    rnm_group = _ensure_group_rnm()
    attr_names = ["Col", "colorSet1", "Color", "COLOR", "col"]
    attr = _mk_attr_color(nt, attr_names, (-1200, 360))
    sep_rgb = nt.nodes.new("ShaderNodeSeparateRGB")
    sep_rgb.location = (-980, 360)
    if hasattr(attr, "outputs") and "Color" in attr.outputs:
        nt.links.new(attr.outputs["Color"], sep_rgb.inputs["Image"])
    else:
        if hasattr(attr, "outputs") and "Fac" in attr.outputs:
            crgb = nt.nodes.new("ShaderNodeCombineRGB")
            crgb.location = (-1100, 360)
            nt.links.new(attr.outputs["Fac"], crgb.inputs["R"])
            nt.links.new(attr.outputs["Fac"], crgb.inputs["G"])
            nt.links.new(attr.outputs["Fac"], crgb.inputs["B"])
            nt.links.new(crgb.outputs["Image"], sep_rgb.inputs["Image"])
    map_base = _mk_mapping(nt, uv_name, (-1120, 40))
    params = _extract_params(streams)
    tile = params.get("tileuv", (1.0, 1.0))
    ofs = params.get("offsetuv", (0.0, 0.0))
    _apply_tile_ofs(map_base, tile, ofs)
    base_keys = [e for e in (entries or []) if (e.get("key") or "").lower() in {"diffusemap","albedomap","basecolormap","albedo","basecolor","colormap","color","diffuse","diffusemap1","diffusemap2","diffusemap3","diffusemap4"}]
    norm_keys = [e for e in (entries or []) if (e.get("key") or "").lower() in {"normalmap","bumpmap","normal","normalmap1","normalmap2","normalmap3","normalmap4"}]
    d_list = [[], [], [], []]
    n_list = [[], [], [], []]
    for e in base_keys:
        k = (e.get("key") or "").lower()
        idx = 0
        if "1" in k: idx = 0
        elif "2" in k: idx = 1
        elif "3" in k: idx = 2
        elif "4" in k: idx = 3
        d_list[idx].append(e)
    for e in norm_keys:
        k = (e.get("key") or "").lower()
        idx = 0
        if "1" in k: idx = 0
        elif "2" in k: idx = 1
        elif "3" in k: idx = 2
        elif "4" in k: idx = 3
        n_list[idx].append(e)
    col_nodes = []
    for i in range(4):
        def _link_color(img_node):
            def _f(tex):
                pass
            def _link(tex_node):
                return
            return _f
        img_node, _, _, _ = _make_img_node(
            nt, search_dirs, img_cache, missing_log, d_list[i], None, "sRGB", map_base,
            lambda tex: None, logger, matname, debug
        )
        col_nodes.append(img_node)
    mix12 = nt.nodes.new("ShaderNodeMixRGB"); mix12.location = (-200, 420)
    nt.links.new(sep_rgb.outputs["R"], mix12.inputs["Fac"])
    nt.links.new(col_nodes[0].outputs["Color"], mix12.inputs["Color1"])
    nt.links.new(col_nodes[1].outputs["Color"], mix12.inputs["Color2"])
    mix123 = nt.nodes.new("ShaderNodeMixRGB"); mix123.location = (0, 420)
    nt.links.new(sep_rgb.outputs["G"], mix123.inputs["Fac"])
    nt.links.new(mix12.outputs["Color"], mix123.inputs["Color1"])
    nt.links.new(col_nodes[2].outputs["Color"], mix123.inputs["Color2"])
    mix1234 = nt.nodes.new("ShaderNodeMixRGB"); mix1234.location = (200, 420)
    nt.links.new(sep_rgb.outputs["B"], mix1234.inputs["Fac"])
    nt.links.new(mix123.outputs["Color"], mix1234.inputs["Color1"])
    nt.links.new(col_nodes[3].outputs["Color"], mix1234.inputs["Color2"])
    nt.links.new(mix1234.outputs["Color"], bsdf.inputs["Base Color"])
    def _mk_normal(tex_entries):
        img_n, _, _, _ = _make_img_node(
            nt, search_dirs, img_cache, missing_log, tex_entries, None, "Non-Color", map_base,
            lambda tex: None, logger, matname, debug
        )
        nmap = nt.nodes.new("ShaderNodeNormalMap"); nmap.location = (img_n.location.x + 220, img_n.location.y)
        nt.links.new(img_n.outputs["Color"], nmap.inputs["Color"])
        return nmap.outputs["Normal"]
    n1 = _mk_normal(n_list[0])
    n2 = _mk_normal(n_list[1])
    n3 = _mk_normal(n_list[2])
    n4 = _mk_normal(n_list[3])
    acc = n1
    def _step(acc_norm, nxt_norm, fac, x):
        rnm = nt.nodes.new("ShaderNodeGroup"); rnm.node_tree = rnm_group; rnm.location = (x, 40)
        nt.links.new(acc_norm, rnm.inputs["N1"]); nt.links.new(nxt_norm, rnm.inputs["N2"])
        mx = nt.nodes.new("ShaderNodeMixRGB"); mx.location = (x + 180, 40)
        nt.links.new(fac, mx.inputs["Fac"])
        nt.links.new(acc_norm, mx.inputs["Color1"])
        nt.links.new(rnm.outputs["OUT"], mx.inputs["Color2"])
        return mx.outputs["Color"]
    acc = _step(acc, n2, sep_rgb.outputs["R"], -120)
    acc = _step(acc, n3, sep_rgb.outputs["G"], 80)
    acc = _step(acc, n4, sep_rgb.outputs["B"], 280)
    nt.links.new(acc, bsdf.inputs["Normal"])
    try:
        m.blend_method = "OPAQUE"
        m.shadow_method = "OPAQUE"
    except Exception:
        pass

def _build_submix(nt, m, bsdf, uv_name, entries, streams, search_dirs, img_cache, missing_log, debug, logger, matname):
    map_base = _mk_mapping(nt, uv_name, (-1120, 40))
    params = _extract_params(streams)
    tile = params.get("tileuv", (1.0, 1.0))
    ofs = params.get("offsetuv", (0.0, 0.0))
    _apply_tile_ofs(map_base, tile, ofs)
    base_keys = [e for e in (entries or []) if (e.get("key") or "").lower() in {"diffusemap","albedomap","basecolormap","albedo","basecolor","colormap","color","diffuse","diffusemap1","diffusemap2"}]
    norm_keys = [e for e in (entries or []) if (e.get("key") or "").lower() in {"normalmap","bumpmap","normal","normalmap1","normalmap2"}]
    d1 = [e for e in base_keys if "2" not in (e.get("key") or "").lower()]
    d2 = [e for e in base_keys if "2" in (e.get("key") or "").lower()]
    n1 = [e for e in norm_keys if "2" not in (e.get("key") or "").lower()]
    n2 = [e for e in norm_keys if "2" in (e.get("key") or "").lower()]
    attr = _mk_attr_color(nt, ["Col","colorSet1","Color","COLOR","col"], (-1200, 360))
    sep = nt.nodes.new("ShaderNodeSeparateRGB"); sep.location = (-980, 360)
    if hasattr(attr, "outputs") and "Color" in attr.outputs:
        nt.links.new(attr.outputs["Color"], sep.inputs["Image"])
    c1, _, _, _ = _make_img_node(nt, search_dirs, img_cache, missing_log, d1, None, "sRGB", map_base, lambda t: None, logger, matname, debug)
    c2, _, _, _ = _make_img_node(nt, search_dirs, img_cache, missing_log, d2, None, "sRGB", map_base, lambda t: None, logger, matname, debug)
    mx = nt.nodes.new("ShaderNodeMixRGB"); mx.location = (-200, 420)
    nt.links.new(sep.outputs["R"], mx.inputs["Fac"])
    nt.links.new(c1.outputs["Color"], mx.inputs["Color1"])
    nt.links.new(c2.outputs["Color"], mx.inputs["Color2"])
    nt.links.new(mx.outputs["Color"], bsdf.inputs["Base Color"])
    def _mk_normal(tex_entries):
        img_n, _, _, _ = _make_img_node(nt, search_dirs, img_cache, missing_log, tex_entries, None, "Non-Color", map_base, lambda t: None, logger, matname, debug)
        nmap = nt.nodes.new("ShaderNodeNormalMap"); nmap.location = (img_n.location.x + 220, img_n.location.y)
        nt.links.new(img_n.outputs["Color"], nmap.inputs["Color"])
        return nmap.outputs["Normal"]
    nn1 = _mk_normal(n1)
    nn2 = _mk_normal(n2)
    rnm_group = _ensure_group_rnm()
    rnm = nt.nodes.new("ShaderNodeGroup"); rnm.node_tree = rnm_group; rnm.location = (-40, 40)
    nt.links.new(nn1, rnm.inputs["N1"]); nt.links.new(nn2, rnm.inputs["N2"])
    mxn = nt.nodes.new("ShaderNodeMixRGB"); mxn.location = (140, 40)
    nt.links.new(sep.outputs["R"], mxn.inputs["Fac"])
    nt.links.new(nn1, mxn.inputs["Color1"])
    nt.links.new(rnm.outputs["OUT"], mxn.inputs["Color2"])
    nt.links.new(mxn.outputs["Color"], bsdf.inputs["Normal"])
    try:
        m.blend_method = "OPAQUE"
        m.shadow_method = "OPAQUE"
    except Exception:
        pass

def _stem_sanitized(fname):
    st = os.path.splitext(fname)[0]
    st = re.sub(r'([._-])?[DN]$', '', st, flags=re.IGNORECASE)
    return st

def make_principled_material(name, mat_entries, streams, uv_name, search_dirs, img_cache, mat_cache, missing_log, debug=False, mesh_name=None, cache_id=None, override_base=None, override_norm=None, logger=None):
    key = (cache_id or name or "BMDL_MAT", uv_name or "", tuple(search_dirs))
    m = mat_cache.get(key)
    if m and m.users >= 0:
        return m
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
    uv_base = _mk_mapping(nt, uv_name, (-1120, 40))
    params = _extract_params(streams)
    tile = params.get("tileuv", (1.0, 1.0))
    ofs  = params.get("offsetuv", (0.0, 0.0))
    _apply_tile_ofs(uv_base, tile, ofs)
    base_keys_all = [e for e in (mat_entries or []) if (e.get("key") or "").lower() in {"diffusemap","albedomap","basecolormap","albedo","basecolor","colormap","color","diffuse","diffusemap1","diffusemap2","diffusemap3","diffusemap4"}]
    norm_keys_all = [e for e in (mat_entries or []) if (e.get("key") or "").lower() in {"normalmap","bumpmap","normal","normalmap1","normalmap2","normalmap3","normalmap4"}]
    is_supermix = (name or "").lower().startswith("labssupermix") or any("diffusemap2" in (e.get("key") or "").lower() for e in base_keys_all) or any("normalmap2" in (e.get("key") or "").lower() for e in norm_keys_all)
    is_submix = (name or "").lower().startswith("labssubmix") or any("diffusemap2" in (e.get("key") or "").lower() for e in base_keys_all)
    if is_supermix:
        _build_supermix(nt, m, bsdf, uv_name, mat_entries, streams, search_dirs, img_cache, missing_log, debug, logger if logger else (lambda s: None), name or "labsSuperMix")
    elif is_submix:
        _build_submix(nt, m, bsdf, uv_name, mat_entries, streams, search_dirs, img_cache, missing_log, debug, logger if logger else (lambda s: None), name or "labsSubMix")
    else:
        def link_color(tex):
            _force_ignore_alpha(tex.image) if tex and tex.image else None
            nt.links.new(tex.outputs["Color"], bsdf.inputs.get("Base Color"))
        img_base, resolved_b, _, _ = _make_img_node(nt, search_dirs, img_cache, missing_log, base_keys_all, override_base, "sRGB", uv_base, link_color, logger, name, debug)
        def link_normal(tex):
            pass
        img_norm, _, _, _ = _make_img_node(nt, search_dirs, img_cache, missing_log, norm_keys_all, override_norm, "Non-Color", uv_base, link_normal, logger, name, debug)
        if img_norm:
            nmap = nt.nodes.new("ShaderNodeNormalMap"); nmap.location = (img_norm.location.x + 220, img_norm.location.y)
            nt.links.new(img_norm.outputs["Color"], nmap.inputs["Color"])
            nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
        prefer = resolved_b
        if prefer:
            try:
                m.name = _stem_sanitized(prefer)
            except Exception:
                pass
    mat_cache[key] = m
    return m
