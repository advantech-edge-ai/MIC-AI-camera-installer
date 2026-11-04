"""Terminal menu fallback, used when there is no $DISPLAY (e.g. over SSH)."""
from __future__ import annotations

import sys
import threading

from . import APP_NAME, __version__, catalog as cat, checks, installer, matching

MARK = {"ok": "[ OK ]", "warn": "[WARN]", "err": "[FAIL]", "skip": "[ -- ]"}


def _ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        print()
        return None


def _menu(title, items, extra=()):
    """items: list of labels. extra: (key, label) shortcuts. Returns index, key, or None (back)."""
    print("\n" + title)
    print("-" * len(title))
    for i, label in enumerate(items, 1):
        print("  {:>2}. {}".format(i, label))
    for key, label in extra:
        print("  {:>2}. {}".format(key, label))
    print("   0. Back / Exit")
    while True:
        ans = _ask("Select: ")
        if ans is None or ans == "0":
            return None
        if ans.isdigit() and 1 <= int(ans) <= len(items):
            return int(ans) - 1
        for key, _ in extra:
            if ans.lower() == key:
                return key
        print("  Please enter a number from the list.")


def _yes(prompt):
    return (_ask(prompt + " [y/N]: ") or "").lower() in ("y", "yes")


def run(args) -> int:
    print("{} v{}{}".format(APP_NAME, __version__, "  (dry-run)" if args.dry_run else ""))

    state = installer.load_state()
    if state and state.get("status") in ("installing", "done") and state["rebooted"]:
        print("\nLast installation: " + state["key"])
        _next_steps(state["dest"], state["log"])
        installer.clear_state()
        if not _yes("Install another driver?"):
            return 0

    while True:
        print("\nSystem check")
        result = checks.run(args.list_url, report=lambda r: print(
            "  {} {:<13} {}{}".format(MARK[r.state], checks.ROW_TITLES[r.name], r.value,
                                      "\n         -> " + r.hint if r.hint else "")))
        if not result.blocking:
            break
        if not _yes("A required check failed. Retry?"):
            return 1

    catalog, device = result.catalog, result.device
    matches = matching.classify(catalog, device)
    show_other = not any(m.compatible for m in matches)

    while True:
        vendors = matching.vendors(catalog)
        counts = [len({m.package.camera for m in matches if m.package.vendor == v and m.compatible})
                  for v in vendors]
        toggle = ("o", ("Hide" if show_other else "Show") + " drivers for other models (not recommended)")
        pick = _menu("Select vendor  [{} · {} · JetPack {}]".format(
            device.model or "Unknown model", checks.platform_label(catalog, device),
            cat.jetpack_label(device.jetpack)),
            ["{:<12} {} compatible".format(v, n) for v, n in zip(vendors, counts)], extra=(toggle,))
        if pick is None:
            return 0
        if pick == "o":
            show_other = not show_other
            continue
        vendor = vendors[pick]

        rows = sorted((m for m in matches if m.package.vendor == vendor and (m.compatible or show_other)),
                      key=lambda m: (m.package.sensor.lower(), not m.compatible, m.package.key))
        if not rows:
            print("\nNo compatible driver from {} for this device.".format(vendor))
            continue
        labels = []
        for m in rows:
            p = m.package
            if m.compatible:
                tag = "uses {} package".format(catalog.board_label(m.via_board)) if m.via_board else "compatible"
            else:
                tag = "!! {} / JP {}".format(catalog.board_label(p.board), cat.jetpack_label(p.jetpack))
            labels.append("{:<20} {}".format(p.sensor, tag))
        pick = _menu("Select camera  [{}]".format(vendor), labels)
        if pick is None:
            continue
        m = rows[pick]
        if _confirm(catalog, device, m) and _install(m.package, args):
            return 0


def _confirm(catalog, device, m) -> bool:
    p = m.package
    print("\nConfirm installation")
    print("  Camera  : {} / {}".format(p.vendor, p.sensor))
    print("  For     : {} · JetPack {}".format(catalog.board_label(p.board), cat.jetpack_label(p.jetpack)))
    print("  Package : " + p.asset_name)
    print("  Size    : " + cat.human_size(cat.remote_size(p.url)))
    if not m.compatible:
        print("\n  !! This driver was not built for this device:")
        for x in m.problems:
            print("     - " + x)
        print("     Installing it may leave the camera non-functional and change GPIO settings.")
    print("\n  NOTE: the device will REBOOT automatically when installation finishes.")
    print("        After reboot, run init.sh then cam.sh <N>.")
    return _yes("\nInstall anyway?" if not m.compatible else "\nInstall now?")


def _install(pkg, args) -> bool:
    cancel = threading.Event()
    outcome = {}
    last = {"len": 0}

    def emit(kind, **d):
        if kind == "progress":
            if d["total"]:
                pct = d["done"] * 100 // d["total"]
                bar = "#" * (pct // 4)
                line = "  [{:<25}] {:3d}%  {} / {}  {:.1f} MB/s".format(
                    bar, pct, cat.human_size(d["done"]), cat.human_size(d["total"]), d["speed"] / 1e6)
            else:
                line = "  {}  {:.1f} MB/s".format(cat.human_size(d["done"]), d["speed"] / 1e6)
            sys.stdout.write("\r" + line.ljust(last["len"]))
            sys.stdout.flush()
            last["len"] = len(line)
        elif kind == "step":
            if d["state"] == "run" and d["name"] == "extract" and d["text"]:
                return
            if last["len"]:
                print()
                last["len"] = 0
            label = installer.STEPS.index(d["name"]) + 1, d["name"].capitalize()
            mark = {"run": "[ .. ]"}.get(d["state"], MARK.get(d["state"], ""))
            print("{} {}. {} {}".format(mark, label[0], label[1], d["text"]).rstrip())
        elif kind == "log" and d["line"].startswith(("[", "$")):
            print("       " + d["line"])
        elif kind in ("finished", "failed", "cancelled"):
            outcome.update(d, kind=kind)

    print()
    try:
        installer.run(pkg, emit, cancel, use_pkexec=False, dry_run=args.dry_run)
    except KeyboardInterrupt:
        cancel.set()
        print("\nCancelled.")
        return False

    if outcome.get("kind") == "finished":
        print("\nDriver installed successfully.")
        _next_steps(outcome["dest"], outcome["log"])
        return True
    if outcome.get("kind") == "failed":
        print("\nInstallation failed: " + outcome["message"])
    else:
        print("\nInstallation cancelled.")
    print("Log: " + outcome.get("log", ""))
    return False


def _next_steps(dest, log):
    print("Next steps after reboot:")
    print("  1. cd " + dest)
    print("  2. sudo ./init.sh")
    print("  3. ./cam.sh <N>")
    print("Log: " + log)
