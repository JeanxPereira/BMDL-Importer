"""README art, generated from a Darkspore install (needs Pillow and fontTools): the banner, the
pipeline and the section headers, set in the game's own UI fonts (EA Pirulen and Helvetica Neue
Condensed Bold, read from `UI.package`, drawn as SVG paths) and in the look of the game's front-end
frames (chamfered gunmetal panels, steel rims, red alert accents), with the DARKSPORE wordmark from
the login screen.

    python tools/readme_art.py [DARKSPORE_DATA_DIR]      writes docs/img/*.svg

The data dir is the game's `Data` folder (the one with `UI.package`); it can also come from the
DARKSPORE_DATA environment variable. Only the generated SVGs are committed; nothing extracted from
the game is kept on disk. Fan use of Maxis' lettering for this README: regenerate, never hand-edit.
"""
import base64
import io
import os
import struct
import sys

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "img")

# Palette, sampled from the front-end textures: void and panel from the login frames, steel from
# the FE frame rims, ice (core and edge) from the lit FE panel highlight, teal from the DARKSPORE
# wordmark, green from the loading-screen planet.
VOID, PANEL, PANEL_HI = "#0c0c0c", "#14151b", "#242430"
STEEL, STEEL_DIM, TEAL = "#7884a8", "#485478", "#54a89c"
ICE, ICE_HI, ICE_EDGE, GREEN, BONE = "#98c0f0", "#c0f8f8", "#7890d8", "#78d83c", "#e4e8ee"

HEADERS = {
    "overview": "Overview",
    "features": "Features",
    "requirements": "Requirements",
    "install": "Installation",
    "use": "Usage",
    "options": "Importer options",
    "materials": "Materials",
    "animations": "Animations",
    "logs": "Logs",
    "limits": "Known limitations",
    "layout": "Project layout",
    "credits": "Credits",
}


# --- Darkspore packages (DBPF 3.0, RefPack), just enough to read UI.package by name -------------

def fnv(s):
    h = 0x811C9DC5
    for c in s.lower().encode():
        h = (h * 0x01000193) & 0xFFFFFFFF
        h ^= c
    return h


def refpack(b):
    n, p = (int.from_bytes(b[2:6], "big"), 6) if b[0] & 0x80 else (int.from_bytes(b[2:5], "big"), 5)
    out = bytearray()
    while len(out) < n:
        c = b[p]
        p += 1
        if c >= 0xFC:
            plain, count, off = c & 3, 0, 0
        elif c >= 0xE0:
            plain, count, off = ((c & 0x1F) << 2) + 4, 0, 0
        elif c >= 0xC0:
            b1, b2, b3 = b[p:p + 3]
            p += 3
            plain, count, off = c & 3, ((c & 0x0C) << 6) + b3 + 5, ((c & 0x10) << 12) + (b1 << 8) + b2 + 1
        elif c >= 0x80:
            b1, b2 = b[p:p + 2]
            p += 2
            plain, count, off = (b1 >> 6) & 3, (c & 0x3F) + 4, ((b1 & 0x3F) << 8) + b2 + 1
        else:
            b1 = b[p]
            p += 1
            plain, count, off = c & 3, ((c & 0x1C) >> 2) + 3, ((c & 0x60) << 3) + b1 + 1
        out += b[p:p + plain]
        p += plain
        for _ in range(count):
            out.append(out[-off])
    return bytes(out)


# Folder and type IDs come from Spore's name registry (not FNV of the text); instances are FNV-1.
UI_FILES = {
    "sporeUIDesigner~/EAPirulen-RGDS.ttf": (0x0248E873, fnv("EAPirulen-RGDS"), 0x027C5CEF),
    "sporeUIDesigner~/EAHelveticaNeueLTCom-BdCnDS.ttf": (0x0248E873, fnv("EAHelveticaNeueLTCom-BdCnDS"), 0x027C5CEF),
    "pie_menu~/login_logo.png": (0x011C0C59, fnv("login_logo"), 0x2F7D0004),
}


