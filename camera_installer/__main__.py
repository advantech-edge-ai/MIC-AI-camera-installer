"""Entry point: GUI when a display is available, terminal menu otherwise."""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__, catalog


def gui_errors():
    errors = [ImportError]
    try:
        import tkinter
        errors.append(tkinter.TclError)
    except ImportError:
        pass
    return tuple(errors)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="advantech-camera-installer",
                                 description="Install Advantech MIC-AI camera drivers.")
    ap.add_argument("--tui", action="store_true", help="use the terminal menu even if a display is available")
    ap.add_argument("--list-url", default=os.environ.get("CF_LIST_URL", catalog.LIST_URL),
                    help="driver list URL or local file (default: GitHub main branch)")
    ap.add_argument("--dry-run", action="store_true",
                    help="download, verify and extract, but do not run the installer as root")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    if not args.tui and os.environ.get("DISPLAY"):
        try:
            from . import gui
            root = gui.create_root()
        except gui_errors() as e:  # python3-tk missing or display unusable
            print("GUI unavailable ({}); falling back to terminal menu.".format(e), file=sys.stderr)
        else:
            return gui.run(args, root)
    from . import tui
    return tui.run(args)


if __name__ == "__main__":
    sys.exit(main())
