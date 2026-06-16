"""Standalone validator: parse every .bmdl via bmdl_schema and assert structural
invariants. Run: python tools/validate_bmdl.py <dir>. Exit 0 iff all files pass."""
import os, sys, glob, struct
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bmdl_schema as S

def validate_file(path):
    data = open(path, "rb").read()
    problems = []
    try:
        r = S.Reader(data)
    except Exception as e:
        return [f"header: {e}"], {}
    seen = {}
    # later tasks extend this with: walk(r, seen, problems)
    if WALK:
        WALK(r, seen, problems)
    return problems, seen

def walk(r, seen, problems):
    def bump(name): seen[name] = seen.get(name, 0) + 1
    root = r.read("TbmdlRoot", 0); bump("TbmdlRoot")

    # model + materials
    mp = root["model_ptr"]
    if mp and r.in_range(mp):
        mdl = r.read("Model", mp); bump("Model")
        nm, matp = mdl["num_materials"], mdl["materials_ptr"]
        if 0 < nm < 4096 and r.in_range(matp):
            for mat in r.read_array("Material", matp, nm):
                bump("Material")
                if mat["num_params"] > 0 and r.in_range(mat["params_ptr"]):
                    nf = mat["num_floats"]
                    for prm in r.read_array("MatParam", mat["params_ptr"], mat["num_params"]):
                        bump("MatParam")
                        if prm["float_offset"] + prm["dimension"] > nf:
                            problems.append(f"matparam slice {prm['float_offset']}+{prm['dimension']} > {nf}")
                for arr in ("textures", "streams"):
                    n = mat[f"num_{arr}"]; p = mat[f"{arr}_ptr"]
                    if n > 0 and r.in_range(p):
                        r.read_array("TexBinding", p, n); bump("TexBinding")

        # meshes (geometry) -- exact layout from BinaryModel::ReadResourceModel @ 004a9220
        nmesh, mep = mdl["num_meshes"], mdl["meshes_ptr"]
        mesh_icounts = []   # parallel to mesh array; used to bound renderable index ranges
        mesh_vcounts = []
        if 0 < nmesh < 65536 and r.in_range(mep):
            for mi, mesh in enumerate(r.read_array("Mesh", mep, nmesh)):
                bump("Mesh")
                vc, ic = mesh["vertex_count"], mesh["index_count"]
                mesh_vcounts.append(vc); mesh_icounts.append(ic)
                for fld in ("vdecl_ptr", "vb_data_ptr", "ib_data_ptr"):
                    if not r.in_range(mesh[fld]):
                        problems.append(f"mesh{mi} {fld} {mesh[fld]} oor")
                if not (0 < vc <= (1 << 24)):
                    problems.append(f"mesh{mi} vertex_count {vc} insane")
                if not (0 < ic <= (1 << 26)) or ic % 3 != 0:
                    problems.append(f"mesh{mi} index_count {ic} insane")
                # vdecl must terminate (stream==0xFF) inside the graph
                if r.in_range(mesh["vdecl_ptr"]):
                    try:
                        vd = S.read_vdecl(r, mesh["vdecl_ptr"])
                    except Exception as e:
                        problems.append(f"mesh{mi} vdecl: {e}")
                    else:
                        if not vd:
                            problems.append(f"mesh{mi} vdecl empty")
                        # the 16-bit index buffer must hold ib_data_ptr .. +index_count*2 in graph
                        if r.in_range(mesh["ib_data_ptr"]) and not r.in_range(mesh["ib_data_ptr"] + ic * 2 - 1):
                            problems.append(f"mesh{mi} ib spans past graph (icount={ic})")
                        # the vertex buffer (stride = decl's max offset+, at least vc*4) must fit
                        if r.in_range(mesh["vb_data_ptr"]) and not r.in_range(mesh["vb_data_ptr"] + vc * 4 - 1):
                            problems.append(f"mesh{mi} vb spans past graph (vcount={vc})")
                        # every 16-bit index must reference a vertex that exists
                        if (r.in_range(mesh["ib_data_ptr"]) and r.in_range(mesh["ib_data_ptr"] + ic * 2 - 1)
                                and 0 < vc <= (1 << 24)):
                            ibo = r._abs(mesh["ib_data_ptr"])
                            mx = max(struct.unpack_from(f"<{ic}H", r.d, ibo)) if ic else 0
                            if mx >= vc:
                                problems.append(f"mesh{mi} max index {mx} >= vertex_count {vc}")

        # instances / LODs and their renderables (sub-draws)
        ninst, ip = mdl["num_instances"], mdl["instances_ptr"]
        if 0 < ninst < 65536 and r.in_range(ip):
            for ii, inst in enumerate(r.read_array("Instance", ip, ninst)):
                bump("Instance")
                meshidx = inst["mesh_index"]
                ic = mesh_icounts[meshidx] if meshidx < len(mesh_icounts) else None
                if mesh_icounts and meshidx >= len(mesh_icounts):
                    problems.append(f"inst{ii} mesh_index {meshidx} >= num_meshes {len(mesh_icounts)}")
                nr, rp = inst["num_renderables"], inst["renderables_ptr"]
                if not (0 <= nr < 65536):
                    problems.append(f"inst{ii} num_renderables {nr} insane")
                    continue
                if nr > 0 and not r.in_range(rp):
                    problems.append(f"inst{ii} renderables_ptr {rp} oor")
                    continue
                for ri, rend in enumerate(r.read_array("Renderable", rp, nr)):
                    bump("Renderable")
                    mat_i = rend["material_index"]
                    if 0 < nm < 4096 and not (0 <= mat_i < nm):
                        problems.append(f"inst{ii} rend{ri} material_index {mat_i} >= {nm}")
                    start, cnt = rend["index_start"], rend["index_count"]
                    if cnt % 3 != 0:
                        problems.append(f"inst{ii} rend{ri} index_count {cnt} not a multiple of 3")
                    if ic is not None and start + cnt > ic:
                        problems.append(f"inst{ii} rend{ri} index range {start}+{cnt} > mesh icount {ic}")

    # skeleton + bones
    sk = root["skeleton_ptr"]
    if sk:
        if not r.in_range(sk):
            problems.append(f"skeleton_ptr {sk} oor")
        else:
            skel = r.read("Skeleton", sk); bump("Skeleton")
            n, bp = skel["num_bones"], skel["bones_ptr"]
            if 0 < n < 4096 and r.in_range(bp):
                for b in r.read_array("Bone", bp, n):
                    bump("Bone")
                    if b["parent_index"] < -1 or b["parent_index"] >= n:
                        problems.append(f"bone parent {b['parent_index']} oor")

    # animations
    na, ap = root["num_anims"], root["anims_ptr"]
    dims = {1: 3, 2: 4, 3: 3}
    if 0 < na < 4096 and r.in_range(ap):
        for h in r.read_array("AnimHeader", ap, na):
            bump("AnimHeader")
            nt, tp = h["num_tracks"], h["tracks_ptr"]
            if not (0 < nt < 65536 and r.in_range(tp)):
                continue
            for t in r.read_array("AnimTrack", tp, nt):
                bump("AnimTrack")
                nk, tpt, vpt = t["num_keys"], t["times_ptr"], t["values_ptr"]
                if nk == 0:
                    continue
                if vpt - tpt != nk * 4:
                    problems.append(f"track contiguity: vpt-tpt={vpt-tpt} != num_keys*4={nk*4}")
                if t["category"] not in dims:
                    problems.append(f"track category {t['category']} unknown")

WALK = walk

def main(root):
    files = glob.glob(os.path.join(root, "**", "*.bmdl"), recursive=True)
    ok = bad = 0
    agg = {}
    for f in files:
        problems, seen = validate_file(f)
        for k, v in seen.items():
            agg[k] = agg.get(k, 0) + v
        if problems:
            bad += 1
            if bad <= 30:
                print(f"FAIL {os.path.relpath(f, root)}: {problems[0]}")
        else:
            ok += 1
    print(f"\nfiles={len(files)} ok={ok} fail={bad}")
    print("struct coverage:", {k: agg[k] for k in sorted(agg)})
    return 0 if bad == 0 else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