def package_files(path, wanted):
    """{name: bytes} for `wanted`, a {name: (group, instance, type)} map."""
    keys = {key: name for name, key in wanted.items()}
    found = {}
    with open(path, "rb") as f:
        head = f.read(96)
        if head[:4] != b"DBPF":
            raise SystemExit(f"{path}: not a DBPF package")
        count, = struct.unpack_from("<I", head, 0x24)
        f.seek(struct.unpack_from("<I", head, 0x40)[0])
        flags, = struct.unpack("<I", f.read(4))
        t = struct.unpack("<I", f.read(4))[0] if flags & 1 else None
        g = struct.unpack("<I", f.read(4))[0] if flags & 2 else None
        if flags & 4:
            f.read(4)
        items = []
        for _ in range(count):
            tt = t if t is not None else struct.unpack("<I", f.read(4))[0]
            gg = g if g is not None else struct.unpack("<I", f.read(4))[0]
            inst, off, csize, _size, comp, _saved, _pad = struct.unpack("<IIIIhBB", f.read(20))
            name = keys.get((gg, inst, tt))
            if name:
                items.append((name, off, csize & 0x7FFFFFFF, comp == -1))
        for name, off, csize, comp in items:
            f.seek(off)
            data = f.read(csize)
            found[name] = refpack(data) if comp else data
    missing = set(wanted) - set(found)
    if missing:
        raise SystemExit(f"{path}: missing {sorted(missing)}")
    return found


# --- Text as SVG paths -------------------------------------------------------------------------

class Face:
    def __init__(self, data):
        self.font = TTFont(io.BytesIO(data))
        self.glyphs = self.font.getGlyphSet()
        self.cmap = self.font.getBestCmap()
        self.upm = self.font["head"].unitsPerEm
        self.cache = {}

    def glyph(self, ch):
        gname = self.cmap.get(ord(ch)) or self.cmap.get(ord("?"))
        if gname not in self.cache:
            pen = SVGPathPen(self.glyphs)
            self.glyphs[gname].draw(pen)
            self.cache[gname] = (pen.getCommands(), self.glyphs[gname].width)
        return self.cache[gname]

    def width(self, text, size, track=0.0):
        return sum(self.glyph(c)[1] for c in text) * size / self.upm + track * size * max(len(text) - 1, 0)

    def text(self, text, x, y, size, fill, track=0.0, anchor="start", extra=""):
        """Baseline at y. One <path> per run, glyphs placed by transform (font units, y up)."""
        if anchor == "middle":
            x -= self.width(text, size, track) / 2
        elif anchor == "end":
            x -= self.width(text, size, track)
        s = size / self.upm
        parts, pen_x = [], 0.0
        for c in text:
            d, adv = self.glyph(c)
            if d:
                parts.append(f'<path transform="translate({pen_x:.1f} 0)" d="{d}"/>')
            pen_x += adv + track * self.upm
        return (f'<g transform="translate({x:.1f} {y:.1f}) scale({s:.5f} {-s:.5f})" fill="{fill}"{extra}>'
                + "".join(parts) + "</g>")


# --- Shapes in the front-end's language --------------------------------------------------------

def chamfer(x, y, w, h, c, cuts="tl br"):
    """A rectangle with 45-degree cut corners, the shape of every Darkspore FE frame."""
    tl, tr, br, bl = (c if k in cuts.split() else 0 for k in ("tl", "tr", "br", "bl"))
    pts = [(x + tl, y), (x + w - tr, y), (x + w, y + tr), (x + w, y + h - br), (x + w - br, y + h),
           (x + bl, y + h), (x, y + h - bl), (x, y + tl)]
    return " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)


def hex_pattern(pid, r, color, opacity):
    w, h = r * 3, r * 1.7320508
    pts = lambda cx, cy: " ".join(f"{cx + r * dx:.1f},{cy + r * dy:.1f}" for dx, dy in
                                  ((1, 0), (.5, .8660254), (-.5, .8660254), (-1, 0), (-.5, -.8660254), (.5, -.8660254)))
    return (f'<pattern id="{pid}" width="{w:.1f}" height="{h:.1f}" patternUnits="userSpaceOnUse">'
            f'<g fill="none" stroke="{color}" stroke-opacity="{opacity}" stroke-width="1">'
            f'<polygon points="{pts(r, h / 2)}"/><polygon points="{pts(r * 2.5, 0)}"/>'
            f'<polygon points="{pts(r * 2.5, h)}"/></g></pattern>')


