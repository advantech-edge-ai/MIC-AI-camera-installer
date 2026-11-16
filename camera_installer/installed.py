"""Camera driver packages already installed on this device.

Both this tool and online_mode.sh (MIC-AI-camera-driver) copy a package into
  /opt/advantech/camera_framework/vendors/<vendor>/<sensor>/<platform>/<board>/<jetpack>/
(realsense has no <sensor> level) and run its installer there. The leaf
directories of that tree are the drivers installed so far, whichever tool was used.

A leaf only says the package was installed at some point: the boot configuration
(device tree overlay) and kernel modules in effect come from whichever vendor
installer ran last, and may be a mix of several.
"""
from __future__ import annotations

import os
import re
from typing import List, NamedTuple

from .catalog import Package, jetpack_label
from .installer import VENDORS_DIR

_JETPACK_DIR = re.compile(r"^(jp\d+(\.\d+)*|igx\d+(\.\d+)*)$", re.IGNORECASE)
_PLATFORM_ALIAS = {"agx_thor": "thor"}      # install_camera.sh stores 'thor' as 'agx_thor'


class Installed(NamedTuple):
    vendor: str
    sensor: str         # "" for realsense (no sensor level)
    platform: str       # list naming: 'thor', not 'agx_thor'
    board: str
    jetpack: str
    path: str

    @property
    def identity(self):
        return _identity(self.vendor, self.sensor, self.platform, self.board, self.jetpack)

    def label(self) -> str:
        """'otobrite / imx728 · MIC-733AO · JetPack 6.2'"""
        camera = "{} / {}".format(self.vendor, self.sensor) if self.sensor else self.vendor
        return "{} · {} · JetPack {}".format(camera, self.board.upper().replace("_", "-"),
                                            jetpack_label(self.jetpack))


def _identity(vendor, sensor, platform, board, jetpack):
    vendor = vendor.lower()
    sensor = "" if vendor == "realsense" else sensor.lower()
    platform = _PLATFORM_ALIAS.get(platform.lower(), platform.lower())
    return (vendor, sensor, platform, board.lower(), jetpack.lower())


def scan(root: str = VENDORS_DIR) -> List[Installed]:
    """Installed packages, sorted by vendor / sensor. Empty when the tree does not exist."""
    found = []
    root = os.path.normpath(root)
    for dirpath, dirnames, _ in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        parts = [] if rel == "." else rel.split(os.sep)
        if len(parts) in (4, 5) and _JETPACK_DIR.match(parts[-1]):
            if len(parts) == 5:
                vendor, sensor, platform, board, jp = parts
            else:
                vendor, platform, board, jp = parts
                sensor = ""
            platform = _PLATFORM_ALIAS.get(platform, platform)
            found.append(Installed(vendor, sensor, platform, board, jp, dirpath))
            dirnames[:] = []            # the package's own files are below this point
        elif len(parts) >= 5:
            dirnames[:] = []
        dirnames.sort()
    found.sort(key=lambda d: (d.vendor.lower(), d.sensor.lower(), d.board, d.jetpack))
    return found


def others(drivers: List[Installed], pkg: Package) -> List[Installed]:
    """Installed drivers other than `pkg` itself (re-installing the same package is not listed)."""
    me = _identity(pkg.vendor, pkg.sensor, pkg.platform, pkg.board, pkg.jetpack)
    return [d for d in drivers if d.identity != me]


class Conflict(NamedTuple):
    title: str
    drivers: List[Installed]
    note: str


def conflict(drivers: List[Installed], pkg: Package):
    """Warning for the confirm step when other drivers are installed, else None."""
    other = others(drivers, pkg)
    if not other:
        return None
    title = ("Another camera driver is already installed" if len(other) == 1 else
             "{} other camera drivers are already installed".format(len(other)))
    note = ("After installing {} / {}, switching back to {} may require changing the boot "
            "settings, or even reflashing the system."
            .format(pkg.vendor, pkg.sensor, "it" if len(other) == 1 else "them"))
    return Conflict(title, other, note)
