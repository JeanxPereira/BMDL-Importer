import bpy
import os
import re
import time
from .bmdl_core import _extract_params

# ============================================================================
# Data-driven material — math derived 1:1 from the real labs fragments
# (CompiledMaterials/materials_shader_fragments~). See docs/BMDL_MATERIALS.md.
#
# Backbone (deferred -> forward approximation in Blender):
#   - Normal map is PACKED (swizzle .agbr): R=gloss  G=normalY  B=specExp  A=normalX
#   - diffuse.ALPHA = emissive/glow mask
#   - albedo  = diffuseTex.rgb * DiffuseTint * DiffLevel (* vertexColor for VertColor)
#   - specular = SpecularTint * SpecLevel   (=0 => matte)
#   - reflective: cubemap(reflect) * ReflectTint*ReflectLevel * gloss   (masked by gloss)
#   - emissive = albedo * diffuse.a * EmissiveLevel
# ============================================================================

DIFFUSE_KEYS = {"diffusemap", "albedomap", "basecolormap", "albedo", "basecolor", "colormap", "color", "diffuse"}
NORMAL_KEYS = {"normalmap", "bumpmap", "normal"}


def palette_color(i):
    x = (i * 1103515245 + 12345) & 0xFFFFFFFF
    return ((x >> 16) & 255) / 255.0, ((x >> 8) & 255) / 255.0, (x & 255) / 255.0, 1.0


def _set_opaque(m):
    for attr, val in (("blend_method", "OPAQUE"), ("shadow_method", "OPAQUE")):
        if hasattr(m, attr):
            try: setattr(m, attr, val)
            except Exception: pass

def _set_blended(m, clip=False):
    if hasattr(m, "blend_method"):
        try: m.blend_method = "CLIP" if clip else "BLEND"
        except Exception: pass
    if hasattr(m, "surface_render_method"):
        try: m.surface_render_method = "DITHERED" if clip else "BLENDED"
        except Exception: pass
    if hasattr(m, "show_transparent_back"):
        try: m.show_transparent_back = False
        except Exception: pass

def _set_in(node, names, value):
    for n in names:
        if n in node.inputs:
            try:
                node.inputs[n].default_value = value
                return True
            except Exception:
                pass
    return False

def _link_in(nt, socket, node, names):
    for n in names:
        if n in node.inputs:
            try:
                nt.links.new(socket, node.inputs[n]); return True
            except Exception:
                pass
    return False


def ensure_empty_material(name):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (300, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (0, 0)
    _set_opaque(m)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m

def ensure_uv_debug_material(uv_name):
    mat = bpy.data.materials.get("DS_DEBUG_UV") or bpy.data.materials.new("DS_DEBUG_UV")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (400, 0)
    emis = nt.nodes.new("ShaderNodeEmission"); emis.location = (200, 0)
    uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.uv_map = uv_name; uvn.location = (-400, 0)
    chk = nt.nodes.new("ShaderNodeTexChecker"); chk.location = (-150, 0)
    nt.links.new(uvn.outputs["UV"], chk.inputs["Vector"])
    nt.links.new(chk.outputs["Color"], emis.inputs["Color"])
    nt.links.new(emis.outputs["Emission"], out.inputs["Surface"])
    return mat


# ---- texture lookup / loading ----------------------------------------------
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
            if c.lower() in s:
                return os.path.join(cur, s[c.lower()])
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
                    return _load_image_cached(path, img_cache), path
    return None, None

def _find_by_hash(value_hash, search_dirs, img_cache, max_depth=5):
    if value_hash is None:
        return None, None
    hx = f"{int(value_hash) & 0xFFFFFFFF:08X}"
    for sd in search_dirs:
        for cur, files in _iter_with_depth(sd, max_depth):
            for fname in files:
                stem, _ = os.path.splitext(fname)
                s = stem.upper()
                if s == hx or s == f"0X{hx}" or hx in s:
                    img = _load_image_cached(os.path.join(cur, fname), img_cache)
                    if img:
                        return img, os.path.join(cur, fname)
    return None, None

def search_roots_for(p, settings):
    roots = []
    if not settings.get("import_textures"):
        return roots
    if settings.get("use_custom_texture_dir"):
        td = settings.get("textures_dir") or ""
        if td and os.path.isdir(os.path.abspath(td)):
            roots.append(os.path.abspath(td))
    base = os.path.abspath(os.path.dirname(p))
    for up in ["", "..", os.path.join("..", ".."), os.path.join("..", "..", "..")]:
        updir = os.path.abspath(os.path.normpath(os.path.join(base, up)))
        for nm in ["~animations", "animations~"]:
            c = os.path.abspath(os.path.normpath(os.path.join(updir, nm)))
            if os.path.isdir(c):
                roots.append(c)
    seen, uniq = set(), []
    for r in roots:
        if r not in seen:
            uniq.append(r); seen.add(r)
    return uniq

def write_missing_log(base_path, missings):
    if not missings:
        return
    log_path = os.path.join(os.path.dirname(base_path),
                            os.path.splitext(os.path.basename(base_path))[0] + ".darkspore_import.missing_textures.log.txt")
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] file={os.path.basename(base_path)}\n")
            found = missing = 0
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


