"""Rasterize assets/advantech_logo.svg to PNG for the Tk header (dev-time only).

Tk 8.6 cannot load SVG, and the runtime must not depend on Pillow, so the PNG
is generated once here and committed. Needs Pillow:  python3 tools/render_logo.py

Only the SVG features the logo actually uses are supported: <rect>, <polygon>,
and <path> with M/L/H/V/C/S/Z (absolute + relative). Sub-paths are combined
with the even-odd rule, which is what punches the holes in "D" and "A".
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "camera_installer" / "assets" / "advantech_logo.svg"
SUPERSAMPLE = 8
BEZIER_STEPS = 24


def _cubic(p0, p1, p2, p3):
    pts = []
    for i in range(1, BEZIER_STEPS + 1):
        t = i / BEZIER_STEPS
        u = 1 - t
        pts.append((
            u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
        ))
    return pts


def parse_path(d):
    """Return a list of sub-paths, each a list of (x, y) points."""
    tokens = re.findall(r"[MmLlHhVvCcSsZz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?", d)
    subpaths, cur = [], []
    x = y = 0.0
    start = (0.0, 0.0)
    last_ctrl = None
    cmd = None
    i = 0

    def num():
        nonlocal i
        v = float(tokens[i])
        i += 1
        return v

    while i < len(tokens):
        if re.match(r"[A-Za-z]", tokens[i]):
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                if cur:
                    subpaths.append(cur)
                cur = []
                x, y = start
                last_ctrl = None
                continue
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            nx, ny = num(), num()
            if rel:
                nx, ny = x + nx, y + ny
            if cur:
                subpaths.append(cur)
            x, y = nx, ny
            start = (x, y)
            cur = [(x, y)]
            cmd = "l" if rel else "L"  # implicit lineto after moveto
            last_ctrl = None
        elif c == "L":
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            cur.append((x, y))
            last_ctrl = None
        elif c == "H":
            nx = num()
            x = x + nx if rel else nx
            cur.append((x, y))
            last_ctrl = None
        elif c == "V":
            ny = num()
            y = y + ny if rel else ny
            cur.append((x, y))
            last_ctrl = None
        elif c in "CS":
            if c == "C":
                x1, y1 = num(), num()
                if rel:
                    x1, y1 = x + x1, y + y1
            else:
                x1, y1 = (2 * x - last_ctrl[0], 2 * y - last_ctrl[1]) if last_ctrl else (x, y)
            x2, y2, nx, ny = num(), num(), num(), num()
            if rel:
                x2, y2, nx, ny = x + x2, y + y2, x + nx, y + ny
            cur.extend(_cubic((x, y), (x1, y1), (x2, y2), (nx, ny)))
            last_ctrl = (x2, y2)
            x, y = nx, ny
        else:
            raise ValueError("unsupported path command: " + cmd)
    if cur:
        subpaths.append(cur)
    return subpaths


def render(height):
    tree = ET.parse(SRC)
    svg = tree.getroot()
    ns = {"s": "http://www.w3.org/2000/svg"}
    vb = [float(v) for v in svg.get("viewBox").split()]
    styles = dict(re.findall(r"\.(cls-\d+)\{fill:(#[0-9a-fA-F]{3,6});\}", ET.tostring(svg, encoding="unicode")))

    scale = height * SUPERSAMPLE / vb[3]
    size = (round(vb[2] * scale), round(vb[3] * scale))
    img = Image.new("RGB", size, "#000000")

    def tx(pts):
        return [((px - vb[0]) * scale, (py - vb[1]) * scale) for px, py in pts]

    for el in svg.iter():
        tag = el.tag.split("}")[-1]
        fill = styles.get(el.get("class", ""), "#000000")
        if tag == "rect":
            w, h = float(el.get("width")), float(el.get("height"))
            subs = [[(0, 0), (w, 0), (w, h), (0, h)]]
        elif tag == "polygon":
            nums = [float(v) for v in re.findall(r"-?\d+\.?\d*", el.get("points"))]
            subs = [list(zip(nums[0::2], nums[1::2]))]
        elif tag == "path":
            subs = parse_path(el.get("d"))
        else:
            continue
        mask = Image.new("1", size, 0)
        for sp in subs:
            m = Image.new("1", size, 0)
            ImageDraw.Draw(m).polygon(tx(sp), fill=1)
            mask = ImageChops.logical_xor(mask, m)
        img.paste(fill, mask=mask)

    out_size = (round(size[0] / SUPERSAMPLE), height)
    return img.resize(out_size, Image.LANCZOS)


def main():
    for h in (26,):
        out = SRC.with_name("advantech_logo_{}.png".format(h))
        render(h).save(out)
        print("wrote", out.relative_to(ROOT))


if __name__ == "__main__":
    sys.exit(main())