def png_uri(im):
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def svg(w, h, body, label):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{label}">{body}</svg>\n')


def write(name, text):
    with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"{name}: {len(text) // 1024} KB")


# --- The pieces --------------------------------------------------------------------------------

def banner(title, body, wordmark, icon):
    W, H = 1280, 360
    s = [f'<defs>{hex_pattern("hex", 18, STEEL, 0.07)}'
         f'<radialGradient id="glow" cx="0.2" cy="0.5" r="0.6"><stop offset="0" stop-color="{STEEL_DIM}" stop-opacity="0.55"/>'
         f'<stop offset="1" stop-color="{VOID}" stop-opacity="0"/></radialGradient>'
         f'<linearGradient id="panel" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{PANEL_HI}"/>'
         f'<stop offset="0.55" stop-color="{PANEL}"/><stop offset="1" stop-color="{VOID}"/></linearGradient>'
         f'<linearGradient id="chrome" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/>'
         f'<stop offset="0.5" stop-color="{BONE}"/><stop offset="1" stop-color="{STEEL}"/></linearGradient>'
         f'<radialGradient id="ember" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="{ICE_EDGE}" stop-opacity="0.35"/>'
         f'<stop offset="1" stop-color="{ICE_EDGE}" stop-opacity="0"/></radialGradient>'
         f'<linearGradient id="ice" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{ICE_HI}"/>'
         f'<stop offset="1" stop-color="{ICE_EDGE}"/></linearGradient></defs>',
         f'<rect width="{W}" height="{H}" fill="{VOID}"/>',
         f'<polygon points="{chamfer(8, 8, W - 16, H - 16, 28)}" fill="url(#panel)"/>',
         f'<polygon points="{chamfer(8, 8, W - 16, H - 16, 28)}" fill="url(#hex)"/>',
         f'<polygon points="{chamfer(8, 8, W - 16, H - 16, 28)}" fill="url(#glow)"/>',
         f'<polygon points="{chamfer(8, 8, W - 16, H - 16, 28)}" fill="none" stroke="{STEEL}" stroke-width="2"/>',
         f'<polygon points="{chamfer(18, 18, W - 36, H - 36, 22)}" fill="none" stroke="{STEEL_DIM}" stroke-width="1" stroke-opacity="0.7"/>',
         # top notch tab and bottom rails, after the FE frames
         f'<polygon points="{W - 420},8 {W - 396},30 {W - 120},30 {W - 98},8" fill="{STEEL_DIM}" fill-opacity="0.55"/>',
         f'<rect x="{W - 380}" y="17" width="200" height="3" fill="{STEEL}" fill-opacity="0.8"/>',
         f'<circle cx="200" cy="{H / 2}" r="150" fill="url(#ember)"/>']
    # the project's emblem
    s.append(f'<image x="80" y="{H / 2 - 120}" width="240" height="240" xlink:href="{png_uri(icon)}"/>')
    x0 = 370
    s.append(f'<image x="{x0}" y="78" width="{wordmark.width}" height="{wordmark.height}" xlink:href="{png_uri(wordmark)}"/>')
    s.append(f'<rect x="{x0 + wordmark.width + 14}" y="{78 + wordmark.height / 2 - 1}" width="{W - 96 - x0 - wordmark.width - 14}" height="2" fill="{STEEL_DIM}"/>')
    s.append(title.text("BMDL IMPORTER", x0 - 4, 194, 72, "url(#chrome)"))
    s.append(f'<polygon points="{chamfer(x0, 216, 300, 8, 6, "tl br")}" fill="url(#ice)"/>')
    s.append(f'<polygon points="{chamfer(x0 + 308, 216, 60, 8, 6, "tl br")}" fill="{ICE_EDGE}" fill-opacity="0.45"/>')
    s.append(body.text("Darkspore models, skeletons, materials and animations, into Blender", x0, 266, 30, BONE))
    s.append(title.text("mesh · skeleton · material · animation", x0, 306, 18, TEAL, track=0.08))
    return svg(W, H, "".join(s), "BMDL Importer: Darkspore models, skeletons, materials and animations into Blender")