# ---- node helpers ----------------------------------------------------------
def _mk_attr_color(nt, names, loc):
    if bpy.types.ShaderNodeVertexColor.is_registered_node_type():
        vc = nt.nodes.new("ShaderNodeVertexColor"); vc.location = loc; vc.layer_name = names[0]
        return vc
    att = nt.nodes.new("ShaderNodeAttribute"); att.location = loc; att.attribute_name = names[0]
    return att

def _mk_mapping(nt, uv_name, loc):
    if not uv_name:
        return None
    uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.uv_map = uv_name; uvn.location = (loc[0], loc[1])
    mapn = nt.nodes.new("ShaderNodeMapping"); mapn.location = (loc[0] + 180, loc[1])
    nt.links.new(uvn.outputs["UV"], mapn.inputs["Vector"])
    return mapn

def _apply_tile_ofs(mapn, tile, ofs):
    if not mapn:
        return
    def _xy(v, d0, d1):
        if isinstance(v, (tuple, list)):
            a = float(v[0]) if len(v) >= 1 else d0
            b = float(v[1]) if len(v) >= 2 else a
            return a, b
        try:
            f = float(v); return f, f
        except Exception:
            return d0, d1
    sx, sy = _xy(tile, 1.0, 1.0); ox, oy = _xy(ofs, 0.0, 0.0)
    try:
        mapn.inputs["Scale"].default_value[0] = sx
        mapn.inputs["Scale"].default_value[1] = sy
        mapn.inputs["Location"].default_value[0] = ox
        mapn.inputs["Location"].default_value[1] = oy
    except Exception:
        pass

def _make_img_node(nt, search_dirs, img_cache, missing_log, key_list, override_val, color_space, map_node, matname):
    candidates = []
    if override_val:
        candidates.append({"value": override_val, "value_hash": None})
    for e in key_list or []:
        v = e.get("value") or None
        if v:
            candidates.append({"value": v, "value_hash": e.get("value_hash")})
    img_node = nt.nodes.new("ShaderNodeTexImage")
    if map_node:
        nt.links.new(map_node.outputs["Vector"], img_node.inputs["Vector"])
    resolved = None
    for ent in candidates:
        stem, vh = ent.get("value"), ent.get("value_hash")
        if stem:
            img, path = _find_by_stem(stem, search_dirs, img_cache)
            if img:
                try: img.colorspace_settings.name = color_space
                except Exception: pass
                img_node.image = img; resolved = os.path.basename(path); break
            elif missing_log is not None:
                missing_log.append(("name", stem, [*search_dirs], matname, False))
        if vh is not None:
            img2, path2 = _find_by_hash(vh, search_dirs, img_cache)
            if img2:
                try: img2.colorspace_settings.name = color_space
                except Exception: pass
                img_node.image = img2; resolved = os.path.basename(path2)
                if missing_log is not None:
                    missing_log.append(("hash", f"0x{int(vh)&0xFFFFFFFF:08X}", [*search_dirs], matname, True))
                break
    return img_node, resolved


