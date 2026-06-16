import struct
import os
import re
from dataclasses import dataclass
from mathutils import Quaternion

def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]

def _i32(b, o):
    return struct.unpack_from("<i", b, o)[0]

def _cstr(b, o):
    L = len(b)
    e = o
    while e < L and b[e] != 0:
        e += 1
    return b[o:e].decode("ascii", "ignore")

def _half_to_float(h):
    s = (h >> 15) & 1
    e = (h >> 10) & 31
    f = h & 1023
    if e == 0:
        return ((-1.0) if s else 1.0) * (f / 1024.0) * (2**-14) if f else ((-0.0) if s else 0.0)
    if e == 31:
        return float("nan") if f else (float("-inf") if s else float("inf"))
    return ((-1.0) if s else 1.0) * (1.0 + f / 1024.0) * (2.0 ** (e - 15))

def _type_size(t):
    if t == 0:
        return 4
    if t == 1:
        return 8
    if t == 2:
        return 12
    if t == 3:
        return 16
    if t == 5:
        return 4
    if t == 6:
        return 4
    if t == 7:
        return 8
    if t == 8:
        return 4
    if t == 15:
        return 4
    if t == 16:
        return 8
    return 4

def _align(x, a=4):
    r = x % a
    return x if r == 0 else x + (a - r)

def _parse_numbers(s):
    if not isinstance(s, str):
        return []
    xs = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s.replace(",", " "))
    try:
        return [float(v) for v in xs]
    except Exception:
        return []

def _extract_params(streams):
    out = {}
    for e in streams or []:
        k = (e.get("key") or "").lower()
        v = e.get("value") or ""
        nums = _parse_numbers(v)
        if not k:
            continue
        if len(nums) == 0:
            out[k] = v
        elif len(nums) == 1:
            out[k] = nums[0]
        else:
            out[k] = tuple(nums)
    return out

