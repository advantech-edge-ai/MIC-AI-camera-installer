"""Start-up system check (step 1), shared by GUI and TUI."""
from __future__ import annotations

from typing import Callable, NamedTuple, Optional

from . import catalog as cat
from . import device as dev

ROWS = ("network", "list", "model", "jetpack", "soc")
ROW_TITLES = {
    "network": "Network",
    "list": "Driver list",
    "model": "Device model",
    "jetpack": "JetPack",
    "soc": "SoC family",
}


class Row(NamedTuple):
    name: str
    state: str          # ok | warn | err | skip
    value: str
    hint: str = ""


class Result(NamedTuple):
    catalog: Optional[cat.Catalog]
    device: dev.Device
    blocking: bool      # True -> cannot go on to step 2


def run(list_url: str, report: Callable[[Row], None],
        running: Callable[[str], None] = lambda name: None) -> Result:
    """Run every check in order, calling running(name) before and report(row)
    after each one."""
    blocking = False
    catalog = None

    running("network")
    try:
        cat.check_network()
        report(Row("network", "ok", "GitHub reachable"))
        net_ok = True
    except OSError as e:
        report(Row("network", "err", "Cannot reach github.com ({})".format(_short(e)),
                   "Check the Ethernet cable or proxy settings, then click Retry."))
        net_ok = False
        blocking = True

    if net_ok or "://" not in list_url:
        running("list")
        try:
            catalog = cat.fetch(list_url)
            report(Row("list", "ok", "{} drivers available".format(len(catalog.packages))))
        except (OSError, cat.CatalogError) as e:
            report(Row("list", "err", "Cannot load driver list ({})".format(_short(e)),
                       "GitHub may be temporarily unavailable. Click Retry in a moment."))
            blocking = True
    else:
        report(Row("list", "skip", "Skipped"))

    running("model")
    device = dev.detect()
    if device.board:
        report(Row("model", "ok", device.model))
    else:
        report(Row("model", "warn", "Not detected",
                   "{} is missing or unreadable. Drivers can still be chosen manually."
                   .format(dev.VERSION_FILE)))

    running("jetpack")
    if device.jetpack:
        report(Row("jetpack", "ok", cat.jetpack_label(device.jetpack)))
    else:
        report(Row("jetpack", "warn", "Not detected",
                   "No JetPack version found in {}.".format(dev.VERSION_FILE)))

    running("soc")
    if device.family:
        report(Row("soc", "ok", "{} (TEGRA_CHIPID {})".format(
            platform_label(catalog, device), device.chipid)))
    elif device.chipid:
        report(Row("soc", "err", "Unsupported SoC (TEGRA_CHIPID {})".format(device.chipid),
                   "This tool supports Jetson Orin and Thor devices only."))
        blocking = True
    else:
        report(Row("soc", "warn", "Not detected",
                   "TEGRA_CHIPID not found in {}.".format(dev.NV_BOOT_CONF)))

    return Result(catalog, device, blocking)


def platform_label(catalog: Optional[cat.Catalog], device: dev.Device) -> str:
    """'AGX Orin' when the board is known from the list, else 'Orin' / 'Thor'."""
    if catalog and device.board:
        p = catalog.platform_of_board(device.board)
        if p:
            return catalog.platform_label(p)
    return dev.FAMILY_LABEL.get(device.family or "", "Unknown")


def _short(e: Exception) -> str:
    reason = getattr(e, "reason", None) or e
    return str(reason)[:60]