def header(title, text):
    W, H = 1280, 72
    tw = title.width(text.lower(), 32, 0.06)
    s = [f'<defs><linearGradient id="plate" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{PANEL_HI}"/>'
         f'<stop offset="0.6" stop-color="{PANEL}"/><stop offset="1" stop-color="{VOID}"/></linearGradient></defs>',
         f'<polygon points="{chamfer(1, 1, W - 2, H - 2, 16)}" fill="url(#plate)" stroke="{STEEL_DIM}" stroke-width="1.5"/>',
         f'<polygon points="{chamfer(18, 18, 14, 36, 6, "tl br")}" fill="{ICE_HI}"/>',
         f'<polygon points="{chamfer(38, 18, 6, 36, 3, "tl br")}" fill="{ICE_EDGE}" fill-opacity="0.6"/>',
         title.text(text.lower(), 62, 50, 32, BONE, track=0.06),
         f'<polyline points="{62 + tw + 26},44 {W - 150},44 {W - 136},56 {W - 40},56" fill="none" stroke="{STEEL}" stroke-width="2"/>',
         f'<rect x="{W - 120}" y="16" width="80" height="3" fill="{STEEL_DIM}"/>']
    return svg(W, H, "".join(s), text)


def pipeline(title, body):
    W, H = 1280, 210
    steps = [("Data/*.package", "the game's DBPF archives", STEEL),
             ("DBPF-Unpacker", "unpacks .bmdl, .dds, .raster", STEEL),
             ("BMDL Importer", "mesh, rig, material, anim", ICE),
             ("Blender", "objects, armature, actions", GREEN)]
    bw, gap, y, bh = 262, 50, 46, 118
    x = (W - (4 * bw + 3 * gap)) / 2
    s = [f'<defs>{hex_pattern("hexp", 14, STEEL, 0.06)}'
         f'<linearGradient id="box" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{PANEL_HI}"/>'
         f'<stop offset="1" stop-color="{VOID}"/></linearGradient></defs>',
         f'<polygon points="{chamfer(4, 4, W - 8, H - 8, 20)}" fill="{VOID}" stroke="{STEEL_DIM}" stroke-width="1.5"/>',
         f'<polygon points="{chamfer(4, 4, W - 8, H - 8, 20)}" fill="url(#hexp)"/>']
    for i, (name, sub, color) in enumerate(steps):
        bx = x + i * (bw + gap)
        s.append(f'<polygon points="{chamfer(bx, y, bw, bh, 14)}" fill="url(#box)" stroke="{color}" stroke-width="2"/>')
        s.append(f'<rect x="{bx + 18}" y="{y + 16}" width="40" height="4" fill="{color}"/>')
        s.append(title.text(f"0{i + 1}", bx + bw - 18, y + 30, 16, color, anchor="end"))
        s.append(body.text(name, bx + 18, y + 66, 28, BONE))
        s.append(body.text(sub, bx + 18, y + 96, 19, STEEL))
        if i < 3:
            ax = bx + bw + 8
            s.append(f'<polygon points="{ax},{y + bh / 2 - 9} {ax + gap - 18},{y + bh / 2} {ax},{y + bh / 2 + 9}" fill="{STEEL}"/>')
    return svg(W, H, "".join(s), "pipeline: Darkspore packages, DBPF-Unpacker, BMDL Importer, Blender")


def main():
    data = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DARKSPORE_DATA", "")
    ui = os.path.join(data, "UI.package")
    if not os.path.isfile(ui):
        raise SystemExit("usage: python tools/readme_art.py <Darkspore Data dir>  (or set DARKSPORE_DATA)")
    files = package_files(ui, UI_FILES)
    title = Face(files["sporeUIDesigner~/EAPirulen-RGDS.ttf"])
    body = Face(files["sporeUIDesigner~/EAHelveticaNeueLTCom-BdCnDS.ttf"])
    wordmark = Image.open(io.BytesIO(files["pie_menu~/login_logo.png"])).convert("RGBA")
    icon = Image.open(os.path.join(ROOT, "res", "icon.png")).convert("RGBA")
    icon.thumbnail((240, 240), Image.Resampling.LANCZOS)

    os.makedirs(OUT, exist_ok=True)
    write("banner.svg", banner(title, body, wordmark, icon))
    write("pipeline.svg", pipeline(title, body))
    for key, text in HEADERS.items():
        write(f"h-{key}.svg", header(title, text))


if __name__ == "__main__":
    main()
