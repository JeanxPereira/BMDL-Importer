import bpy
from mathutils import Quaternion, Vector, Euler, Matrix
from .bmdl_core import (
    AnimHeader, RawTrack, ResolvedAnim,
    _enumerate_anim_headers, _read_tracks, _decode_animation
)

class AnimLogger:
    def __init__(self, path, enable=True, echo=False):
        self.path = path
        self.enable = enable
        self.echo = echo
        self.lines = []
        self.warns = 0
    def log(self, msg):
        if not self.enable:
            return
        s = str(msg)
        if s.startswith("t=") and "warn=" in s:
            self.warns += 1
        self.lines.append(s)
        if self.echo:
            print(s)
    def dump(self):
        if not self.enable or not self.path:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                for ln in self.lines:
                    f.write(ln + "\n")
        except Exception:
            pass
    def clear(self):
        self.lines.clear()


def ensure_action(arm_obj, name):
    """Retorna (action, fcurve_container). Em Blender 4.4+ as fcurves vivem
    num channelbag (slot+layer+strip); no legado, na propria action."""
    if not arm_obj.animation_data:
        arm_obj.animation_data_create()
    act = bpy.data.actions.get(name) or bpy.data.actions.new(name)
    ad = arm_obj.animation_data
    ad.action = act
    if hasattr(act, "fcurves"):          # Blender <4.4 (legado)
        return act, act
    # Sistema novo (slotted action)
    slot = next((s for s in act.slots if s.target_id_type == 'OBJECT'), None)
    if slot is None:
        slot = act.slots.new(id_type='OBJECT', name="Object")
    try:
        ad.action_slot = slot
    except Exception:
        pass
    layer = act.layers[0] if len(act.layers) else act.layers.new("Base")
    strip = layer.strips[0] if len(layer.strips) else layer.strips.new(type='KEYFRAME')
    cb = strip.channelbag(slot, ensure=True)
    return act, cb

def _ensure_fcurve(cb, path, idx):
    for fc in cb.fcurves:
        if fc.data_path == path and fc.array_index == idx:
            return fc
    return cb.fcurves.new(path, index=idx)

def write_channel(fc, frames, values):
    n = min(len(frames), len(values))
    if n <= 0:
        return
    kps = fc.keyframe_points
    if len(kps) > 0:
        kps.clear()
    kps.add(n)
    co = [0.0] * (2 * n)
    j = 0
    for i in range(n):
        co[j] = float(frames[i])
        co[j + 1] = float(values[i])
        j += 2
    kps.foreach_set("co", co)
    for kp in kps:
        kp.interpolation = "LINEAR"


# ----------------------------------------------------------------------------
# Bake em forma fechada.
#
# Fatos confirmados por engenharia reversa (ver docs/BMDL_ANIMATION.md):
#   - cada track guarda TRS LOCAL relativo ao pai (medido em 24/24 ossos).
#   - matriz armazenada e row-major (D3D) -> transpor ao carregar no mathutils.
#   - local = Translation(T) @ quat.to_matrix() @ Diagonal(S)  (conv. coluna).
#   - world[osso] = world[pai] @ local[osso].
#   - quaternion em xyzw -> Quaternion((w,x,y,z)).  (decode ja entrega wxyz)
#
# A deformacao do jogo em world-space e  D = world_anim @ inv_bind.
# No Blender (armature space, com conversao de eixo A = m3 4x4):
#   pose[osso]  = A @ D @ A^-1 @ matrix_local[osso]
#   basis[osso] = rel_rest[osso]^-1 @ pose[pai]^-1 @ pose[osso]   (raiz: pai = I)
# basis e o que vira location / rotation_quaternion / scale do pose bone.
# Isto independe de como build_armature aproximou a orientacao do rest
# (head->filho), pois A e matrix_local se cancelam corretamente no rest.
# ----------------------------------------------------------------------------

def _loadmat(m16):
    R = Matrix(((m16[0], m16[1], m16[2], m16[3]),
                (m16[4], m16[5], m16[6], m16[7]),
                (m16[8], m16[9], m16[10], m16[11]),
                (m16[12], m16[13], m16[14], m16[15])))
    return R.transposed()

def _depth(i, parent_idx):
    d = 0
    seen = set()
    while i is not None and i >= 0 and i not in seen:
        seen.add(i)
        p = parent_idx.get(i, -1)
        if p < 0:
            break
        i = p
        d += 1
    return d

def _interp_vec(times, vals, t, default):
    n = min(len(times), len(vals))
    if n <= 0:
        return Vector(default)
    if t <= times[0]:
        return Vector(vals[0])
    if t >= times[n - 1]:
        return Vector(vals[n - 1])
    for i in range(1, n):
        if t <= times[i]:
            t0, t1 = times[i - 1], times[i]
            f = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            return Vector(vals[i - 1]).lerp(Vector(vals[i]), f)
    return Vector(vals[n - 1])

def _interp_quat(times, quats, t, default):
    n = min(len(times), len(quats))
    if n <= 0:
        return Quaternion(default)
    if t <= times[0]:
        return Quaternion(quats[0])
    if t >= times[n - 1]:
        return Quaternion(quats[n - 1])
    for i in range(1, n):
        if t <= times[i]:
            t0, t1 = times[i - 1], times[i]
            f = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            return Quaternion(quats[i - 1]).slerp(Quaternion(quats[i]), f)
    return Quaternion(quats[n - 1])