class BMDLv2:
    def __init__(self, d):
        self.d = d
        if d[4:8] != b"bmdl" or _u32(d, 8) != 2:
            raise ValueError("unsupported")
        self.base = _u32(d, 12)
        self.graph_size = _u32(d, 16)
        self.graph = d[self.base : self.base + self.graph_size]

    def tbmdl(self):
        o = self.base
        return {
            "model_ptr": _u32(self.d, o + 0),
            "skeleton_ptr": _u32(self.d, o + 4),
            "num_anims": _i32(self.d, o + 8),
            "anims_ptr": _u32(self.d, o + 12),
        }

    def model(self, ptr):
        o = self.base + ptr
        name_ptr = _u32(self.d, o + 32)
        return {
            "name": _cstr(self.d, self.base + name_ptr) if name_ptr else None,
            "num_materials": _i32(self.d, o + 40),
            "materials_ptr": _u32(self.d, o + 44),
            "num_meshes": _i32(self.d, o + 48),
            "meshes_ptr": _u32(self.d, o + 52),
            "num_instances": _i32(self.d, o + 56),
            "instances_ptr": _u32(self.d, o + 60),
        }

    def mesh_flexible(self, meshes_ptr, idx):
        o0 = self.base + meshes_ptr + idx * 64
        best = None
        for s in range(0, 84, 4):
            o = o0 + s
            if o + 56 > self.base + self.graph_size:
                break
            try:
                struct.unpack_from("<ffffffff", self.d, o)
            except Exception:
                continue
            name_ptr = _u32(self.d, o + 32)
            nh = _u32(self.d, o + 36)
            fl = _u32(self.d, o + 40)
            pitch = _u32(self.d, o + 44)
            vdecl = _u32(self.d, o + 48)
            vb = _u32(self.d, o + 52)
            ib = _u32(self.d, o + 56)
            sv = si = 0
            if o + 62 <= self.base + self.graph_size:
                sv = struct.unpack_from("<h", self.d, o + 60)[0]
                si = struct.unpack_from("<h", self.d, o + 62)[0]
            if not (1 <= pitch <= 4096):
                continue
            if any(x >= self.graph_size or x < 0 for x in (vdecl, vb, ib)):
                continue
            decl = self.vdecl(vdecl)
            if not _validate_decl(decl, pitch):
                continue
            name = _cstr(self.d, self.base + name_ptr) if name_ptr and name_ptr < self.graph_size else None
            cand = {
                "shift": s,
                "name": name,
                "name_hash": nh,
                "flags": fl,
                "pitch": pitch,
                "vdecl_ptr": vdecl,
                "vb_ptr": vb,
                "ib_ptr": ib,
                "sizevb": sv,
                "sizeib": si,
            }
            best = cand
            break
        if best is None:
            raise ValueError("mesh parse failed")
        return best

    def vdecl(self, ptr):
        res = []
        o = self.base + ptr
        limit = self.base + self.graph_size
        for _ in range(0, 64):
            if o + 8 > limit:
                break
            stream, offs = struct.unpack_from("<HH", self.d, o)
            if stream == 0xFF:
                break
            typ, method, usage, idx = struct.unpack_from("<BBBB", self.d, o + 4)
            res.append({"stream": stream, "offset": offs, "type": typ, "method": method, "usage": usage, "usage_index": idx})
            o += 8
        return res

    def instances(self, ptr, n):
        out = []
        s = 44
        for i in range(max(0, n)):
            o = self.base + ptr + i * s
            if o + s > self.base + self.graph_size:
                break
            im = _u32(self.d, o + 32)
            nr = _u32(self.d, o + 36)
            rp = _u32(self.d, o + 40)
            out.append({"imesh": im, "num_renderables": nr, "renderables_ptr": rp})
        return out

    def renderables(self, ptr, n):
        out = []
        s = 44
        for i in range(n):
            o = self.base + ptr + i * s
            if o + s > self.base + self.graph_size:
                break
            im = _u32(self.d, o + 32)
            st = _i32(self.d, o + 36)
            ct = _i32(self.d, o + 40)
            out.append({"imat": im, "start": st, "count": ct})
        return out

    def nv_pairs16(self, ptr, n):
        out = []
        s = 16
        for i in range(max(0, n)):
            o = self.base + ptr + i * s
            if o + s > self.base + self.graph_size:
                break
            np = _u32(self.d, o + 0)
            nh = _u32(self.d, o + 4)
            vp = _u32(self.d, o + 8)
            vh = _u32(self.d, o + 12)
            name = _cstr(self.d, self.base + np) if np and np < self.graph_size else ""
            val = _cstr(self.d, self.base + vp) if vp and vp < self.graph_size else ""
            out.append({"key": name, "key_hash": nh, "value": val, "value_hash": vh})
        return out

    def nv_pairs(self, ptr, n):
        out = []
        s = 8
        for i in range(max(0, n)):
            o = self.base + ptr + i * s
            if o + s > self.base + self.graph_size:
                break
            np = _u32(self.d, o + 0)
            vp = _u32(self.d, o + 4)
            name = _cstr(self.d, self.base + np) if np and np < self.graph_size else ""
            val = _cstr(self.d, self.base + vp) if vp and vp < self.graph_size else ""
            out.append((name, val))
        return out

    def _mat_params(self, params_ptr, n, floats_ptr, num_floats):
        # bmdl_MatParam (16B): {name_ptr, name_hash, float_offset, dimension}
        # -> slice [float_offset:float_offset+dim] of the custom_floats constant buffer.
        floats = []
        if floats_ptr and num_floats > 0:
            for i in range(num_floats):
                fo = self.base + floats_ptr + i * 4
                if fo + 4 > self.base + self.graph_size:
                    break
                floats.append(struct.unpack_from("<f", self.d, fo)[0])
        out = {}
        if params_ptr and n > 0:
            for i in range(n):
                o = self.base + params_ptr + i * 16
                if o + 16 > self.base + self.graph_size:
                    break
                np = _u32(self.d, o + 0)
                off = _u32(self.d, o + 8)
                dim = _u32(self.d, o + 12)
                name = _cstr(self.d, self.base + np) if np and np < self.graph_size else ""
                if not name or off + dim > len(floats):
                    continue
                sl = floats[off:off + dim]
                out[name] = sl[0] if dim == 1 else tuple(sl)
        return out, floats

    def materials(self, ptr, n):
        out = []
        s = 44
        for i in range(max(0, n)):
            o = self.base + ptr + i * s
            if o + s > self.base + self.graph_size:
                break
            name_ptr = _u32(self.d, o + 0)
            name = _cstr(self.d, self.base + name_ptr) if name_ptr and name_ptr < self.graph_size else None
            name_hash = _u32(self.d, o + 4)
            flags = _u32(self.d, o + 8)
            num_params = _i32(self.d, o + 12)
            params_ptr = _u32(self.d, o + 16)
            num_floats = _i32(self.d, o + 20)
            floats_ptr = _u32(self.d, o + 24)
            num_textures = _i32(self.d, o + 28)
            textures_ptr = _u32(self.d, o + 32)
            num_streams = _i32(self.d, o + 36)
            streams_ptr = _u32(self.d, o + 40)
            tex = self.nv_pairs16(textures_ptr, num_textures) if num_textures > 0 and textures_ptr > 0 else []
            streams = self.nv_pairs16(streams_ptr, num_streams) if num_streams > 0 and streams_ptr > 0 else []
            params, custom_floats = self._mat_params(params_ptr, num_params, floats_ptr, num_floats)
            out.append({
                "index": i,
                "name": name,
                "shader": name,            # the material name IS the shader name
                "name_hash": name_hash,
                "flags": flags,
                "textures": tex,
                "streams": streams,
                "params": params,
                "custom_floats": custom_floats,
            })
        return out

    def skeleton(self, ptr):
        if ptr == 0:
            return None
        o = self.base + ptr
        if o + 8 > self.base + self.graph_size:
            return None
        n = _i32(self.d, o + 0)
        bp = _u32(self.d, o + 4)
        if n <= 0 or bp == 0:
            return None
        return {"num_bones": n, "bones_ptr": bp}

    def bones(self, ptr, n):
        out = []
        s = 80
        for i in range(max(0, n)):
            o = self.base + ptr + i * s
            if o + s > self.base + self.graph_size:
                break
            np = _u32(self.d, o + 0)
            name = _cstr(self.d, self.base + np) if np and np < self.graph_size else f"bone_{i}"
            _ = _u32(self.d, o + 4)
            parent = _i32(self.d, o + 8)
            _pad = _u32(self.d, o + 12)
            m = struct.unpack_from("<" + "f" * 16, self.d, o + 16)
            out.append({"index": i, "name": name, "parent": parent, "inv_bind": m})
        return out
    
