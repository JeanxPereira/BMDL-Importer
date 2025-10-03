bl_info = {
    "name": "Darkspore BMDL Importer",
    "author": "JeanxPereira, foehammer",
    "version": (1, 0, 1),
    "blender": (4, 5, 0),
    "location": "File > Import > Darkspore (.bmdl)",
    "description": "Import Darkspore BMDL files",
    'warning': '',
    'tracker_url': "https://github.com/JeanxPereira/BMDL-Importer/issues/",
    "category": "Import-Export",
}

import bpy
import os
import time
from bpy.types import Operator
from bpy.props import StringProperty, CollectionProperty, BoolProperty, IntProperty, FloatProperty
from bpy_extras.io_utils import ImportHelper, orientation_helper

from .bmdl_core import (
    BMDLv2,
    _compute_vb_cap, _scan_max_for_mode, _score_mode, _expected_tris,
    _read_renderable_indices, _decode_vertices, _decode_normals, _decode_colors, _decode_uv_sets,
)

from .io_mesh import (
    build_mesh,
    ensure_empty_material,
    ensure_uv_debug_material,
    make_principled_material,
    search_roots_for,
    write_missing_log,
)
from .io_armature import (
    build_armature,
    apply_skin_to_object,
    apply_skin_joined,
)
from .io_anim import (
    import_animations,
    AnimLogger,
)
from .utils import (
    make_axis_m3,
)

_pending_import = None

