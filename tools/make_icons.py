"""Resize assets/app_icon_192.png (GitHub org avatar) to the hicolor icon sizes
(dev-time only, needs Pillow):  python3 tools/make_icons.py"""
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parent.parent / "camera_installer" / "assets"
SIZES = (48, 64, 128)

src = Image.open(ASSETS / "app_icon_192.png").convert("RGBA")
for s in SIZES:
    out = ASSETS / "app_icon_{}.png".format(s)
    src.resize((s, s), Image.LANCZOS).save(out)
    print("wrote", out.name)
