"""Decide which catalog packages fit the detected device.

Board rules follow Chris's install_camera.sh; do not change them until Chris
does:
  * mic_741 / mic_742 / mic_743 share Thor packages built for mic_742.
  * mic_741 / mic_743 prefer a package built for their own board (same
    JetPack) and only fall back to the mic_742 one when that camera has none
    -- the list carries e.g. econ STURDeCAM25 mic_743/jp7.1, which a plain
    "743 -> 742" mapping would never offer.
  * Every other board only accepts packages built for exactly that board.

Wrong SoC family is never offered. Board / JetPack mismatch or unknown device
info is offered only behind "Show drivers for other models" and needs an
extra confirmation (online_mode.sh behaviour).
"""
from __future__ import annotations

from typing import List, NamedTuple, Optional

from .catalog import Catalog, Package, jetpack_label
from .device import Device

SHARED_BOARD = "mic_742"
SHARES_WITH = {"mic_741", "mic_743"}


class Match(NamedTuple):
    package: Package
    compatible: bool
    problems: List[str]          # why it is not compatible (empty if compatible)
    via_board: Optional[str]     # set when a mic_742 package serves a 741/743


def _has_own(catalog: Catalog, camera, board: str, jetpack: Optional[str]) -> bool:
    return any(p.camera == camera and p.board == board and p.jetpack == jetpack
               for p in catalog.packages)


def classify(catalog: Catalog, device: Device) -> List[Match]:
    """Every package except those for the wrong SoC family, with a verdict."""
    out = []
    for p in catalog.packages:
        if device.family and p.family != device.family:
            continue

        problems = []
        via = None
        if not device.family:
            problems.append("SoC family unknown (TEGRA_CHIPID not readable)")

        if not device.board:
            problems.append("Device model unknown (/opt/version not readable)")
        elif p.board == device.board:
            pass
        elif (p.board == SHARED_BOARD and device.board in SHARES_WITH
              and not _has_own(catalog, p.camera, device.board, device.jetpack)):
            via = p.board
        else:
            problems.append("Built for {}, this device is {}".format(
                catalog.board_label(p.board), catalog.board_label(device.board)))

        if not device.jetpack:
            problems.append("JetPack version unknown")
        elif p.jetpack != device.jetpack:
            problems.append("Built for JetPack {}, this device has JetPack {}".format(
                jetpack_label(p.jetpack), jetpack_label(device.jetpack)))

        out.append(Match(p, not problems, problems, via))
    return out


def vendors(catalog: Catalog) -> List[str]:
    return sorted({p.vendor for p in catalog.packages})