@orientation_helper(axis_forward="-Z", axis_up="Y")
class IMPORT_OT_io_darkspore(Operator, ImportHelper):
    bl_idname = "import_scene.io_darkspore"
    bl_label = "Import Darkspore (.bmdl)"
    filename_ext = ".bmdl"

    filter_glob: StringProperty(default="*.bmdl", options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH")

    convert_axes: BoolProperty(name="Apply Axis to Vertices", default=False)
    flip_v: BoolProperty(name="Flip V", default=True)
    preview_uv: BoolProperty(name="Preview UV (Checker)", default=False)
    preview_uv_index: IntProperty(name="UV Index", default=0, min=0, max=7)
    apply_custom_normals: BoolProperty(name="Apply Custom Normals", default=False)
    join_renderables: BoolProperty(name="Join Renderables (per mesh)", default=False)
    debug_log: BoolProperty(name="Debug Log", default=True)
    dry_run: BoolProperty(name="Dry Run (no mesh build)", default=False)

    import_animations_opt: BoolProperty(name="Import Animations", default=True)

    import_textures: BoolProperty(name="Import Textures", default=True)
    use_custom_texture_dir: BoolProperty(name="Use Custom Texture Path", default=False)
    textures_dir: StringProperty(name="Custom Texture Path", subtype="DIR_PATH", default="")

    def execute(self, context):
        paths = []
        if self.files:
            for f in self.files:
                paths.append(os.path.join(self.directory, f.name))
        else:
            paths.append(self.filepath)

        m3 = make_axis_m3(self.convert_axes, self.axis_forward, self.axis_up)

        if self.import_textures and self.use_custom_texture_dir and not self.textures_dir:
            settings = {
                # "convert_axes": self.convert_axes,
                # "axis_forward": self.axis_forward,
                # "axis_up": self.axis_up,
                # "axis_m3": m3,
                "flip_v": self.flip_v,
                "preview_uv": self.preview_uv,
                #"preview_uv_index": self.preview_uv_index,
                "apply_custom_normals": self.apply_custom_normals,
                "join_renderables": self.join_renderables,
                "debug_log": self.debug_log,
                "dry_run": self.dry_run,
                "import_textures": True,
                "use_custom_texture_dir": True,
                "textures_dir": "",
                "import_animations": self.import_animations_opt,
            }
            global _pending_import
            _pending_import = {"paths": paths, "settings": settings}
            try:
                bpy.ops.import_scene.darkspore_pick_textures("INVOKE_DEFAULT")
            except Exception:
                self.report({"WARNING"}, 'Could not open folder picker; please set "Custom Texture Dir" and run again.')
            return {"FINISHED"}

        settings = {
            #"convert_axes": self.convert_axes,
            #"axis_forward": self.axis_forward,
            #"axis_up": self.axis_up,
            #"axis_m3": m3,
            "flip_v": self.flip_v,
            "preview_uv": self.preview_uv,
            #"preview_uv_index": self.preview_uv_index,
            "apply_custom_normals": self.apply_custom_normals,
            "join_renderables": self.join_renderables,
            "debug_log": self.debug_log,
            "dry_run": self.dry_run,
            "import_textures": self.import_textures,
            "use_custom_texture_dir": self.use_custom_texture_dir,
            "textures_dir": self.textures_dir,
            "import_animations": self.import_animations_opt,
        }
        imported = run_import_from_paths(context, paths, settings)
        return {"FINISHED"} if imported > 0 else {"CANCELLED"}


class IMPORT_OT_darkspore_pick_textures(Operator):
    bl_idname = "import_scene.darkspore_pick_textures"
    bl_label = "Select Darkspore Textures Folder"

    directory: StringProperty(name="Textures Folder", subtype="DIR_PATH", default="")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        global _pending_import
        if not _pending_import or not _pending_import.get("paths"):
            self.report({"WARNING"}, "No pending BMDL selection to use.")
            return {"CANCELLED"}
        settings = _pending_import.get("settings", {})
        settings["textures_dir"] = self.directory
        settings["import_textures"] = True
        settings["use_custom_texture_dir"] = True
        paths = _pending_import["paths"]
        imported = run_import_from_paths(context, paths, settings)
        _pending_import = None
        return {"FINISHED"} if imported > 0 else {"CANCELLED"}


def run_import_from_paths(context, paths, settings):
    imported = 0
    m3 = settings.get("axis_m3")
    img_cache = {}
    mat_cache = {}

    

    anim_m3 = make_axis_m3(
        settings.get("convert_axes", False),
        settings.get("axis_forward", "-Z"),
        settings.get("axis_up", "Y"),
    )
    settings["anim_m3"] = anim_m3

    for p in paths:
        file_stem = os.path.splitext(os.path.basename(p))[0]

        try:
            with open(p, "rb") as f:
                d = f.read()
            ds = BMDLv2(d)
            tb = ds.tbmdl()
            if not tb["model_ptr"]:
                continue
            mdl = ds.model(tb["model_ptr"])
            if mdl["num_meshes"] <= 0:
                continue

            # --- Armature / skeleton ---
            arm_obj = None
            bone_names = []
            bones_count = 0
            if tb["skeleton_ptr"]:
                sk = ds.skeleton(tb["skeleton_ptr"])
                if sk:
                    bones = ds.bones(sk["bones_ptr"], sk["num_bones"])
                    if bones:
                        arm_obj, bone_names = build_armature(
                            context, bones,
                            mdl.get("name") or os.path.splitext(os.path.basename(p))[0],
                            m3
                        )
                        bones_count = len(bone_names)

            # --- MAterials / Instances ---
            mats_bmdl = ds.materials(mdl["materials_ptr"], mdl["num_materials"]) if mdl["num_materials"] > 0 else []
            insts = ds.instances(mdl["instances_ptr"], mdl["num_instances"])
            rels_by_mesh = {}
            for inst in insts:
                if inst["num_renderables"] > 0:
                    rels_by_mesh.setdefault(inst["imesh"], []).extend(
                        ds.renderables(inst["renderables_ptr"], inst["num_renderables"])
                    )

            debug = settings.get("debug_log", False)
            search_dirs = search_roots_for(p, settings) if settings.get("import_textures") else []
            missing_records = []

            # --- Meshes ---
            for mi in range(mdl["num_meshes"]):
                try:
                    m = ds.mesh_flexible(mdl["meshes_ptr"], mi)
                    if m["vdecl_ptr"] == 0 or m["vb_ptr"] == 0 or m["pitch"] == 0:
                        continue
                    decl = ds.vdecl(m["vdecl_ptr"])
                    if not decl:
                        continue
                    stride = m["pitch"] * 4
                    rels = rels_by_mesh.get(mi, [])
                    if not rels or m["ib_ptr"] == 0:
                        continue

                    logs = []
                    def L(msg):
                        logs.append(msg)
                        if debug:
                            print(msg)

                    vb_cap = _compute_vb_cap(m, stride, ds.graph_size)
                    L(f"[mesh {mi}] name={m.get('name')} pitch={m['pitch']} stride={stride} vb_ptr={m['vb_ptr']} ib_ptr={m['ib_ptr']} sizevb={m.get('sizevb',0)} vb_cap={vb_cap} rels={len(rels)}")

                    modes = [(2, 1), (4, 1), (2, 3), (4, 3)]
                    stats = []
                    for isz, fac in modes:
                        mxi, ok = _scan_max_for_mode(ds.d, ds.base, m["ib_ptr"], rels, isz, fac, ds.base + ds.graph_size)
                        if not ok:
                            L(f"  mode isz={isz} fac={fac} -> scan failed")
                            continue
                        vb_cap_local = _compute_vb_cap(m, stride, ds.graph_size)
                        vcount = max(1, min(vb_cap_local, mxi + 1)) if vb_cap_local > 0 else max(1, mxi + 1)
                        tri_valid, expect = _score_mode(ds.d, ds.base, m, rels, isz, fac, ds.graph_size, vcount)
                        exp_tris = _expected_tris(rels, fac)
                        ratio = (tri_valid / max(exp_tris, 1.0)) if exp_tris > 0 else 0.0
                        L(f"  mode isz={isz} fac={fac} mxi={mxi} vcount={vcount} tri_valid={tri_valid} expect={exp_tris} ratio={ratio:.3f}")
                        stats.append((isz, fac, vcount, tri_valid, exp_tris, ratio))
                    if not stats:
                        L("  no viable mode")
                        log_path = os.path.join(os.path.dirname(p), os.path.splitext(os.path.basename(p))[0] + ".darkspore_import.log.txt")
                        with open(log_path, "a", encoding="utf-8") as lf:
                            for line in logs:
                                lf.write(line + "\n")
                        continue

                    choice = max(stats, key=lambda s: (s[5], s[3], -s[0], -(1 if s[1] == 1 else 0)))
                    s1 = max([s for s in stats if s[1] == 1], default=None, key=lambda s: (s[5], s[3]))
                    s3 = max([s for s in stats if s[1] == 3], default=None, key=lambda s: (s[5], s[3]))
                    if s3 and s1 and s3[5] >= 0.95 and s3[3] >= 2.5 * s1[3]:
                        choice = s3
                    isz, fac, vcount, tri_valid, expect, ratio = choice
                    L(f"  chosen isz={isz} fac={fac} vcount={vcount}")

                    # base_name = m["name"] or mdl["name"] or os.path.splitext(os.path.basename(p))[0]
                    base_name = file_stem

                    global_order = []
                    order_map = {}
                    segments = []
                    slot_stem_base = {}
                    slot_stem_norm = {}
                    base_keys = {"diffusemap","albedomap","basecolormap","albedo","basecolor","colormap","color","diffuse"}
                    norm_keys = {"normalmap","normal","bumpmap","bump"}

                    for ri, r in enumerate(rels):
                        idxs = _read_renderable_indices(ds.d, ds.base, m["ib_ptr"], r, isz, fac, ds.base + ds.graph_size)
                        if not idxs:
                            L(f"  r{ri}: no idxs")
                            continue
                        tri = len(idxs) // 3
                        if tri <= 0:
                            L(f"  r{ri}: no tris")
                            continue
                        vb_cap_local = _compute_vb_cap(m, stride, ds.graph_size)
                        base_v = 0
                        vcount_r = vb_cap_local
                        in0 = sum(1 for t in range(tri) if idxs[t * 3] < vb_cap_local and idxs[t * 3 + 1] < vb_cap_local and idxs[t * 3 + 2] < vb_cap_local)
                        ratio0 = in0 / tri if tri > 0 else 0.0
                        B = 0
                        if vb_cap_local > 0:
                            srt = sorted(idxs)
                            i = 0
                            best_i = 0
                            best_cnt = 0
                            for j in range(len(srt)):
                                while srt[j] - srt[i] >= vb_cap_local and i < j:
                                    i += 1
                                cnt = j - i + 1
                                if cnt > best_cnt:
                                    best_cnt = cnt
                                    best_i = i
                            B = srt[best_i]
                        inB = sum(1 for t in range(tri) if B <= idxs[t * 3] < B + vb_cap_local and B <= idxs[t * 3 + 1] < B + vb_cap_local and B <= idxs[t * 3 + 2] < B + vb_cap_local)
                        ratioB = inB / tri if tri > 0 else 0.0
                        useB = (inB >= 64 and ratioB >= max(0.2, ratio0 + 0.1)) or (ratio0 < 0.2 and ratioB >= 2.0 * max(ratio0, 1e-6) and inB >= 32)
                        if useB:
                            base_v = B
                            hi = max(idx for tri_i in range(tri) for idx in (idxs[tri_i * 3], idxs[tri_i * 3 + 1], idxs[tri_i * 3 + 2]) if B <= idx < B + vb_cap_local)
                            vcount_r = hi - base_v + 1 if hi >= base_v else vb_cap_local

                        kept_tris = []
                        for t in range(tri):
                            a = idxs[t * 3]
                            b = idxs[t * 3 + 1]
                            c = idxs[t * 3 + 2]
                            if base_v <= a < base_v + vcount_r and base_v <= b < base_v + vcount_r and base_v <= c < base_v + vcount_r:
                                kept_tris.append((a - base_v, b - base_v, c - base_v))
                        L(f"  r{ri}: base0_ratio={ratio0:.3f} densestB={B} densest_ratio={ratioB:.3f} useB={useB} base={base_v} vcount={vcount_r} tris={len(kept_tris)}")
                        if not kept_tris:
                            continue
                        if settings.get("dry_run", False):
                            continue

                        if settings.get("join_renderables", True):
                            mslot = order_map.get(ri)
                            if mslot is None:
                                mslot = len(order_map)
                                order_map[ri] = mslot
                                global_order.append(ri)
                            mats = [mslot] * len(kept_tris)
                        else:
                            mats = [0] * len(kept_tris)

                        verts = _decode_vertices(ds.d, ds.base, m["vb_ptr"], base_v, vcount_r, stride, decl)
                        if settings.get("import_textures") and mdl["num_materials"] > 0 and 0 <= r["imat"] < len(mats_bmdl):
                            info = mats_bmdl[r["imat"]]
                            stems_b = [e.get("value") for e in info.get("textures", []) if (e.get("key") or "").lower() in base_keys and (e.get("value") or "")]
                            stems_n = [e.get("value") for e in info.get("textures", []) if (e.get("key") or "").lower() in norm_keys and (e.get("value") or "")]
                            if stems_b:
                                idxb = ri if ri < len(stems_b) else (ri % len(stems_b))
                                slot_stem_base[ri] = stems_b[idxb]
                            if stems_n:
                                idxn = ri if ri < len(stems_n) else (ri % len(stems_n))
                                slot_stem_norm[ri] = stems_n[idxn]

                        if verts is None:
                            L(f"  r{ri}: no verts for base")
                            continue

                        nrms = _decode_normals(ds.d, ds.base, m["vb_ptr"], base_v, vcount_r, stride, decl)
                        vcols = _decode_colors(ds.d, ds.base, m["vb_ptr"], base_v, vcount_r, stride, decl)
                        uvsets = _decode_uv_sets(ds.d, ds.base, m["vb_ptr"], base_v, vcount_r, stride, decl)

                        if settings.get("join_renderables", True):
                            segments.append({"verts": verts, "nrms": nrms, "vcols": vcols, "uvsets": uvsets, "tris": kept_tris, "mats": mats, "base": base_v, "vcount": vcount_r})
                        else:
                            order = [r["imat"]]
                            inds = []
                            for a, b, c in kept_tris:
                                inds.extend([a, b, c])

                            # material
                            mat_objs = None
                            if 0 <= r["imat"] < len(mats_bmdl):
                                info = mats_bmdl[r["imat"]]
                                uv_name = f"UV{min(uvsets.keys())}" if uvsets else None
                                stems_b = [e.get("value") for e in info.get("textures", []) if (e.get("key") or "").lower() in base_keys and (e.get("value") or "")]
                                stems_n = [e.get("value") for e in info.get("textures", []) if (e.get("key") or "").lower() in norm_keys and (e.get("value") or "")]
                                ov_b = stems_b[ri] if stems_b and ri < len(stems_b) else (stems_b[ri % len(stems_b)] if stems_b else None)
                                ov_n = stems_n[ri] if stems_n and ri < len(stems_n) else (stems_n[ri % len(stems_n)] if stems_n else None)
                                disp = (info.get("name") or "MAT") + f"_{ri:02d}"
                                cid = f"{os.path.abspath(p)}|slot|{ri}"
                                mat_obj = make_principled_material(
                                    disp, info.get("textures", []), info.get("streams", []),
                                    uv_name, search_dirs, img_cache, mat_cache, missing_records, debug,
                                    mesh_name=m.get("name"), cache_id=cid,
                                    override_base=ov_b, override_norm=ov_n, logger=L,
                                )
                                mat_objs = [mat_obj]
                            else:
                                mat_objs = [ensure_empty_material(f"SLOT_{ri:02d}")]

                            obj = build_mesh(
                                context, f"{base_name}__r{ri:02d}", verts, inds, uvsets, nrms, vcols,
                                order, mats, settings.get("flip_v", True), m3,
                                settings.get("preview_uv_index") if settings.get("preview_uv") else None,
                                settings.get("apply_custom_normals", False), mat_objs,
                            )
                            if arm_obj and bones_count > 0:
                                apply_skin_to_object(obj, ds, m, decl, base_v, vcount_r, stride, bones_count, bone_names, arm_obj, m3)
                            imported += 1

                    # join per mesh
                    if not settings.get("dry_run", False) and settings.get("join_renderables", True) and segments:
                        voff = 0
                        all_verts, all_inds, all_nrms = [], [], []
                        all_vcols = None
                        uv_keys = set()
                        for seg in segments:
                            uv_keys.update(seg["uvsets"].keys())
                        uv_join = {k: [] for k in sorted(uv_keys)}
                        has_nrms = all(seg["nrms"] is not None for seg in segments)
                        has_cols = all(seg["vcols"] is not None for seg in segments)
                        if has_cols:
                            all_vcols = []
                        mats_index = []
                        for seg in segments:
                            vcount = len(seg["verts"]) // 3
                            all_verts.extend(seg["verts"])
                            if has_nrms: all_nrms.extend(seg["nrms"])
                            if has_cols: all_vcols.extend(seg["vcols"])
                            for k in uv_join.keys():
                                arr = seg["uvsets"].get(k)
                                if arr is None:
                                    uv_join[k].extend([0.0] * (vcount * 2))
                                else:
                                    uv_join[k].extend(arr)
                            for (a, b, c), ms in zip(seg["tris"], seg["mats"]):
                                all_inds.extend([a + voff, b + voff, c + voff])
                                mats_index.append(ms)
                            voff += vcount

                        # name = m["name"] or mdl["name"] or os.path.splitext(os.path.basename(p))[0]
                        name = file_stem

                        mat_objs = None
                        if settings.get("import_textures") and search_dirs and mdl["num_materials"] > 0 and global_order:
                            mat_objs = []
                            uv_name = f"UV{min(uv_join.keys())}" if uv_join else None
                            for ri in global_order:
                                r = rels[ri]
                                if 0 <= r["imat"] < len(mats_bmdl):
                                    info = mats_bmdl[r["imat"]]
                                    disp = (info.get("name") or "MAT") + f"_{ri:02d}"
                                    cid = f"{os.path.abspath(p)}|slot|{ri}"
                                    mat_objs.append(
                                        make_principled_material(
                                            disp, info.get("textures", []), info.get("streams", []),
                                            uv_name, search_dirs, img_cache, mat_cache, missing_records, debug,
                                            mesh_name=m.get("name"), cache_id=cid,
                                            override_base=slot_stem_base.get(ri), override_norm=slot_stem_norm.get(ri), logger=L,
                                        )
                                    )
                                else:
                                    mat_objs.append(ensure_empty_material(f"SLOT_{ri:02d}"))

                        obj = build_mesh(
                            context, name, all_verts, all_inds, uv_join,
                            all_nrms if has_nrms else None, all_vcols,
                            global_order, mats_index, settings.get("flip_v", True), m3,
                            settings.get("preview_uv_index") if settings.get("preview_uv") else None,
                            settings.get("apply_custom_normals", False), mat_objs,
                        )
                        if arm_obj and bones_count > 0:
                            apply_skin_joined(obj, ds, m, decl, stride, segments, bones_count, bone_names, arm_obj, m3)
                        imported += 1

                    # dump log desse mesh
                    log_path = os.path.join(os.path.dirname(p), os.path.splitext(os.path.basename(p))[0] + ".darkspore_import.log.txt")
                    with open(log_path, "a", encoding="utf-8") as lf:
                        for line in logs:
                            lf.write(line + "\n")

                except Exception as e:
                    print(f"[mesh {mi}] import error for {os.path.basename(p)}:", e)

            if settings.get("import_textures"):
                write_missing_log(p, missing_records)

            # --- Animations ---
            try:
                log_dir = os.path.dirname(p)
                stem = os.path.splitext(os.path.basename(p))[0]
                anim_log_path = os.path.join(log_dir, stem + ".darkspore_anim.log.txt")
                alog = AnimLogger(anim_log_path, enable=True, echo=settings.get("debug_log", False))
                settings["anim_logger"] = alog
                if settings.get("import_animations", True) and tb.get("num_anims", 0) > 0 and arm_obj:
                    import_animations(ds, tb, arm_obj, bone_names, settings)
            except Exception as e:
                print("[anim] import error:", e)

        except Exception as e:
            print(f"[file] {os.path.basename(p)}: {e}")

    return imported


def menu_func_import(self, context):
    self.layout.operator(IMPORT_OT_io_darkspore.bl_idname, text="Darkspore (.bmdl)")


def register():
    bpy.utils.register_class(IMPORT_OT_io_darkspore)
    bpy.utils.register_class(IMPORT_OT_darkspore_pick_textures)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(IMPORT_OT_darkspore_pick_textures)
    bpy.utils.unregister_class(IMPORT_OT_io_darkspore)

if __name__ == "__main__":
    register()