def bake_resolved_anim(arm_obj, anim, settings):
    alog = settings.get("anim_logger", None)
    game_bones = settings.get("anim_bones") or []
    if not game_bones:
        if alog:
            alog.log(f'[anim] "{anim.name}" SKIP: sem dados de esqueleto (anim_bones)')
        return

    m3 = settings.get("anim_build_m3")
    A = m3.to_4x4() if m3 is not None else Matrix.Identity(4)
    Ainv = A.inverted()

    invb = {}
    parent_idx = {}
    idx_name = {}
    bi_by_name = {}
    for b in game_bones:
        i = b["index"]
        invb[i] = _loadmat(b["inv_bind"])
        parent_idx[i] = b["parent"]
        idx_name[i] = b["name"]
        bi_by_name[b["name"]] = i

    # rest world (game) e TRS local de rest (defaults para canais ausentes)
    Wg_rest = {}
    def world_rest(i):
        if i not in Wg_rest:
            Wg_rest[i] = invb[i].inverted()
        return Wg_rest[i]
    rest_local = {}
    for i in invb:
        p = parent_idx[i]
        wl = world_rest(i)
        ll = (world_rest(p).inverted() @ wl) if 0 <= p else wl
        rest_local[i] = ll.decompose()  # (Vector T, Quaternion Q, Vector S)

    # rest do Blender (armature space)
    data_bones = arm_obj.data.bones
    ml = {}
    rel_rest = {}
    for db in data_bones:
        ml[db.name] = db.matrix_local.copy()
    for db in data_bones:
        if db.parent:
            rel_rest[db.name] = db.parent.matrix_local.inverted() @ db.matrix_local
        else:
            rel_rest[db.name] = db.matrix_local.copy()

    # tempos de amostragem = uniao dos tempos de todas as tracks
    tset = set()
    for bn, chans in anim.timeline.items():
        for ch, ts in chans.items():
            for t in ts:
                tset.add(round(float(t), 6))
    times = sorted(tset)
    if not times:
        times = [0.0]

    order = sorted(invb.keys(), key=lambda i: _depth(i, parent_idx))
    animated = [bn for bn in anim.bones.keys() if bn in bi_by_name]
    out = {bn: {"loc": [], "quat": [], "scl": []} for bn in animated}

    for t in times:
        Wg = {}
        pose = {}
        for i in order:
            name = idx_name[i]
            T0, Q0, S0 = rest_local[i]
            data = anim.bones.get(name, {})
            tl = anim.timeline.get(name, {})
            if "location" in data:
                T = _interp_vec(tl.get("location", []), data["location"], t, T0)
            else:
                T = Vector(T0)
            if "rotation_quaternion" in data:
                Q = _interp_quat(tl.get("rotation_quaternion", []), data["rotation_quaternion"], t, Q0)
            else:
                Q = Quaternion(Q0)
            if "scale" in data:
                S = _interp_vec(tl.get("scale", []), data["scale"], t, S0)
            else:
                S = Vector(S0)
            local = (Matrix.Translation(T) @ Q.to_matrix().to_4x4()
                     @ Matrix.Diagonal(Vector((S.x, S.y, S.z, 1.0))))
            p = parent_idx[i]
            Wg[i] = (Wg[p] @ local) if (0 <= p and p in Wg) else local
            D = Wg[i] @ invb[i]
            pose[i] = A @ D @ Ainv @ ml[name]
        for name in animated:
            i = bi_by_name[name]
            p = parent_idx[i]
            pm = pose[p] if (0 <= p and p in pose) else Matrix.Identity(4)
            basis = rel_rest[name].inverted() @ pm.inverted() @ pose[i]
            loc, q, scl = basis.decompose()
            out[name]["loc"].append(loc)
            out[name]["quat"].append(q)
            out[name]["scl"].append(scl)

    if alog:
        alog.log(f'[anim] "{anim.name}" dur={round(anim.duration,3)} '
                 f'bones={len(animated)} samples={len(times)}')

    act, cb = ensure_action(arm_obj, anim.name)
    for name in animated:
        be = name.replace('"', '\\"')
        pb = arm_obj.pose.bones.get(name)
        if pb:
            pb.rotation_mode = "QUATERNION"
        locs = out[name]["loc"]
        quats = out[name]["quat"]
        scls = out[name]["scl"]
        # continuidade do quaternion entre keyframes
        for k in range(1, len(quats)):
            if quats[k].dot(quats[k - 1]) < 0.0:
                quats[k] = Quaternion((-quats[k].w, -quats[k].x, -quats[k].y, -quats[k].z))
        path = f'pose.bones["{be}"].location'
        for c in range(3):
            write_channel(_ensure_fcurve(cb, path, c), times, [v[c] for v in locs])
        path = f'pose.bones["{be}"].rotation_quaternion'
        for c in range(4):
            write_channel(_ensure_fcurve(cb, path, c), times, [q[c] for q in quats])
        path = f'pose.bones["{be}"].scale'
        for c in range(3):
            write_channel(_ensure_fcurve(cb, path, c), times, [v[c] for v in scls])


def import_animations(ds, tb, arm_obj, bone_names, settings):
    alog = settings.get("anim_logger", None)
    headers = _enumerate_anim_headers(ds, tb)
    total_warns = 0
    ok = 0
    for h in headers:
        raw = _read_tracks(ds, h)
        w0 = alog.warns if alog else 0
        anim = _decode_animation(ds, h, raw, bone_names, settings)
        w1 = alog.warns if alog else 0
        total_warns += max(0, w1 - w0)
        if anim and anim.bones:
            bake_resolved_anim(arm_obj, anim, settings)
            ok += 1
    if alog:
        alog.log(f'summary imported={ok}/{len(headers)} warnings={total_warns}')
        alog.dump()
        alog.clear()
    return ok