def _score_mode(d, base, m, rels, ib_size, factor, graph_size, vcount):
    ib_end = base + graph_size
    tri_total = 0
    tri_valid = 0
    for r in rels:
        c = r["count"]
        st = r["start"]
        if c <= 0 or st < 0:
            continue
        nidx = c * factor
        off = st * factor
        src = base + m["ib_ptr"] + off * ib_size
        end = src + nidx * ib_size
        if end > ib_end:
            continue
        if ib_size == 2:
            idxs = struct.unpack_from("<" + "H" * nidx, d, src)
        else:
            idxs = struct.unpack_from("<" + "I" * nidx, d, src)
        tri = nidx // 3
        tri_total += tri
        for t in range(tri):
            a = idxs[t * 3]
            b = idxs[t * 3 + 1]
            c2 = idxs[t * 3 + 2]
            if a < vcount and b < vcount and c2 < vcount:
                tri_valid += 1
    return tri_valid, tri_total


def _infer_stride_bytes(pitch, decl):
    return pitch * 4


def _validate_decl(decl, pitch_words):
    if not decl:
        return False
    stride = pitch_words * 4
    if stride <= 0 or stride > 4096 or (stride % 4) != 0:
        return False
    need = 0
    have_pos = False
    for e in decl:
        end = e["offset"] + _type_size(e["type"])
        if e["offset"] < 0 or end > stride:
            return False
        if e["usage"] == 0 and e["usage_index"] == 0 and e.get("stream", 0) == 0 and e["type"] in (2, 3):
            have_pos = True
        if end > need:
            need = end
    if _align(need, 4) > stride:
        return False
    return have_pos


def _decode_vertices(d, base, vb_ptr, vstart, count, stride, decl):
    pos_off = None
    for e in decl:
        if e["stream"] == 0 and e["usage"] == 0 and e["usage_index"] == 0:
            pos_off = e["offset"]
    if pos_off is None:
        return None
    verts = [0.0] * (count * 3)
    for i in range(count):
        o = base + vb_ptr + (vstart + i) * stride
        x, y, z = struct.unpack_from("<fff", d, o + pos_off)
        j = i * 3
        verts[j : j + 3] = [x, y, z]
    return verts


