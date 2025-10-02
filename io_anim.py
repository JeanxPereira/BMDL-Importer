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


def _rot_from_m3(m3):
    if m3 is None:
        return None
    q = m3.to_quaternion()
    try:
        q.normalize()
    except:
        pass
    return q


def axis_apply_loc(v, m3):
    if not isinstance(v, Vector):
        v = Vector(v)
    if m3 is None:
        return (v.x, v.y, v.z)
    r = m3 @ v
    return (r.x, r.y, r.z)


def axis_apply_quat(q, m3):
    qq = Quaternion((q[0], q[1], q[2], q[3]))
    if m3 is not None:
        qm = m3.to_quaternion()
        qq = qm @ qq @ qm.inverted()
    qq.normalize()
    return (qq.w, qq.x, qq.y, qq.z)


def axis_apply_scale(s, m3):
    if not isinstance(s, Vector):
        s = Vector(s)
    if m3 is None:
        return (s.x, s.y, s.z)
    out = [0.0, 0.0, 0.0]
    for i in range(3):
        row = (m3[i][0], m3[i][1], m3[i][2])
        j = 0
        if abs(row[1]) > abs(row[j]):
            j = 1
        if abs(row[2]) > abs(row[j]):
            j = 2
        sign = 1.0 if row[j] >= 0.0 else -1.0
        val = (s.x, s.y, s.z)[j]
        out[i] = sign * val
    return (out[0], out[1], out[2])



def quat_to_euler_xyz(q):
    e = Quaternion(q).to_euler('XYZ')
    return (e.x, e.y, e.z)


def ensure_action(arm_obj, name):
    if not arm_obj.animation_data:
        arm_obj.animation_data_create()
    act = bpy.data.actions.get(name) or bpy.data.actions.new(name)
    arm_obj.animation_data.action = act
    return act


def ensure_group(act, name):
    return act.groups.get(name) or act.groups.new(name)


def ensure_fcurve(act, bone, path, idx, logger=None):
    g = ensure_group(act, bone)
    for fc in act.fcurves:
        if fc.data_path == path and fc.array_index == idx:
            if fc.group is None:
                fc.group = g
            if logger:
                logger.log(f'[fcurve] reuse path="{path}" idx={idx} group="{g.name}"')
            return fc
    fc = act.fcurves.new(path, index=idx, action_group=bone)
    if logger:
        logger.log(f'[fcurve] create path="{path}" idx={idx} group="{bone}"')
    return fc


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


def map_frames(times, duration, settings):
    if not times:
        return []
    fps = bpy.context.scene.render.fps or 24
    mode = settings.get("anim_time_mode", "FILE_FRAMES")
    tmax = max(times)
    dur = max(float(duration or 0.0), float(tmax or 0.0))
    if mode == "FILE_FRAMES":
        s = dur if (tmax <= 1.05 and dur > 1.5) else 1.0
        return [float(t) * s for t in times]
    sec = [float(t) * dur for t in times] if (tmax <= 1.05 and dur > 1.5) else [float(t) for t in times]
    return [t * fps for t in sec]


