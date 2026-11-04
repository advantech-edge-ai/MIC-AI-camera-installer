"""Device detection: product model + JetPack from /opt/version, SoC family
from TEGRA_CHIPID in /etc/nv_boot_control.conf (same rules as Chris's
install_camera.sh / online_mode.sh).

CF_VERSION_FILE / CF_NV_BOOT_CONF override the paths, matching Chris's
scripts, so the tool can be exercised on a non-Jetson machine.
"""
from __future__ import annotations

import os
import re
from typing import NamedTuple, Optional

VERSION_FILE = os.environ.get("CF_VERSION_FILE", "/opt/version")
NV_BOOT_CONF = os.environ.get("CF_NV_BOOT_CONF", "/etc/nv_boot_control.conf")

CHIPID_FAMILY = {"0x23": "orin", "0x26": "thor"}
FAMILY_LABEL = {"orin": "Orin", "thor": "Thor"}


class Device(NamedTuple):
    raw_version: Optional[str]   # first line of /opt/version
    model: Optional[str]         # MIC-743
    board: Optional[str]         # mic_743
    jetpack: Optional[str]       # jp7.2
    chipid: Optional[str]        # 0x26
    family: Optional[str]        # thor | orin


def parse_version_line(line: str):
    """'MIC-743_Thor_7.2_V1.0.0, 1:2f23252, ...' -> ('MIC-743', 'mic_743', 'jp7.2')."""
    header = line.replace("\r", "").strip().split(",", 1)[0]
    fields = header.split("_")
    model = fields[0].strip() if fields and fields[0].strip() else None
    board = model.lower().replace("-", "_").replace(" ", "_") if model else None
    jetpack = None
    for f in fields[1:]:
        if re.fullmatch(r"\d+\.\d+", f):
            jetpack = "jp" + f
            break
    return model, board, jetpack


def parse_chipid(text: str) -> Optional[str]:
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "TEGRA_CHIPID":
            return parts[1]
    return None


def detect(version_file: str = VERSION_FILE, nv_boot_conf: str = NV_BOOT_CONF) -> Device:
    raw = model = board = jetpack = chipid = None
    try:
        with open(version_file, encoding="utf-8", errors="replace") as f:
            raw = f.readline().strip() or None
    except OSError:
        pass
    if raw:
        model, board, jetpack = parse_version_line(raw)
    try:
        with open(nv_boot_conf, encoding="utf-8", errors="replace") as f:
            chipid = parse_chipid(f.read())
    except OSError:
        pass
    return Device(raw, model, board, jetpack, chipid, CHIPID_FAMILY.get(chipid or ""))