def _decode_normals(d, base, vb_ptr, vstart, count, stride, decl):
    nrm_off = nrm_type = None
    for e in decl:
        if e["stream"] == 0 and e["usage"] == 1 and e["usage_index"] == 0:
            nrm_off, nrm_type = e["offset"], e["type"]
    if nrm_off is None:
        return None
    nrms = [0.0] * (count * 3)
    for i in range(count):
        o = base + vb_ptr + (vstart + i) * stride
        if nrm_type == 8:
            b0, b1, b2, b3 = struct.unpack_from("<BBBB", d, o + nrm_off)
            nx, ny, nz = (b0/255.0)*2.0-1.0, (b1/255.0)*2.0-1.0, (b2/255.0)*2.0-1.0
        elif nrm_type == 2:
            nx, ny, nz = struct.unpack_from("<fff", d, o + nrm_off)
        elif nrm_type == 3:
            nx, ny, nz, _ = struct.unpack_from("<ffff", d, o + nrm_off)
        else:
            nx, ny, nz = 0.0, 0.0, 1.0
        j = i * 3
        nrms[j : j + 3] = [nx, ny, nz]
    return nrms


def _decode_colors(d, base, vb_ptr, vstart, count, stride, decl):
    col_off = col_type = None
    for e in decl:
        if e["stream"] == 0 and e["usage"] == 5 and e["usage_index"] == 0:
            col_off, col_type = e["offset"], e["type"]
    if col_off is None:
        return None
    cols = [0.0] * (count * 4)
    for i in range(count):
        o = base + vb_ptr + (vstart + i) * stride
        if col_type == 8:
            b0, b1, b2, b3 = struct.unpack_from("<BBBB", d, o + col_off)
            r, g, b, a = b0/255.0, b1/255.0, b2/255.0, b3/255.0
        elif col_type == 3:
            r, g, b, a = struct.unpack_from("<ffff", d, o + col_off)
        else:
            r, g, b, a = 1.0, 1.0, 1.0, 1.0
        j = i * 4
        cols[j : j + 4] = [r, g, b, a]
    return cols


def _decode_uv_sets(d, base, vb_ptr, vstart, count, stride, decl):
    uv_e = [e for e in decl if e["stream"] == 0 and e["usage"] == 4]
    if not uv_e:
        return {}
    uv_sets = {}
    for e in uv_e:
        idx = e["usage_index"]
        off = e["offset"]
        typ = e["type"]
        vals = [0.0] * (count * 2)
        if typ == 1:
            for i in range(count):
                u, v = struct.unpack_from("<ff", d, base + vb_ptr + (vstart + i) * stride + off)
                j = i * 2
                vals[j : j + 2] = [u, v]
        elif typ == 15:
            for i in range(count):
                u16, v16 = struct.unpack_from("<HH", d, base + vb_ptr + (vstart + i) * stride + off)
                u, v = _half_to_float(u16), _half_to_float(v16)
                j = i * 2
                vals[j : j + 2] = [u, v]
        else:
            for i in range(count):
                u, v = struct.unpack_from("<ff", d, base + vb_ptr + (vstart + i) * stride + off)
                j = i * 2
                vals[j : j + 2] = [u, v]
        if idx not in uv_sets:
            uv_sets[idx] = vals
    return dict(sorted(uv_sets.items(), key=lambda kv: kv[0]))


def _scan_max_for_mode(d, base, ib_ptr, renderables, index_size, factor, ib_end):
    mxi = 0
    for r in renderables:
        c = r["count"]
        st = r["start"]
        if c <= 0 or st < 0:
            return 0, False
        nidx = c * factor
        off = st * factor
        src = base + ib_ptr + off * index_size
        end = src + nidx * index_size
        if end > ib_end:
            return 0, False
        if index_size == 2:
            chunk = struct.unpack_from("<" + "H" * nidx, d, src)
        else:
            chunk = struct.unpack_from("<" + "I" * nidx, d, src)
        if chunk:
            mm = max(chunk)
            mxi = mm if mm > mxi else mxi
    return mxi, True