# ---- param helpers ---------------------------------------------------------
def _classify(shader):
    s = (shader or "").lower()
    if s == "model":          return "legacy"
    if s == "labsid":         return "id"
    if "supermix" in s:       return "supermix"
    if "submix" in s:         return "submix"
    if "crystal" in s:        return "crystal"
    if "puddle" in s:         return "puddle"
    if "chrome" in s or "tech" in s:  return "reflective"
    if "flora" in s:          return "flora"
    if "cutout" in s:         return "cutout"
    if "volumefog" in s:      return "fog"
    if any(k in s for k in ("unlit", "sunbeam", "spacedome", "sphere")):
        return "unlit"
    if s == "labssimple":     return "simple"
    return "lit"

def _flag(shader, token):
    return token in (shader or "").lower()

def _getf(params, name, default):
    v = params.get(name)
    if isinstance(v, (tuple, list)):
        return float(v[0]) if v else default
    try:
        return float(v) if v is not None else default
    except Exception:
        return default

def _getrgb(params, name, default=(1.0, 1.0, 1.0)):
    v = params.get(name)
    if isinstance(v, (tuple, list)):
        t = tuple(float(x) for x in v[:3])
        if len(t) == 1: return (t[0], t[0], t[0])
        if len(t) == 2: return (t[0], t[1], 0.0)
        return t
    if v is None:
        return default
    try:
        f = float(v); return (f, f, f)
    except Exception:
        return default

def _entries(entries, keyset):
    return [e for e in (entries or []) if (e.get("key") or "").lower() in keyset]

def _mapping(ctx, tile="TileUV", off="OffsetUV", loc=(-1200, 0)):
    mapn = _mk_mapping(ctx["nt"], ctx["uv_name"], loc)
    _apply_tile_ofs(mapn, ctx["params"].get(tile, (1.0, 1.0)), ctx["params"].get(off, (0.0, 0.0)))
    return mapn

def _img(ctx, keyset, color_space, mapn, override=None):
    node, resolved = _make_img_node(ctx["nt"], ctx["search_dirs"], ctx["img_cache"], ctx["missing_log"],
                                    _entries(ctx["entries"], keyset), override, color_space, mapn, ctx["matname"])
    return (node, resolved) if node.image is not None else (None, None)

def _vertex_color(ctx, loc=(-1500, 400)):
    # io_mesh creates the vertex-color layer named "Col" (= the game's colorSet1)
    nm = ctx.get("vcol_name") or "Col"
    return _mk_attr_color(ctx["nt"], [nm, "Col", "colorSet1", "Color", "COLOR", "col"], loc)

