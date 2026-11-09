"""Download -> verify MD5 -> extract -> install pipeline (shared by GUI and TUI).

Everything up to "install" runs as the normal user in ~/.cache. Only the last
step (copy into /opt and run the vendor installer) is elevated, through
helpers/install_driver.sh via pkexec (GUI) or sudo (terminal).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import threading
import time
import zipfile
from datetime import datetime
from typing import Callable, Optional

from .catalog import Package, human_size, open_url

APP_ID = "advantech-camera-installer"
VENDORS_DIR = "/opt/advantech/camera_framework/vendors"
HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "helpers", "install_driver.sh")

CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), APP_ID)
DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), APP_ID)
STATE_FILE = os.path.join(DATA_DIR, "last_install.json")

STEPS = ("download", "verify", "extract", "install")
CHUNK = 256 * 1024


class Cancelled(Exception):
    pass


class InstallError(Exception):
    pass


# --------------------------------------------------------------------------
# paths / state
# --------------------------------------------------------------------------
def dest_dir(pkg: Package) -> str:
    """Same layout as the vendors/ tree of install_camera.sh: 'thor' is stored as 'agx_thor',
    realsense has no <sensor> level."""
    platform = "agx_thor" if pkg.platform == "thor" else pkg.platform
    parts = [VENDORS_DIR, pkg.vendor]
    if pkg.vendor != "realsense":
        parts.append(pkg.sensor)
    parts += [platform, pkg.board, pkg.jetpack]
    return os.path.join(*parts)


def new_log_path() -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, "install_{}.log".format(datetime.now().strftime("%Y%m%d_%H%M%S")))


def boot_id() -> str:
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_state(**data) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    data["boot_id"] = boot_id()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_state() -> Optional[dict]:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None
    state["rebooted"] = state.get("boot_id") != boot_id()
    return state


def clear_state() -> None:
    try:
        os.remove(STATE_FILE)
    except OSError:
        pass


# --------------------------------------------------------------------------
# individual steps
# --------------------------------------------------------------------------
def download(url: str, path: str, progress: Callable[[int, Optional[int], float], None],
             cancel: threading.Event) -> None:
    tmp = path + ".part"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open_url(url, timeout=60) as resp, open(tmp, "wb") as out:
            total = resp.headers.get("Content-Length")
            total = int(total) if total else None
            done, t0, last = 0, time.monotonic(), 0.0
            while True:
                if cancel.is_set():
                    raise Cancelled()
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                now = time.monotonic()
                if now - last >= 0.2:
                    progress(done, total, done / max(now - t0, 1e-6))
                    last = now
            progress(done, total, done / max(time.monotonic() - t0, 1e-6))
        if total is not None and done != total:
            raise InstallError("Download incomplete ({} of {} bytes).".format(done, total))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def fetch_md5(url: str) -> Optional[str]:
    """Expected MD5 from <url>.md5sum, or None when not published."""
    try:
        with open_url(url + ".md5sum", timeout=15) as resp:
            text = resp.read(4096).decode("ascii", "replace").split()
    except OSError:
        return None
    return text[0].lower() if text and len(text[0]) == 32 else None


def md5_file(path: str, cancel: threading.Event) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            if cancel.is_set():
                raise Cancelled()
            h.update(chunk)
    return h.hexdigest()


def _tar_mode(name: str) -> Optional[str]:
    for ext, mode in ((".tbz2", "r:bz2"), (".tar.bz2", "r:bz2"), (".tbz", "r:bz2"),
                      (".tar.gz", "r:gz"), (".tgz", "r:gz"),
                      (".tar.xz", "r:xz"), (".txz", "r:xz")):
        if name.endswith(ext):
            return mode
    return None


def extract(archive: str, stage: str, progress: Callable[[int, int], None],
            cancel: threading.Event) -> None:
    name = os.path.basename(archive).lower()
    mode = _tar_mode(name)
    if mode:
        with tarfile.open(archive, mode) as tf:
            members = tf.getmembers()
            for i, m in enumerate(members, 1):
                if cancel.is_set():
                    raise Cancelled()
                # 'tar' filter blocks absolute / ../ paths but keeps symlinks,
                # which bundled kernel headers need. Older Pythons lack it.
                if hasattr(tarfile, "tar_filter"):
                    tf.extract(m, stage, filter="tar")
                else:
                    _check_inside(stage, m.name)
                    tf.extract(m, stage)
                progress(i, len(members))
    elif name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            for i, info in enumerate(infos, 1):
                if cancel.is_set():
                    raise Cancelled()
                _check_inside(stage, info.filename)
                target = zf.extract(info, stage)
                perm = (info.external_attr >> 16) & 0o777
                if perm and not info.is_dir():
                    os.chmod(target, perm)
                progress(i, len(infos))
    else:
        raise InstallError("Unsupported archive type: " + os.path.basename(archive))


def _check_inside(root: str, member: str) -> None:
    target = os.path.realpath(os.path.join(root, member))
    if not target.startswith(os.path.realpath(root) + os.sep):
        raise InstallError("Archive contains an unsafe path: " + member)


def find_entry(stage: str, max_depth: int = 5) -> Optional[str]:
    """Directory holding the shallowest install.sh, else install_binaries.sh,
    else *.deb (online_mode.sh rules: kernel headers bundled in some packages
    carry another install.sh deeper down)."""
    def shallowest(match):
        best = None
        base = stage.rstrip(os.sep).count(os.sep)
        for root, dirs, files in os.walk(stage):
            depth = root.count(os.sep) - base + 1
            if depth > max_depth:
                dirs[:] = []
                continue
            for f in files:
                if match(f) and (best is None or depth < best[0]):
                    best = (depth, root)
        return best[1] if best else None

    return (shallowest(lambda f: f == "install.sh")
            or shallowest(lambda f: f == "install_binaries.sh")
            or shallowest(lambda f: f.endswith(".deb")))


def privileged_command(pkg_dir: str, dest: str, use_pkexec: bool):
    cmd = ["/bin/bash", HELPER, pkg_dir, dest]
    if os.geteuid() == 0:
        return cmd
    return (["pkexec"] if use_pkexec else ["sudo"]) + cmd


# --------------------------------------------------------------------------
# pipeline
# --------------------------------------------------------------------------
def run(pkg: Package, emit: Callable, cancel: threading.Event,
        use_pkexec: bool = True, dry_run: bool = False) -> None:
    """Run all four steps, reporting through emit(event, **data):

      step      name, state (run|ok|warn|err), text
      progress  done, total, speed               (download)
      log       line
      finished  dest, log
      failed    message, log
      cancelled log
    """
    log_path = new_log_path()
    logf = open(log_path, "a", encoding="utf-8")

    def log(line):
        logf.write(line.rstrip("\n") + "\n")
        logf.flush()
        emit("log", line=line.rstrip("\n"))

    dest = dest_dir(pkg)
    archive = os.path.join(CACHE_DIR, "download", pkg.asset_name)
    stage = os.path.join(CACHE_DIR, "stage")
    step = None
    try:
        log("Driver   : " + pkg.key)
        log("Package  : " + pkg.url)
        log("Install  : " + dest)

        step = "download"
        emit("step", name=step, state="run", text="")
        log("Downloading ...")
        download(pkg.url, archive, lambda d, t, s: emit("progress", done=d, total=t, speed=s), cancel)
        emit("step", name=step, state="ok", text=human_size(os.path.getsize(archive)))

        step = "verify"
        emit("step", name=step, state="run", text="")
        want = fetch_md5(pkg.url)
        if want:
            got = md5_file(archive, cancel)
            if got != want:
                os.remove(archive)
                raise InstallError("MD5 mismatch: expected {}, got {}. The download is "
                                   "corrupted; please retry.".format(want, got))
            log("MD5 verified: " + got)
            emit("step", name=step, state="ok", text="MD5 OK")
        else:
            log("No .md5sum published for this package; integrity not verified.")
            emit("step", name=step, state="warn", text="Not verified (no .md5sum published)")

        step = "extract"
        emit("step", name=step, state="run", text="")
        shutil.rmtree(stage, ignore_errors=True)
        os.makedirs(stage)
        extract(archive, stage, lambda i, n: emit("step", name="extract", state="run",
                                                  text="{} / {} files".format(i, n)), cancel)
        pkg_dir = find_entry(stage)
        if not pkg_dir:
            raise InstallError("No install.sh / install_binaries.sh / .deb found in the package.")
        log("Package dir: " + os.path.relpath(pkg_dir, stage))
        emit("step", name=step, state="ok", text="")

        if cancel.is_set():
            raise Cancelled()

        step = "install"
        emit("step", name=step, state="run", text="Waiting for authorization ..."
             if use_pkexec and os.geteuid() != 0 and not dry_run else "")
        save_state(key=pkg.key, dest=dest, log=log_path, status="installing")
        cmd = privileged_command(pkg_dir, dest, use_pkexec)
        if dry_run:
            log("[dry-run] would run: " + " ".join(cmd))
            for name in sorted(os.listdir(pkg_dir))[:20]:
                log("[dry-run]   " + name)
            rc = 0
        else:
            log("$ " + " ".join(cmd))
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, universal_newlines=True,
                                    errors="replace", bufsize=1)
            for line in proc.stdout:
                log(line)
            rc = proc.wait()
        if rc != 0:
            clear_state()
            if use_pkexec and rc in (126, 127):
                raise InstallError("Administrator authorization was cancelled or denied.")
            raise InstallError("Installer exited with code {}. See the log for details.".format(rc))
        save_state(key=pkg.key, dest=dest, log=log_path, status="done")
        emit("step", name=step, state="ok", text="")
        shutil.rmtree(stage, ignore_errors=True)
        emit("finished", dest=dest, log=log_path)
    except Cancelled:
        log("Cancelled by user.")
        if step:
            emit("step", name=step, state="err", text="Cancelled")
        emit("cancelled", log=log_path)
    except (InstallError, OSError, tarfile.TarError, zipfile.BadZipFile) as e:
        log("ERROR: {}".format(e))
        if step:
            emit("step", name=step, state="err", text="Failed")
        emit("failed", message=str(e), log=log_path)
    finally:
        logf.close()