def _read_renderable_indices(d, base, ib_ptr, r, ib_size, factor, ib_end):
    c = r["count"]
    st = r["start"]
    if c <= 0 or st < 0:
        return None
    nidx = c * factor
    off = st * factor
    src = base + ib_ptr + off * ib_size
    end = src + nidx * ib_size
    if end > ib_end:
        return None
    if ib_size == 2:
        return list(struct.unpack_from("<" + "H" * nidx, d, src))
    else:
        return list(struct.unpack_from("<" + "I" * nidx, d, src))


def _expected_tris(rels, factor):
    tot = 0
    for r in rels:
        c = r.get("count", 0)
        st = r.get("start", 0)
        if c > 0 and st >= 0:
            if factor == 1:
                tot += c // 3
            else:
                tot += c
    return max(tot, 0)


def _compute_vb_cap(m, stride, graph_size):
    cap = None
    if m["vb_ptr"] < m["ib_ptr"]:
        diff = m["ib_ptr"] - m["vb_ptr"]
        if diff > 0 and diff % stride == 0:
            cap = diff // stride
    if m.get("sizevb", 0) > 0:
        cap = min(cap, m["sizevb"]) if cap is not None else m["sizevb"]
    if cap is None:
        cap = max(0, (graph_size - m["vb_ptr"]) // max(stride, 1))
    return cap

@dataclass(slots=True)
class AnimHeader:
    name: str
    duration: float
    num_tracks: int
    tracks_ptr: int
    next_ptr: int

@dataclass(slots=True)
class RawTrack:
    bone_index: int
    category: int
    flags: int
    times_ptr: int
    values_ptr: int

@dataclass(slots=True)
class ResolvedAnim:
    name: str
    duration: float
    bones: dict            # {bone: {"location":[...], "rotation_quaternion":[...], "rotation_euler":[...], "scale":[...]}}
    timeline: dict         # {bone: { "location":[t...], "rotation_quaternion":[t...], "rotation_euler":[t...], "scale":[t...] }}

def _enumerate_anim_headers(ds, tb):
    out = []
    n = tb.get("num_anims", 0)
    ptr = tb.get("anims_ptr", 0)
    if n <= 0 or ptr <= 0:
        return out
    o = ds.base + ptr
    for i in range(n):
        np = _u32(ds.d, o + 0)
        name = _cstr(ds.d, ds.base + np) if 0 < np < ds.graph_size else f"anim_{i}"
        _ = _u32(ds.d, o + 4)
        duration = struct.unpack_from("<f", ds.d, o + 8)[0]
        num_tracks = _u32(ds.d, o + 12)
        tracks_ptr = _u32(ds.d, o + 16)
        out.append(AnimHeader(name, float(duration), int(num_tracks), int(tracks_ptr), 0))
        o += 20
    return out


def _read_tracks(ds, header):
    out = []
    o = ds.base + header.tracks_ptr
    s = 20
    for i in range(max(0, header.num_tracks)):
        b = _i32(ds.d, o + 0)
        c = _u32(ds.d, o + 4)
        f = _u32(ds.d, o + 8)
        tp = _u32(ds.d, o + 12)
        vp = _u32(ds.d, o + 16)
        out.append(RawTrack(int(b), int(c), int(f), int(tp), int(vp)))
        o += s
    return out


def _norm_quat_wxyz(q, eps=1e-12):
    w, x, y, z = q
    n = (w*w + x*x + y*y + z*z) ** 0.5
    return (w/n, x/n, y/n, z/n)

def _quats_from_xyzw(vals):
    out = []
    prev = None
    for v in vals:
        q = (v[3], v[0], v[1], v[2])
        q = _norm_quat_wxyz(q)
        if prev is not None:
            if (prev[0]*q[0] + prev[1]*q[1] + prev[2]*q[2] + prev[3]*q[3]) < 0.0:
                q = (-q[0], -q[1], -q[2], -q[3])
        out.append(q)
        prev = q
    return out


def _decode_animation(ds, header, raw, bone_names, settings):
    dims = {1: 3, 2: 4, 3: 3}
    bones = {}
    timeline = {}
    alog = settings.get("anim_logger", None)
    
    for i, r in enumerate(raw):
        if not (0 <= r.bone_index < len(bone_names)):
            continue
        if not (0 < r.times_ptr < r.values_ptr < ds.graph_size):
            if alog:
                alog.log(f't={i} bone="{bone_names[r.bone_index]}" cat={"PRS"[r.category-1]} keys=0 warn=PTR_RANGE')
            continue
        
        n = (r.values_ptr - r.times_ptr) // 4
        k = dims.get(r.category, 3)
        nvals = n * k
        a_t = ds.base + r.times_ptr
        a_v = ds.base + r.values_ptr
        limit = ds.base + ds.graph_size
        
        if a_v + nvals * 4 > limit:
            maxn = max(0, (limit - a_v) // 4 // max(k, 1))
            if alog:
                alog.log(f't={i} bone="{bone_names[r.bone_index]}" cat={"PRS"[r.category-1]} keys={n} warn=BUF_OVERFLOW')
            n = maxn
            nvals = n * k
        
        if n <= 0:
            continue
        
        bt_all = [struct.unpack_from("<f", ds.d, a_t + j * 4)[0] for j in range(n)]
        bt = [t for t in bt_all if 0.0 <= t <= max(header.duration, 0.0)]
        if not bt:
            bt = [0.0]
        
        bv = [struct.unpack_from("<f", ds.d, a_v + j * 4)[0] for j in range(nvals)]
        
        bname = bone_names[r.bone_index]
        bones.setdefault(bname, {})
        timeline.setdefault(bname, {})
        
        warn = []
        if not _is_monotonic(bt):
            warn.append("NONMONO_T")
            bt = sorted(bt)
        
        if r.category == 1:
            nn = min(len(bt), len(bv) // 3)
            if nn <= 0:
                continue
            vals = [tuple(bv[j * 3:(j + 1) * 3]) for j in range(nn)]
            bt = bt[:nn]
            bones[bname]["location"] = vals
            timeline[bname]["location"] = bt
        
        elif r.category == 2:
            nn = min(len(bt), len(bv) // 4)
            if nn <= 0:
                continue
            vals = [tuple(bv[j * 4:(j + 1) * 4]) for j in range(nn)]
            bt = bt[:nn]
            
            layout = (settings.get("anim_quat_layout") or "xyzw").lower()
            if not (len(layout) == 4 and set(layout) == set("wxyz")):
                layout = "xyzw"
            idx = {ch: layout.index(ch) for ch in "wxyz"}
            signs = (settings.get("anim_quat_signs") or "++++")
            signs = (signs + "++++")[:4]
            sgn = [1.0 if c != "-" else -1.0 for c in signs]
            
            quats = []
            prev = None
            for v in vals:
                w = v[idx["w"]] * sgn[0]
                x = v[idx["x"]] * sgn[1]
                y = v[idx["y"]] * sgn[2]
                z = v[idx["z"]] * sgn[3]
                w, x, y, z = _norm_quat_wxyz((w, x, y, z))
                if prev is not None and (prev[0]*w + prev[1]*x + prev[2]*y + prev[3]*z) < 0.0:
                    w, x, y, z = -w, -x, -y, -z
                quats.append((w, x, y, z))
                prev = (w, x, y, z)
            
            bones[bname]["rotation_quaternion"] = quats
            timeline[bname]["rotation_quaternion"] = bt
            
            if settings.get("anim_rotation_mode", "QUATERNION") == "EULER_XYZ":
                e = [Quaternion(q).to_euler('XYZ') for q in quats]
                bones[bname]["rotation_euler"] = [(x.x, x.y, x.z) for x in e]
                timeline[bname]["rotation_euler"] = bt
        
        elif r.category == 3:
            nn = min(len(bt), len(bv) // 3)
            if nn <= 0:
                continue
            vals = [tuple(bv[j * 3:(j + 1) * 3]) for j in range(nn)]
            bt = bt[:nn]
            bones[bname]["scale"] = vals
            timeline[bname]["scale"] = bt
        
        if alog and warn:
            alog.log(f't={i} bone="{bname}" cat={"PRS"[r.category-1]} keys={len(bt)} warn={".".join(warn)}')
    
    return ResolvedAnim(header.name, header.duration, bones, timeline) if bones else None

def _is_monotonic(x):
    return all(x[i] <= x[i+1] for i in range(len(x)-1))