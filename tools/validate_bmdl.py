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