def _tint(ctx, src, rgb, loc):
    if rgb == (1.0, 1.0, 1.0):
        return src
    nt = ctx["nt"]
    mix = nt.nodes.new("ShaderNodeMixRGB"); mix.blend_type = "MULTIPLY"
    mix.inputs["Fac"].default_value = 1.0; mix.location = loc
    nt.links.new(src, mix.inputs["Color1"])
    mix.inputs["Color2"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    return mix.outputs["Color"]

def _mulcol(ctx, a, b, loc):
    nt = ctx["nt"]
    mix = nt.nodes.new("ShaderNodeMixRGB"); mix.blend_type = "MULTIPLY"
    mix.inputs["Fac"].default_value = 1.0; mix.location = loc
    nt.links.new(a, mix.inputs["Color1"]); nt.links.new(b, mix.inputs["Color2"])
    return mix.outputs["Color"]

def _packed_normal(ctx, img_node, level, loc=(-500, -250)):
    """Packed normal map (.agbr): R=gloss G=normalY B=specExp A=normalX.
    Returns (normal_socket, gloss_socket, specExp_socket)."""
    nt = ctx["nt"]
    sep = nt.nodes.new("ShaderNodeSeparateColor"); sep.location = (loc[0], loc[1])
    nt.links.new(img_node.outputs["Color"], sep.inputs["Color"])
    comb = nt.nodes.new("ShaderNodeCombineColor"); comb.location = (loc[0] + 180, loc[1])
    nt.links.new(img_node.outputs["Alpha"], comb.inputs["Red"])   # normalX = A
    nt.links.new(sep.outputs["Green"], comb.inputs["Green"])      # normalY = G
    comb.inputs["Blue"].default_value = 1.0
    nmap = nt.nodes.new("ShaderNodeNormalMap"); nmap.location = (loc[0] + 360, loc[1])
    try: nmap.inputs["Strength"].default_value = float(level)
    except Exception: pass
    nt.links.new(comb.outputs["Color"], nmap.inputs["Color"])
    return nmap.outputs["Normal"], sep.outputs["Red"], sep.outputs["Blue"]

def _roughness_from_gloss(ctx, gloss, loc=(150, -260)):
    nt = ctx["nt"]
    inv = nt.nodes.new("ShaderNodeMath"); inv.operation = "SUBTRACT"; inv.location = loc
    inv.inputs[0].default_value = 1.0
    nt.links.new(gloss, inv.inputs[1])
    return inv.outputs["Value"]


# ============================================================================
# Per-family builders
# ============================================================================
def _principled(ctx, x=520):
    nt = ctx["nt"]
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (x, 0)
    return bsdf

def _surface_diffuse_normal(ctx, bsdf, vcolor_mul=True):
    """diffuse(+tint+vcolor) -> Base Color; packed normal -> Normal/Roughness;
    specular from SpecularTint*SpecLevel; emissive from diffuse.a*EmissiveLevel."""
    nt = ctx["nt"]; params = ctx["params"]; shader = ctx["shader"]
    mapn = _mapping(ctx)
    dnode, resolved = _img(ctx, DIFFUSE_KEYS, "sRGB", mapn, ctx.get("override_base"))
    diff_rgb = None; diff_a = None
    if dnode is not None:
        diff_rgb = dnode.outputs["Color"]; diff_a = dnode.outputs["Alpha"]
    # base color = diffuse * DiffuseTint*DiffLevel (* vertexColor)
    dt = _getrgb(params, "DiffuseTint", (1, 1, 1))
    dl = _getf(params, "DiffLevel", 1.0)
    tint = (dt[0] * dl, dt[1] * dl, dt[2] * dl)
    base = diff_rgb
    if base is not None:
        base = _tint(ctx, base, tint, (-300, 300))
        if vcolor_mul and _flag(shader, "vertcolor"):
            vc = _vertex_color(ctx, (-700, 480))
            base = _mulcol(ctx, base, vc.outputs["Color"], (-100, 360))
        nt.links.new(base, bsdf.inputs["Base Color"])
    else:
        _set_in(bsdf, ["Base Color"], (tint[0], tint[1], tint[2], 1.0))

    # packed normal
    nnode, _ = _img(ctx, NORMAL_KEYS, "Non-Color", mapn, ctx.get("override_norm"))
    if nnode is not None:
        nrm, gloss, _spec = _packed_normal(ctx, nnode, _getf(params, "NormalLevel", 1.0))
        nt.links.new(nrm, bsdf.inputs["Normal"])
        nt.links.new(_roughness_from_gloss(ctx, gloss), bsdf.inputs["Roughness"])
        ctx["_gloss"] = gloss
    else:
        _set_in(bsdf, ["Roughness"], 0.6)

    # specular
    st = _getrgb(params, "SpecularTint", (0, 0, 0))
    sl = _getf(params, "SpecLevel", 1.0)
    if st == (0, 0, 0):
        _set_in(bsdf, ["Specular IOR Level", "Specular"], 0.0)
    else:
        _set_in(bsdf, ["Specular IOR Level", "Specular"], min(max(sl, 0.0) * 0.5, 1.0))
        _set_in(bsdf, ["Specular Tint"], (st[0], st[1], st[2], 1.0))
    _set_in(bsdf, ["Metallic"], 0.0)

    # emissive = diffuse.rgb * diffuse.a * EmissiveLevel  (diffuse.a = glow mask)
    emi = _getf(params, "EmissiveLevel", 0.0)
    if emi > 0.0 and diff_rgb is not None and diff_a is not None:
        glow = _mulcol(ctx, base if base is not None else diff_rgb, _alpha_as_color(ctx, diff_a, (-100, -480)), (120, -440))
        _link_in(nt, glow, bsdf, ["Emission Color", "Emission"])
        _set_in(bsdf, ["Emission Strength"], emi)
    return diff_rgb, diff_a, resolved

def _alpha_as_color(ctx, alpha_socket, loc):
    nt = ctx["nt"]
    c = nt.nodes.new("ShaderNodeCombineColor"); c.location = loc
    for ch in ("Red", "Green", "Blue"):
        nt.links.new(alpha_socket, c.inputs[ch])
    return c.outputs["Color"]


def _b_lit(ctx, cutout=False):
    nt = ctx["nt"]; m = ctx["m"]
    bsdf = _principled(ctx)
    nt.links.new(bsdf.outputs["BSDF"], ctx["out"].inputs["Surface"])
    diff_rgb, diff_a, _ = _surface_diffuse_normal(ctx, bsdf)
    if cutout and diff_a is not None:
        nt.links.new(diff_a, bsdf.inputs["Alpha"]); _set_blended(m, clip=True)
    else:
        _set_opaque(m)

def _b_reflective(ctx):
    """chrome/tech: lit + reflection masked by gloss * ReflectTint*ReflectLevel."""
    nt = ctx["nt"]; m = ctx["m"]; params = ctx["params"]
    bsdf = _principled(ctx, 520)
    diff_rgb, diff_a, _ = _surface_diffuse_normal(ctx, bsdf)
    surface = bsdf.outputs["BSDF"]
    env_node, _ = _img(ctx, {"envmap", "skymap"}, "sRGB", None)
    rlevel = _getf(params, "ReflectLevel", 0.0)
    rtint = _getrgb(params, "ReflectTint", (1, 1, 1))
    gloss = ctx.get("_gloss")
    if rlevel > 0.0:
        # glossy environment reflection, tinted and masked by gloss*ReflectLevel
        glossy = nt.nodes.new("ShaderNodeBsdfGlossy"); glossy.location = (520, -360)
        glossy.inputs["Color"].default_value = (rtint[0], rtint[1], rtint[2], 1.0)
        if gloss is not None:
            nt.links.new(_roughness_from_gloss(ctx, gloss, (300, -420)), glossy.inputs["Roughness"])
        else:
            glossy.inputs["Roughness"].default_value = 0.15
        if env_node is not None:
            # use the envMap as the reflection colour (sampled by the reflection vector)
            tc = nt.nodes.new("ShaderNodeTexCoord"); tc.location = (-300, -650)
            nt.links.new(tc.outputs["Reflection"], env_node.inputs["Vector"])
            env_t = _tint(ctx, env_node.outputs["Color"], rtint, (200, -650))
            glossy.inputs["Color"].default_value = (1, 1, 1, 1)
            nt.links.new(env_t, glossy.inputs["Color"])
        mix = nt.nodes.new("ShaderNodeMixShader"); mix.location = (820, 0)
        fac = min(max(rlevel, 0.0), 1.0)
        if gloss is not None:
            mfac = nt.nodes.new("ShaderNodeMath"); mfac.operation = "MULTIPLY"; mfac.location = (600, -200)
            mfac.inputs[1].default_value = fac
            nt.links.new(gloss, mfac.inputs[0])
            nt.links.new(mfac.outputs["Value"], mix.inputs["Fac"])
        else:
            mix.inputs["Fac"].default_value = fac
        nt.links.new(bsdf.outputs["BSDF"], mix.inputs[1])
        nt.links.new(glossy.outputs["BSDF"], mix.inputs[2])
        surface = mix.outputs["Shader"]
    nt.links.new(surface, ctx["out"].inputs["Surface"])
    _set_opaque(m)

def _b_crystal(ctx):
    nt = ctx["nt"]; m = ctx["m"]; params = ctx["params"]
    bsdf = _principled(ctx)
    nt.links.new(bsdf.outputs["BSDF"], ctx["out"].inputs["Surface"])
    diff_rgb, diff_a, _ = _surface_diffuse_normal(ctx, bsdf)
    # refraction + fresnel reflection -> glass transmission
    _set_in(bsdf, ["Transmission Weight", "Transmission"], min(max(_getf(params, "RefractLevel", 0.5), 0.0), 1.0))
    rt = _getrgb(params, "RefractTint", (1, 1, 1))
    _set_in(bsdf, ["Base Color"], (rt[0], rt[1], rt[2], 1.0)) if diff_rgb is None else None
    _set_in(bsdf, ["Roughness"], 0.05)
    _set_in(bsdf, ["IOR"], 1.45)
    _set_blended(m)

def _b_supermix(ctx):
    """4 layers: weighted sum by NORMALISED vertexColor RGBA; per-layer tile/tint."""
    nt = ctx["nt"]; m = ctx["m"]; params = ctx["params"]
    bsdf = _principled(ctx, 760)
    nt.links.new(bsdf.outputs["BSDF"], ctx["out"].inputs["Surface"])
    vc = _vertex_color(ctx, (-1700, 500))
    # normalise weights: w = color / (r+g+b+a)
    sep = nt.nodes.new("ShaderNodeSeparateColor"); sep.location = (-1500, 560)
    nt.links.new(vc.outputs["Color"], sep.inputs["Color"])
    # sum r+g+b (SeparateColor has no alpha output; use rgb + vc.Alpha)
    addrgb = nt.nodes.new("ShaderNodeVectorMath"); addrgb.operation = "DOT_PRODUCT"; addrgb.location = (-1300, 560)
    nt.links.new(vc.outputs["Color"], addrgb.inputs[0]); addrgb.inputs[1].default_value = (1, 1, 1)
    sumn = nt.nodes.new("ShaderNodeMath"); sumn.operation = "ADD"; sumn.location = (-1120, 560)
    nt.links.new(addrgb.outputs["Value"], sumn.inputs[0])
    nt.links.new(vc.outputs["Alpha"], sumn.inputs[1])
    addeps = nt.nodes.new("ShaderNodeMath"); addeps.operation = "ADD"; addeps.location = (-960, 560)
    nt.links.new(sumn.outputs["Value"], addeps.inputs[0]); addeps.inputs[1].default_value = 0.001
    def weight(chan_socket, y):
        d = nt.nodes.new("ShaderNodeMath"); d.operation = "DIVIDE"; d.location = (-780, y)
        nt.links.new(chan_socket, d.inputs[0]); nt.links.new(addeps.outputs["Value"], d.inputs[1])
        return d.outputs["Value"]
    w = [weight(sep.outputs["Red"], 700), weight(sep.outputs["Green"], 560),
         weight(sep.outputs["Blue"], 420), weight(vc.outputs["Alpha"], 280)]
    # layers
    acc = None
    for i in range(4):
        suf = str(i + 1)
        mapn = _mapping(ctx, f"Tile{suf}UV", f"Offset{suf}UV", (-1150, 100 - i * 280))
        dimg, _ = _img(ctx, {f"diffusemap{suf}"}, "sRGB", mapn)
        if dimg is not None:
            csock = _tint(ctx, dimg.outputs["Color"], _getrgb(params, f"DiffuseTint{suf}", (1, 1, 1)), (-650, 120 - i * 280))
        else:
            t = _getrgb(params, f"DiffuseTint{suf}", (0.4, 0.4, 0.4))
            rgb = nt.nodes.new("ShaderNodeRGB"); rgb.location = (-650, 120 - i * 280)
            rgb.outputs[0].default_value = (t[0], t[1], t[2], 1.0); csock = rgb.outputs[0]
        # layer * weight
        scaled = nt.nodes.new("ShaderNodeVectorMath"); scaled.operation = "SCALE"; scaled.location = (-430, 120 - i * 280)
        nt.links.new(csock, scaled.inputs[0])
        try: nt.links.new(w[i], scaled.inputs["Scale"])
        except Exception: nt.links.new(w[i], scaled.inputs[3])
        if acc is None:
            acc = scaled.outputs["Vector"]
        else:
            a = nt.nodes.new("ShaderNodeVectorMath"); a.operation = "ADD"; a.location = (-220, 120 - i * 280)
            nt.links.new(acc, a.inputs[0]); nt.links.new(scaled.outputs["Vector"], a.inputs[1])
            acc = a.outputs["Vector"]
    if acc is not None:
        nt.links.new(acc, bsdf.inputs["Base Color"])
    _set_in(bsdf, ["Specular IOR Level", "Specular"], 0.1)
    _set_in(bsdf, ["Roughness"], 0.85)
    _set_opaque(m)

def _b_unlit(ctx):
    """unlit/scroll/sunbeam/sphere: emission = diffuse*vColor*Tint + glow; additive/alpha."""
    nt = ctx["nt"]; m = ctx["m"]; params = ctx["params"]; shader = ctx["shader"]
    mapn = _mapping(ctx)
    dnode, _ = _img(ctx, DIFFUSE_KEYS, "sRGB", mapn, ctx.get("override_base"))
    emi = nt.nodes.new("ShaderNodeEmission"); emi.location = (400, 0)
    strength = max(_getf(params, "EmissiveLevel", 0.0) + _getf(params, "GlowLevel", 0.0), 0.0)
    emi.inputs["Strength"].default_value = strength if strength > 0 else 1.0
    color = None; alpha = None
    dt = _getrgb(params, "DiffuseTint", (1, 1, 1))
    if dnode is not None:
        color = _tint(ctx, dnode.outputs["Color"], dt, (-200, 100)); alpha = dnode.outputs["Alpha"]
        if _flag(shader, "vertcolor"):
            vc = _vertex_color(ctx, (-500, 360))
            color = _mulcol(ctx, color, vc.outputs["Color"], (0, 200))
        nt.links.new(color, emi.inputs["Color"])
    else:
        emi.inputs["Color"].default_value = (dt[0], dt[1], dt[2], 1.0)
    additive = _flag(shader, "additive") or _flag(shader, "sunbeam")
    surface = emi.outputs["Emission"]
    if (additive or alpha is not None):
        transp = nt.nodes.new("ShaderNodeBsdfTransparent"); transp.location = (400, -200)
        if additive:
            add = nt.nodes.new("ShaderNodeAddShader"); add.location = (760, 0)
            nt.links.new(transp.outputs["BSDF"], add.inputs[0]); nt.links.new(emi.outputs["Emission"], add.inputs[1])
            surface = add.outputs["Shader"]
        else:
            mix = nt.nodes.new("ShaderNodeMixShader"); mix.location = (760, 0)
            nt.links.new(alpha, mix.inputs["Fac"])
            nt.links.new(transp.outputs["BSDF"], mix.inputs[1]); nt.links.new(emi.outputs["Emission"], mix.inputs[2])
            surface = mix.outputs["Shader"]
        _set_blended(m)
    else:
        _set_opaque(m)
    nt.links.new(surface, ctx["out"].inputs["Surface"])

def _b_flora(ctx):
    nt = ctx["nt"]; m = ctx["m"]
    if "blend" in (ctx["shader"] or "").lower():
        return _b_unlit(ctx)   # FloraBlend is unlit (diffuse + glow)
    bsdf = _principled(ctx)
    nt.links.new(bsdf.outputs["BSDF"], ctx["out"].inputs["Surface"])
    _, diff_a, _ = _surface_diffuse_normal(ctx, bsdf)
    if diff_a is not None:
        nt.links.new(diff_a, bsdf.inputs["Alpha"]); _set_blended(m, clip=True)  # cut-out leaves
    else:
        _set_opaque(m)

def _b_simple(ctx):
    nt = ctx["nt"]; m = ctx["m"]; params = ctx["params"]
    bsdf = _principled(ctx)
    nt.links.new(bsdf.outputs["BSDF"], ctx["out"].inputs["Surface"])
    dt = _getrgb(params, "DiffuseTint", (0.8, 0.8, 0.8))
    _set_in(bsdf, ["Base Color"], (dt[0], dt[1], dt[2], 1.0))
    st = _getrgb(params, "SpecularTint", (0, 0, 0))
    if st == (0, 0, 0):
        _set_in(bsdf, ["Specular IOR Level", "Specular"], 0.0); _set_in(bsdf, ["Roughness"], 0.8)
    else:
        _set_in(bsdf, ["Specular Tint"], (st[0], st[1], st[2], 1.0)); _set_in(bsdf, ["Roughness"], 0.4)
    _set_opaque(m)

def _b_fog(ctx):
    nt = ctx["nt"]; m = ctx["m"]; params = ctx["params"]
    emi = nt.nodes.new("ShaderNodeEmission"); emi.location = (400, 0)
    dt = _getrgb(params, "DiffuseTint", (0.5, 0.5, 0.7))
    emi.inputs["Color"].default_value = (dt[0], dt[1], dt[2], 1.0)
    transp = nt.nodes.new("ShaderNodeBsdfTransparent"); transp.location = (400, -200)
    mix = nt.nodes.new("ShaderNodeMixShader"); mix.location = (760, 0)
    mix.inputs["Fac"].default_value = min(max(_getf(params, "FogAmp", 0.5) * 0.5, 0.0), 1.0)
    nt.links.new(transp.outputs["BSDF"], mix.inputs[1]); nt.links.new(emi.outputs["Emission"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], ctx["out"].inputs["Surface"])
    _set_blended(m)

def _b_id(ctx):
    nt = ctx["nt"]; m = ctx["m"]
    tr = nt.nodes.new("ShaderNodeBsdfTransparent"); tr.location = (520, 0)
    nt.links.new(tr.outputs["BSDF"], ctx["out"].inputs["Surface"])
    _set_blended(m)

def _b_puddle(ctx):
    # best-effort (definition not in CompiledMaterials): reflective surface w/ sky
    return _b_reflective(ctx)

def _b_legacy(ctx):
    nt = ctx["nt"]; m = ctx["m"]; params = ctx["params"]
    bsdf = _principled(ctx)
    nt.links.new(bsdf.outputs["BSDF"], ctx["out"].inputs["Surface"])
    diff = _getrgb(params, "diffuse", (0.8, 0.8, 0.8))
    _set_in(bsdf, ["Base Color"], (diff[0], diff[1], diff[2], 1.0))
    spec = _getrgb(params, "specular", (0, 0, 0))
    if spec == (0, 0, 0):
        _set_in(bsdf, ["Specular IOR Level", "Specular"], 0.0); _set_in(bsdf, ["Roughness"], 0.9)
    else:
        sp = _getf(params, "specPow", 0.0)
        _set_in(bsdf, ["Roughness"], max(0.0, min(1.0, (2.0 / (sp + 2.0)) ** 0.5)) if sp else 0.4)
    glow = _getf(params, "glow", 0.0)
    if glow > 0.0:
        _set_in(bsdf, ["Emission Color", "Emission"], (diff[0], diff[1], diff[2], 1.0))
        _set_in(bsdf, ["Emission Strength"], glow)
    _set_opaque(m)


def make_material(name, shader_name, params, mat_entries, streams, uv_name, search_dirs,
                  img_cache, mat_cache, missing_log, debug=False, mesh_name=None,
                  cache_id=None, override_base=None, override_norm=None, logger=None):
    key = (cache_id or name or "BMDL_MAT", uv_name or "", tuple(search_dirs))
    cached = mat_cache.get(key)
    if cached is not None:
        return cached
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name or "BMDL_MAT")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (1150, 0)
    ctx = {
        "nt": nt, "m": m, "out": out, "shader": shader_name or "", "params": params or {},
        "entries": mat_entries or [], "streams": streams or [], "uv_name": uv_name,
        "search_dirs": search_dirs, "img_cache": img_cache, "missing_log": missing_log,
        "matname": name, "override_base": override_base, "override_norm": override_norm,
    }
    fam = _classify(shader_name)
    try:
        if   fam == "supermix":   _b_supermix(ctx)
        elif fam == "submix":     _b_lit(ctx)
        elif fam == "reflective": _b_reflective(ctx)
        elif fam == "crystal":    _b_crystal(ctx)
        elif fam == "puddle":     _b_puddle(ctx)
        elif fam == "unlit":      _b_unlit(ctx)
        elif fam == "flora":      _b_flora(ctx)
        elif fam == "fog":        _b_fog(ctx)
        elif fam == "simple":     _b_simple(ctx)
        elif fam == "id":         _b_id(ctx)
        elif fam == "legacy":     _b_legacy(ctx)
        elif fam == "cutout":     _b_lit(ctx, cutout=True)
        else:                     _b_lit(ctx)
    except Exception as e:
        if logger:
            logger(f'[material] "{name}" ({shader_name}) erro: {e}; fallback Principled')
        for nd in list(nt.nodes):
            if nd.type != "OUTPUT_MATERIAL":
                nt.nodes.remove(nd)
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (520, 0)
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"]); _set_opaque(m)
    if logger:
        logger(f'[material] "{name}" shader="{shader_name}" familia={fam}')
    mat_cache[key] = m
    return m


def make_principled_material(name, mat_entries, streams, uv_name, search_dirs, img_cache,
                             mat_cache, missing_log, debug=False, mesh_name=None, cache_id=None,
                             override_base=None, override_norm=None, logger=None):
    return make_material(name, name, {}, mat_entries, streams, uv_name, search_dirs, img_cache,
                         mat_cache, missing_log, debug, mesh_name, cache_id, override_base, override_norm, logger)


def _stem_sanitized(fname):
    st = os.path.splitext(fname)[0]
    return re.sub(r'([._-])?[DN]$', '', st, flags=re.IGNORECASE)