def bake_resolved_anim(arm_obj, anim, settings):
    act = ensure_action(arm_obj, anim.name)
    alog = settings.get("anim_logger", None)
    m3 = settings.get("anim_m3") or settings.get("axis_m3")
    rotmode = "QUATERNION"
    if alog:
        alog.log(f'[anim] name="{anim.name}" duration={round(anim.duration,6)} bones={len(anim.bones)} rotmode={rotmode}')
    data_bones = arm_obj.data.bones

    rest_R_chain = {}
    rest_R_chain_inv = {}
    rest_t_abs = {}
    rest_q_local = {}

    def build_rest_chain(b):
        if b.name in rest_R_chain:
            return
        if b.parent:
            build_rest_chain(b.parent)
            Rp = rest_R_chain[b.parent.name]
            tp = rest_t_abs[b.parent.name]
            Rb = b.matrix_local.to_3x3()
            tb = b.matrix_local.to_translation()
            Rc = Rp @ Rb
            tc = tp + (Rp @ tb)
            rest_R_chain[b.name] = Rc
            rest_R_chain_inv[b.name] = Rc.inverted()
            rest_t_abs[b.name] = tc
        else:
            Rb = b.matrix_local.to_3x3()
            tb = b.matrix_local.to_translation()
            rest_R_chain[b.name] = Rb
            rest_R_chain_inv[b.name] = Rb.inverted()
            rest_t_abs[b.name] = tb
        rest_q_local[b.name] = b.matrix_local.to_quaternion()

    for b in data_bones:
        build_rest_chain(b)

    for bone, data in anim.bones.items():
        pb = arm_obj.pose.bones.get(bone) if arm_obj and arm_obj.pose else None
        if pb:
            pb.rotation_mode = rotmode
        be = bone.replace('"', '\\"')

        t_loc_raw = anim.timeline.get(bone, {}).get("location", [])
        t_rot_raw = anim.timeline.get(bone, {}).get("rotation_quaternion", []) or anim.timeline.get(bone, {}).get("rotation_euler", [])
        t_scl_raw = anim.timeline.get(bone, {}).get("scale", [])

        if "location" in data:
            tl = map_frames(list(t_loc_raw), anim.duration, settings)
            if not tl and data["location"]:
                tl = list(range(len(data["location"])))
            Rc_inv = rest_R_chain_inv.get(bone)
            t_rest = rest_t_abs.get(bone)
            loc = []
            for v in data["location"]:
                la = Vector(axis_apply_loc(v, m3))
                d = la - t_rest if t_rest is not None else la
                if Rc_inv is not None:
                    d = Rc_inv @ d
                loc.append((d.x, d.y, d.z))
            path = f'pose.bones["{be}"].location'
            for i in range(3):
                fc = ensure_fcurve(act, bone, path, i, alog)
                write_channel(fc, tl, [v[i] for v in loc])

        if rotmode == "QUATERNION" and ("rotation_quaternion" in data or "rotation_euler" in data):
            tr = map_frames(list(t_rot_raw), anim.duration, settings)
            if not tr:
                nkeys = len(data.get("rotation_quaternion", [])) or len(data.get("rotation_euler", []))
                if nkeys:
                    tr = list(range(nkeys))
            q_rest = rest_q_local.get(bone)
            rq = []
            prev = None
            if "rotation_quaternion" in data:
                for q in data["rotation_quaternion"]:
                    qa = Quaternion(axis_apply_quat(q, m3))
                    dq = (qa.to_matrix() @ q_rest.to_matrix().inverted()).to_quaternion() if q_rest else qa
                    if prev and (prev.w*dq.w + prev.x*dq.x + prev.y*dq.y + prev.z*dq.z) < 0.0:
                        dq = Quaternion((-dq.w, -dq.x, -dq.y, -dq.z))
                    rq.append((dq.w, dq.x, dq.y, dq.z))
                    prev = dq
            else:
                for e0 in data["rotation_euler"]:
                    qa0 = Euler(e0, 'XYZ').to_quaternion()
                    qa = Quaternion(axis_apply_quat((qa0.w, qa0.x, qa0.y, qa0.z), m3))
                    dq = (qa.to_matrix() @ q_rest.to_matrix().inverted()).to_quaternion() if q_rest else qa
                    if prev and (prev.w*dq.w + prev.x*dq.x + prev.y*dq.y + prev.z*dq.z) < 0.0:
                        dq = Quaternion((-dq.w, -dq.x, -dq.y, -dq.z))
                    rq.append((dq.w, dq.x, dq.y, dq.z))
                    prev = dq
            path = f'pose.bones["{be}"].rotation_quaternion'
            for i in range(4):
                fc = ensure_fcurve(act, bone, path, i, alog)
                write_channel(fc, tr, [v[i] for v in rq])

        if rotmode == "EULER_XYZ":
            tr = map_frames(list(t_rot_raw), anim.duration, settings)
            if not tr:
                nkeys = len(data.get("rotation_quaternion", [])) or len(data.get("rotation_euler", []))
                if nkeys:
                    tr = list(range(nkeys))
            q_rest = rest_q_local.get(bone)
            re_vals = []
            if "rotation_quaternion" in data:
                for q in data["rotation_quaternion"]:
                    qa = Quaternion(axis_apply_quat(q, m3))
                    dq = (qa.to_matrix() @ q_rest.to_matrix().inverted()).to_quaternion() if q_rest else qa
                    e = dq.to_euler('XYZ')
                    re_vals.append((e.x, e.y, e.z))
            else:
                for e0 in data["rotation_euler"]:
                    qa0 = Euler(e0, 'XYZ').to_quaternion()
                    qa = Quaternion(axis_apply_quat((qa0.w, qa0.x, qa0.y, qa0.z), m3))
                    dq = (qa.to_matrix() @ q_rest.to_matrix().inverted()).to_quaternion() if q_rest else qa
                    e = dq.to_euler('XYZ')
                    re_vals.append((e.x, e.y, e.z))
            if re_vals:
                path = f'pose.bones["{be}"].rotation_euler'
                for i in range(3):
                    fc = ensure_fcurve(act, bone, path, i, alog)
                    write_channel(fc, tr, [v[i] for v in re_vals])

        if "scale" in data:
            ts = map_frames(list(t_scl_raw), anim.duration, settings)
            if not ts and data["scale"]:
                ts = list(range(len(data["scale"])))
            scl = [axis_apply_scale(v, m3) for v in data["scale"]]
            path = f'pose.bones["{be}"].scale'
            for i in range(3):
                fc = ensure_fcurve(act, bone, path, i, alog)
                write_channel(fc, ts, [v[i] for v in scl])


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
        wdelta = max(0, w1 - w0)
        total_warns += wdelta
        if anim and anim.bones:
            bake_resolved_anim(arm_obj, anim, settings)
            ok += 1
    if alog:
        alog.log(f'summary imported={ok}/{len(headers)} warnings={total_warns}')
        alog.dump()
        alog.clear()
    return ok