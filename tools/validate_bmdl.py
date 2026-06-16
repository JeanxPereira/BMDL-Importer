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

WALK = None   # set by later tasks

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
