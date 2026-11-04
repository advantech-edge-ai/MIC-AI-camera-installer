"""Tkinter wizard: Check -> Select -> Install -> Done (see 畫面草圖.html)."""
from __future__ import annotations

import os
import queue
import subprocess
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

from . import APP_NAME, __version__, catalog as cat, checks, installer, matching

# Advantech colours
PRIMARY = "#004280"
ACCENT = "#298ee0"     # current step, progress bar
LIGHT = "#c0dafb"      # selection, info boxes
OK = "#79BD28"
WARN = "#F39800"
MUTED = "#898989"
ERR = "#d93a3a"
BG = "#f4f7fb"
TEXT = "#1d2733"
LINE = "#dde3ea"
WHITE = "#ffffff"
DISABLED_BG = "#e3e7ec"
DISABLED_FG = "#a3acb6"
WARN_BG = "#fef3e0"
ERR_BG = "#fdf1f1"
OK_TEXT = "#4a7d12"
WARN_TEXT = "#a86900"

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
STEP_NAMES = ("Check", "Select", "Install", "Done")
INSTALL_TITLES = {"download": "Download", "verify": "Verify MD5", "extract": "Extract", "install": "Install"}


def create_root() -> tk.Tk:
    root = tk.Tk(className="advantech-camera-installer")
    root.title(APP_NAME)
    try:
        root.app_icons = [tk.PhotoImage(file=os.path.join(ASSETS, "app_icon_{}.png".format(s)))
                          for s in (128, 64, 48)]
        root.iconphoto(True, *root.app_icons)
    except tk.TclError:
        pass
    families = set(tkfont.families(root))
    family = next((f for f in ("Ubuntu", "Noto Sans", "DejaVu Sans") if f in families), "TkDefaultFont")
    mono = next((f for f in ("Ubuntu Mono", "DejaVu Sans Mono") if f in families), "TkFixedFont")
    root.fonts = {
        "base": (family, 10),
        "bold": (family, 10, "bold"),
        "small": (family, 9),
        "small_bold": (family, 9, "bold"),
        "h2": (family, 12, "bold"),
        "title": (family, 14, "bold"),
        "app": (family, 11),
        "mono": (mono, 9),
    }
    return root


# --------------------------------------------------------------------------
# small widgets
# --------------------------------------------------------------------------
class Button(tk.Label):
    """Flat button in the mockup style (tk.Button ignores colours on some WMs)."""

    def __init__(self, master, text, command, primary=False, **kw):
        super().__init__(master, text=text, padx=18, pady=5, cursor="hand2",
                         font=master._root().fonts["base"], **kw)
        self.command = command
        self.primary = primary
        self.enabled = True
        self.bind("<Button-1>", lambda e: self.enabled and self.command())
        self._paint()

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._paint()

    def _paint(self):
        if not self.enabled:
            self.configure(bg=DISABLED_BG, fg=DISABLED_FG, highlightthickness=1,
                           highlightbackground=DISABLED_BG)
        elif self.primary:
            self.configure(bg=PRIMARY, fg=WHITE, highlightthickness=1, highlightbackground=PRIMARY)
        else:
            self.configure(bg=WHITE, fg=PRIMARY, highlightthickness=1, highlightbackground=PRIMARY)


class StatusIcon(tk.Canvas):
    """22px status circle: ok / err / warn / wait / run (spinner)."""
    SIZE = 22

    def __init__(self, master, bg=WHITE):
        super().__init__(master, width=self.SIZE, height=self.SIZE, bg=bg, highlightthickness=0)
        self._angle = 0
        self._spin = None
        self.set("wait")

    def set(self, state, text=None):
        if self._spin:
            self.after_cancel(self._spin)
            self._spin = None
        self.delete("all")
        s = self.SIZE
        font = self._root().fonts["small_bold"]
        if state == "run":
            self._draw_spinner()
            return
        fill, fg, default = {
            "ok": (OK, WHITE, "✓"),
            "err": (ERR, WHITE, "✕"),
            "warn": (WARN, WHITE, "!"),
            "wait": (LINE, MUTED, "–"),
            "skip": (LINE, MUTED, "–"),
        }[state]
        self.create_oval(1, 1, s - 1, s - 1, fill=fill, outline=fill)
        self.create_text(s / 2, s / 2, text=text or default, fill=fg, font=font)

    def _draw_spinner(self):
        self.delete("all")
        s = self.SIZE
        self.create_oval(3, 3, s - 3, s - 3, outline=LIGHT, width=3)
        self.create_arc(3, 3, s - 3, s - 3, start=self._angle, extent=90, style="arc",
                        outline=ACCENT, width=3)
        self._angle = (self._angle - 30) % 360
        self._spin = self.after(80, self._draw_spinner)


class Stepper(tk.Canvas):
    def __init__(self, master):
        super().__init__(master, height=52, bg=WHITE, highlightthickness=0)
        self.current = 0
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, index):
        self.current = index
        self.draw()

    def draw(self):
        self.delete("all")
        fonts = self._root().fonts
        w, h = self.winfo_width(), 52
        pad, r, gap, bar_margin = 22, 12, 8, 12
        widths = [2 * r + gap + tkfont.Font(font=fonts["bold"]).measure(n) for n in STEP_NAMES]
        bar_len = max(20, (w - 2 * pad - sum(widths) - 2 * bar_margin * 3) / 3)
        x = pad
        cy = h / 2
        for i, name in enumerate(STEP_NAMES):
            if i < self.current:
                fill, outline, num_fg, label_fg, label = PRIMARY, PRIMARY, WHITE, PRIMARY, "✓"
            elif i == self.current:
                fill, outline, num_fg, label_fg, label = ACCENT, ACCENT, WHITE, ACCENT, str(i + 1)
            else:
                fill, outline, num_fg, label_fg, label = WHITE, LINE, MUTED, MUTED, str(i + 1)
            self.create_oval(x, cy - r, x + 2 * r, cy + r, fill=fill, outline=outline, width=2)
            self.create_text(x + r, cy, text=label, fill=num_fg, font=fonts["small_bold"])
            self.create_text(x + 2 * r + gap, cy, text=name, anchor="w", fill=label_fg,
                             font=fonts["bold"] if i == self.current else fonts["base"])
            x += widths[i]
            if i < len(STEP_NAMES) - 1:
                self.create_line(x + bar_margin, cy, x + bar_margin + bar_len, cy, width=2,
                                 fill=PRIMARY if i < self.current else LINE)
                x += bar_len + 2 * bar_margin
        self.create_line(0, h - 1, w, h - 1, fill=LINE)


def card(master):
    return tk.Frame(master, bg=WHITE, highlightthickness=1, highlightbackground=LINE)


# --------------------------------------------------------------------------
# application
# --------------------------------------------------------------------------
class App:
    def __init__(self, root: tk.Tk, args):
        self.root = root
        self.args = args
        self.f = root.fonts
        self.q = queue.Queue()
        self.catalog = None
        self.device = None
        self.matches = []
        self.selected = None          # matching.Match
        self.worker = None
        self.cancel = threading.Event()
        self.install_step = None
        self.done_info = None

        root.configure(bg=BG)
        root.geometry("720x500")
        root.minsize(720, 500)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._style()
        self._chrome()
        self.root.after(50, self._poll)

        state = installer.load_state()
        if state and state.get("status") in ("installing", "done") and (
                state["rebooted"] or state["status"] == "done"):
            self.show_done(state["key"], state["dest"], state["log"], resumed=state["rebooted"])
        else:
            self.show_check()

    # ---- layout ---------------------------------------------------------
    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure("Installer.Treeview", background=WHITE, fieldbackground=WHITE, foreground=TEXT,
                    rowheight=34, borderwidth=0, font=self.f["base"])
        s.map("Installer.Treeview", background=[("selected", LIGHT)], foreground=[("selected", PRIMARY)])
        s.layout("Installer.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        s.configure("Accent.Horizontal.TProgressbar", troughcolor="#e6edf5", background=ACCENT,
                    bordercolor="#e6edf5", lightcolor=ACCENT, darkcolor=ACCENT, thickness=10)
        s.configure("Installer.TCheckbutton", background=BG, foreground=MUTED, font=self.f["small"])
        s.map("Installer.TCheckbutton", background=[("active", BG)])

    def _chrome(self):
        header = tk.Frame(self.root, bg=PRIMARY, padx=22, pady=14)
        header.pack(fill="x")
        try:
            self.logo = tk.PhotoImage(file=os.path.join(ASSETS, "advantech_logo_26.png"))
            tk.Label(header, image=self.logo, bg=PRIMARY, bd=0).pack(side="left")
        except tk.TclError:
            tk.Label(header, text="ADVANTECH", bg=PRIMARY, fg=WHITE, font=self.f["title"]).pack(side="left")
        tk.Frame(header, bg="#5984ac", width=1, height=20).pack(side="left", padx=14)
        tk.Label(header, text=APP_NAME, bg=PRIMARY, fg=WHITE, font=self.f["app"]).pack(side="left")
        tk.Label(header, text="v" + __version__ + (" · dry-run" if self.args.dry_run else ""),
                 bg=PRIMARY, fg="#99b3cc", font=self.f["small"]).pack(side="right")

        self.stepper = Stepper(self.root)
        self.stepper.pack(fill="x")

        self.footer = tk.Frame(self.root, bg=WHITE, padx=22, pady=12)
        self.footer.pack(side="bottom", fill="x")
        tk.Frame(self.root, bg=LINE, height=1).pack(side="bottom", fill="x")
        self.body = tk.Frame(self.root, bg=BG, padx=26, pady=20)
        self.body.pack(fill="both", expand=True)

    def _clear(self):
        for w in self.body.winfo_children() + self.footer.winfo_children():
            w.destroy()

    def _footer(self, left="", left_fg=MUTED, buttons=()):
        """buttons: (text, command, primary) from left to right; returns Button widgets."""
        tk.Label(self.footer, text=left, bg=WHITE, fg=left_fg, font=self.f["small"]).pack(side="left")
        out = []
        for text, cmd, primary in reversed(buttons):
            b = Button(self.footer, text, cmd, primary=primary)
            b.pack(side="right", padx=(10, 0))
            out.append(b)
        return list(reversed(out))

    def _h2(self, text):
        tk.Label(self.body, text=text, bg=BG, fg=TEXT, font=self.f["h2"]).pack(anchor="w", pady=(0, 12))

    # ---- worker plumbing -----------------------------------------------
    def _start(self, target, *a):
        self.worker = threading.Thread(target=target, args=a, daemon=True)
        self.worker.start()

    def _emit(self, kind, **data):
        self.q.put((kind, data))

    def _on_call(self, fn):
        fn()

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                getattr(self, "_on_" + kind)(**data)
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    # ======================================================================
    # 1. System check
    # ======================================================================
    def show_check(self):
        self._clear()
        self.stepper.set(0)
        self._h2("System Check")
        box = card(self.body)
        box.pack(fill="x")
        self.check_rows = {}
        for i, name in enumerate(checks.ROWS):
            row = tk.Frame(box, bg=WHITE, padx=16, pady=10)
            row.pack(fill="x")
            if i:
                tk.Frame(box, bg=LINE, height=1).pack(fill="x", before=row)
            icon = StatusIcon(row)
            icon.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 14))
            k = tk.Label(row, text=checks.ROW_TITLES[name], bg=WHITE, fg=TEXT, font=self.f["bold"],
                         width=14, anchor="w")
            k.grid(row=0, column=1, sticky="w")
            v = tk.Label(row, text="", bg=WHITE, fg=MUTED, font=self.f["base"], anchor="w")
            v.grid(row=0, column=2, sticky="w")
            hint = tk.Label(row, text="", bg=WHITE, fg=ERR, font=self.f["small"], anchor="w",
                            justify="left", wraplength=520)
            self.check_rows[name] = (row, icon, k, v, hint)
        self.btn_retry, self.btn_next = self._footer("Checking ...", buttons=(
            ("Retry", self.show_check, False), ("Next ▶", self.show_select, True)))
        self.check_status = self.footer.winfo_children()[0]
        self.btn_retry.set_enabled(False)
        self.btn_next.set_enabled(False)
        self._start(self._check_worker)

    def _check_worker(self):
        result = checks.run(self.args.list_url,
                            report=lambda row: self._emit("check_row", row=row),
                            running=lambda name: self._emit("check_running", name=name))
        self._emit("check_done", result=result)

    def _on_check_running(self, name):
        self.check_rows[name][1].set("run")
        self.check_rows[name][3].configure(text="Checking ...")

    def _on_check_row(self, row):
        frame, icon, k, v, hint = self.check_rows[row.name]
        icon.set(row.state)
        v.configure(text=row.value)
        bg = ERR_BG if row.state == "err" else WHITE
        for w in (frame, k, v, hint):
            w.configure(bg=bg)
        icon.configure(bg=bg)
        if row.hint:
            hint.configure(text="→ " + row.hint, fg=ERR if row.state == "err" else WARN_TEXT)
            hint.grid(row=1, column=1, columnspan=2, sticky="w", pady=(4, 0))

    def _on_check_done(self, result):
        self.catalog, self.device = result.catalog, result.device
        self.btn_retry.set_enabled(True)
        if result.blocking:
            n = sum(1 for r in self.check_rows.values() if r[0].cget("bg") == ERR_BG)
            self.check_status.configure(text="{} check{} failed".format(n, "s" if n > 1 else ""), fg=ERR)
            return
        warned = sum(1 for r in self.check_rows.values() if r[4].cget("text"))
        self.check_status.configure(
            text="All checks passed" if not warned else "{} warning{}".format(warned, "s" if warned > 1 else ""),
            fg=MUTED if not warned else WARN_TEXT)
        self.matches = matching.classify(self.catalog, self.device)
        self.btn_next.set_enabled(True)

    # ======================================================================
    # 2. Select driver
    # ======================================================================
    def show_select(self):
        self._clear()
        self.stepper.set(1)
        self.selected = None
        dev, catalog = self.device, self.catalog

        banner = tk.Frame(self.body, bg=LIGHT, padx=16, pady=10)
        banner.pack(fill="x", pady=(0, 14))
        for title, value in (("Device", dev.model or "Unknown"),
                             ("Platform", checks.platform_label(catalog, dev)),
                             ("JetPack", cat.jetpack_label(dev.jetpack))):
            col = tk.Frame(banner, bg=LIGHT)
            col.pack(side="left", padx=(0, 26))
            tk.Label(col, text=title, bg=LIGHT, fg=TEXT, font=self.f["small"]).pack(anchor="w")
            tk.Label(col, text=value, bg=LIGHT, fg=PRIMARY, font=self.f["h2"]).pack(anchor="w")

        cols = tk.Frame(self.body, bg=BG)
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(1, weight=1)
        cols.rowconfigure(1, weight=1)
        for c, title in enumerate(("VENDOR", "CAMERA")):
            tk.Label(cols, text=title, bg=BG, fg=MUTED, font=self.f["small_bold"]).grid(
                row=0, column=c, sticky="w", pady=(0, 6), padx=(0, 14) if c == 0 else 0)

        self.vendor_tree = self._tree(cols, "count", 50)
        self.vendor_tree.master.grid(row=1, column=0, sticky="nsew", padx=(0, 14))
        self.vendor_tree.column("#0", width=120)
        self.camera_tree = self._tree(cols, "tag", 230)
        self.camera_tree.master.grid(row=1, column=1, sticky="nsew")
        self.camera_tree.tag_configure("other", foreground=DISABLED_FG)
        self.vendor_tree.bind("<<TreeviewSelect>>", lambda e: self._fill_cameras())
        self.camera_tree.bind("<<TreeviewSelect>>", lambda e: self._on_camera())
        self.camera_tree.bind("<Double-1>", lambda e: self.selected and self.confirm())

        bottom = tk.Frame(self.body, bg=BG)
        bottom.pack(fill="x", pady=(10, 0))
        self.show_other = tk.BooleanVar(value=not any(m.compatible for m in self.matches))
        ttk.Checkbutton(bottom, text="Show drivers for other models (not recommended)",
                        variable=self.show_other, style="Installer.TCheckbutton",
                        command=self._fill_vendors).pack(side="left")
        self.select_note = tk.Label(bottom, text="", bg=BG, fg=WARN_TEXT, font=self.f["small"])
        self.select_note.pack(side="right")

        self.btn_back, self.btn_next = self._footer(buttons=(
            ("◀ Back", self.show_check, False), ("Next ▶", self.confirm, True)))
        self.btn_next.set_enabled(False)
        self._fill_vendors()

    def _tree(self, master, column, width):
        frame = tk.Frame(master, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        tree = ttk.Treeview(frame, columns=(column,), show="tree", selectmode="browse",
                            style="Installer.Treeview", height=5)
        tree.column(column, width=width, anchor="e", stretch=False)
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)

        def autohide(first, last):
            sb.set(first, last)
            if float(first) <= 0 and float(last) >= 1:
                sb.grid_remove()
            else:
                sb.grid()
        tree.configure(yscrollcommand=autohide)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        return tree

    def _visible(self, vendor):
        return [m for m in self.matches if m.package.vendor == vendor
                and (m.compatible or self.show_other.get())]

    def _fill_vendors(self):
        prev = self.vendor_tree.selection()
        self.vendor_tree.delete(*self.vendor_tree.get_children())
        first = None
        for v in matching.vendors(self.catalog):
            n = len({m.package.camera for m in self.matches if m.package.vendor == v and m.compatible})
            self.vendor_tree.insert("", "end", iid=v, text="  " + v, values=(str(n) + "  ",))
            if first is None and (n or self.show_other.get()):
                first = v
        target = prev[0] if prev and self.vendor_tree.exists(prev[0]) else first
        if target:
            self.vendor_tree.selection_set(target)
            self.vendor_tree.see(target)
        self._fill_cameras()

    def _fill_cameras(self):
        prev = self.camera_tree.selection()
        self.camera_tree.delete(*self.camera_tree.get_children())
        sel = self.vendor_tree.selection()
        self.match_by_iid = {}
        if sel:
            rows = sorted(self._visible(sel[0]),
                          key=lambda m: (m.package.sensor.lower(), not m.compatible, m.package.key))
            for m in rows:
                p = m.package
                if m.compatible:
                    tag = "✓ uses {} package".format(self.catalog.board_label(m.via_board)) \
                        if m.via_board else "✓ Compatible"
                else:
                    tag = "⚠ {} · JP {}".format(self.catalog.board_label(p.board), cat.jetpack_label(p.jetpack))
                self.camera_tree.insert("", "end", iid=p.key, text="  " + p.sensor, values=(tag + "  ",),
                                        tags=() if m.compatible else ("other",))
                self.match_by_iid[p.key] = m
            if not rows:
                self.camera_tree.insert("", "end", iid="__none__", text="  No compatible driver for this device",
                                        values=("",), tags=("other",))
        if prev and self.camera_tree.exists(prev[0]):
            self.camera_tree.selection_set(prev[0])
        self._on_camera()

    def _on_camera(self):
        sel = self.camera_tree.selection()
        self.selected = self.match_by_iid.get(sel[0]) if sel else None
        self.btn_next.set_enabled(self.selected is not None)
        if self.selected and not self.selected.compatible:
            self.select_note.configure(text="⚠ " + self.selected.problems[0])
        else:
            self.select_note.configure(text="")

    # ---- confirm dialog -------------------------------------------------
    def confirm(self):
        m = self.selected
        if not m:
            return
        p = m.package
        dlg = tk.Toplevel(self.root, bg=WHITE)
        dlg.title("Confirm Installation")
        dlg.transient(self.root)
        dlg.resizable(False, False)

        head = "Confirm Installation" if m.compatible else "Driver does not match this device"
        tk.Label(dlg, text=head, bg=PRIMARY if m.compatible else ERR, fg=WHITE, font=self.f["bold"],
                 anchor="w", padx=18, pady=10).pack(fill="x")
        body = tk.Frame(dlg, bg=WHITE, padx=18, pady=14)
        body.pack(fill="both")

        kv = tk.Frame(body, bg=WHITE)
        kv.pack(fill="x", pady=(0, 12))
        size_var = tk.StringVar(value="…")
        target = "{} · JetPack {}".format(self.catalog.board_label(p.board), cat.jetpack_label(p.jetpack))
        if m.via_board:
            target += "  (shared package for {})".format(self.catalog.board_label(self.device.board))
        for r, (k, v) in enumerate((("Camera", "{} / {}".format(p.vendor, p.sensor)), ("For", target),
                                    ("Package", p.asset_name), ("Size", size_var))):
            tk.Label(kv, text=k, bg=WHITE, fg=MUTED, font=self.f["small"]).grid(row=r, column=0, sticky="nw",
                                                                             padx=(0, 10), pady=2)
            opts = {"textvariable": v} if isinstance(v, tk.StringVar) else {"text": v}
            tk.Label(kv, bg=WHITE, fg=TEXT, font=self.f["small"], wraplength=360, justify="left",
                     anchor="w", **opts).grid(row=r, column=1, sticky="w", pady=2)

        if not m.compatible:
            self._alert(body, ERR, ERR_BG, "This driver was not built for this device:",
                        "\n".join("• " + x for x in m.problems) +
                        "\nInstalling it may leave the camera non-functional and change GPIO settings.")
        self._alert(body, WARN, WARN_BG, "The device will reboot automatically",
                    "when installation finishes. Save your work first.\n"
                    "After reboot, run init.sh then cam.sh <N>.")

        foot = tk.Frame(dlg, bg=WHITE, padx=18, pady=12, highlightthickness=1, highlightbackground=LINE)
        foot.pack(fill="x")
        Button(foot, "Install anyway" if not m.compatible else "Install",
               lambda: (dlg.destroy(), self.start_install(p)), primary=True).pack(side="right", padx=(10, 0))
        Button(foot, "Cancel", dlg.destroy).pack(side="right")
        dlg.bind("<Escape>", lambda e: dlg.destroy())

        dlg.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dlg.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dlg.winfo_reqheight()) // 2
        dlg.geometry("+{}+{}".format(max(x, 0), max(y, 0)))
        dlg.grab_set()

        def fetch_size():
            text = cat.human_size(cat.remote_size(p.url))
            self._emit("call", fn=lambda: size_var.set(text) if dlg.winfo_exists() else None)
        threading.Thread(target=fetch_size, daemon=True).start()

    def _alert(self, master, edge, bg, title, text):
        box = tk.Frame(master, bg=bg)
        box.pack(fill="x", pady=(0, 8))
        tk.Frame(box, bg=edge, width=4).pack(side="left", fill="y")
        inner = tk.Frame(box, bg=bg, padx=12, pady=8)
        inner.pack(side="left", fill="both", expand=True)
        tk.Label(inner, text=title, bg=bg, fg=TEXT, font=self.f["small_bold"], anchor="w",
                 justify="left").pack(anchor="w")
        tk.Label(inner, text=text, bg=bg, fg=TEXT, font=self.f["small"], anchor="w", justify="left",
                 wraplength=380).pack(anchor="w")

    # ======================================================================
    # 3. Download & install
    # ======================================================================
    def start_install(self, pkg):
        self._clear()
        self.stepper.set(2)
        self.current_pkg = pkg
        self._h2("Installing {} / {}".format(pkg.vendor, pkg.sensor))
        box = card(self.body)
        box.pack(fill="x")
        self.prog_rows = {}
        for i, name in enumerate(installer.STEPS):
            if i:
                tk.Frame(box, bg=LINE, height=1).pack(fill="x")
            row = tk.Frame(box, bg=WHITE, padx=16, pady=10)
            row.pack(fill="x")
            icon = StatusIcon(row)
            icon.set("wait", str(i + 1))
            icon.pack(side="left", anchor="n", padx=(0, 14))
            main = tk.Frame(row, bg=WHITE)
            main.pack(side="left", fill="x", expand=True)
            head = tk.Frame(main, bg=WHITE)
            head.pack(fill="x")
            tk.Label(head, text=INSTALL_TITLES[name], bg=WHITE, fg=TEXT, font=self.f["bold"]).pack(side="left")
            v = tk.Label(head, text="", bg=WHITE, fg=MUTED, font=self.f["small"])
            v.pack(side="right")
            bar = None
            if name == "download":
                bar = ttk.Progressbar(main, style="Accent.Horizontal.TProgressbar", maximum=1000)
                bar.pack(fill="x", pady=(8, 0))
            self.prog_rows[name] = (icon, v, bar)

        self.details_link = tk.Label(self.body, text="▸ Show details", bg=BG, fg=ACCENT,
                                     font=self.f["small"], cursor="hand2")
        self.details_link.pack(anchor="w", pady=(10, 0))
        self.details_link.bind("<Button-1>", lambda e: self._toggle_details())
        self.log_frame = tk.Frame(self.body, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        self.log_text = tk.Text(self.log_frame, height=8, bg="#1d2733", fg="#d6dde6", font=self.f["mono"],
                                relief="flat", padx=8, pady=6, state="disabled", wrap="none")
        sb = ttk.Scrollbar(self.log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

        (self.btn_cancel,) = self._footer(buttons=(("Cancel", self._cancel_install, False),))
        self.cancel = threading.Event()
        self._start(installer.run, pkg, self._emit, self.cancel, True, self.args.dry_run)

    def _toggle_details(self):
        if self.log_frame.winfo_ismapped():
            self.log_frame.pack_forget()
            self.details_link.configure(text="▸ Show details")
            self.root.geometry("720x500")
        else:
            self.log_frame.pack(fill="both", expand=True, pady=(6, 0))
            self.details_link.configure(text="▾ Hide details")
            self.root.geometry("720x680")
            self.log_text.see("end")

    def _cancel_install(self):
        self.cancel.set()
        self.btn_cancel.set_enabled(False)

    def _on_step(self, name, state, text):
        icon, v, bar = self.prog_rows[name]
        icon.set(state)
        v.configure(text=text, fg=WARN_TEXT if state == "warn" else ERR if state == "err" else MUTED)
        if name == "install" and state == "run":
            # the vendor installer cannot be interrupted safely
            if self.btn_cancel.winfo_exists():
                self.btn_cancel.pack_forget()
        if bar and state == "ok":
            bar["value"] = 1000

    def _on_progress(self, done, total, speed):
        icon, v, bar = self.prog_rows["download"]
        if total:
            bar["value"] = done * 1000 / total
            left = (total - done) / speed if speed > 0 else 0
            v.configure(text="{} / {} · {:.1f} MB/s · {} left".format(
                cat.human_size(done), cat.human_size(total), speed / 1e6, _duration(left)))
        else:
            if str(bar.cget("mode")) != "indeterminate":
                bar.configure(mode="indeterminate")
                bar.start(15)
            v.configure(text="{} · {:.1f} MB/s".format(cat.human_size(done), speed / 1e6))

    def _on_log(self, line):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _on_finished(self, dest, log):
        self.show_done(self.current_pkg.key, dest, log, resumed=False)

    def _on_failed(self, message, log):
        for w in self.footer.winfo_children():
            w.destroy()
        self._footer(left="✕ " + message, left_fg=ERR, buttons=(
            ("◀ Back", self.show_select, False),
            ("Retry", lambda: self.start_install(self.current_pkg), True)))
        if not self.log_frame.winfo_ismapped():
            self._toggle_details()

    def _on_cancelled(self, log):
        for w in self.footer.winfo_children():
            w.destroy()
        self._footer(left="Installation cancelled", buttons=(("◀ Back", self.show_select, False),))

    # ======================================================================
    # 4. Done
    # ======================================================================
    def show_done(self, key, dest, log, resumed):
        self._clear()
        self.root.geometry("720x500")
        self.stepper.set(3)
        wrap = tk.Frame(self.body, bg=BG)
        wrap.pack(fill="both", expand=True)
        c = tk.Canvas(wrap, width=56, height=56, bg=BG, highlightthickness=0)
        c.create_oval(1, 1, 55, 55, fill=OK, outline=OK)
        c.create_text(28, 28, text="✓", fill=WHITE, font=(self.f["title"][0], 20, "bold"))
        c.pack(pady=(0, 8))
        title = "Driver installed successfully"
        tk.Label(wrap, text=title, bg=BG, fg=TEXT, font=self.f["title"]).pack()
        sub = key.replace("/", " · ")
        if resumed:
            sub += "   (the device has rebooted)"
        tk.Label(wrap, text=sub, bg=BG, fg=MUTED, font=self.f["small"]).pack(pady=(2, 12))

        steps = ["cd " + dest, "sudo ./init.sh", "./cam.sh <N>"]
        nxt = card(wrap)
        nxt.configure(padx=16, pady=10)
        nxt.pack(fill="x")
        tk.Label(nxt, text="Next steps" + ("" if resumed else " after reboot"), bg=WHITE, fg=TEXT,
                 font=self.f["small_bold"]).pack(anchor="w")
        for i, s in enumerate(steps, 1):
            row = tk.Frame(nxt, bg=WHITE)
            row.pack(anchor="w", pady=2)
            tk.Label(row, text="{}.".format(i), bg=WHITE, fg=TEXT, font=self.f["small"]).pack(side="left")
            tk.Label(row, text=s, bg="#eef3f9", fg=PRIMARY, font=self.f["mono"], padx=6).pack(side="left", padx=6)
        tk.Label(wrap, text="Log: " + _tilde(log), bg=BG, fg=MUTED, font=self.f["small"]).pack(anchor="w", pady=(10, 0))

        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(steps))
            self.done_note.configure(text="Copied to clipboard")
        buttons = [("Copy steps", copy, False)]
        if resumed:
            buttons.append(("Install another driver", self._start_over, True))
        else:
            buttons += [("Install another", self._start_over, False), ("Reboot now", self._reboot, True)]
        self._footer(buttons=buttons)
        self.done_note = self.footer.winfo_children()[0]

    def _start_over(self):
        installer.clear_state()
        self.show_check()

    def _reboot(self):
        if not messagebox.askyesno("Reboot", "Reboot the device now?", default="no", parent=self.root):
            return
        if self.args.dry_run:
            messagebox.showinfo("Reboot", "Dry-run: not rebooting.", parent=self.root)
            return
        for cmd in (["systemctl", "reboot"], ["pkexec", "systemctl", "reboot"]):
            if subprocess.call(cmd) == 0:
                return
        messagebox.showerror("Reboot", "Could not reboot. Please reboot manually.", parent=self.root)

    # ---- close ----------------------------------------------------------
    def on_close(self):
        if self.worker and self.worker.is_alive() and self.stepper.current == 2:
            if not messagebox.askyesno(
                    "Installation in progress",
                    "A driver is being installed. Quitting now may leave it half-installed.\n\nQuit anyway?",
                    default="no", icon="warning", parent=self.root):
                return
            self.cancel.set()
        self.root.destroy()


def _duration(seconds):
    seconds = int(seconds)
    return "{} s".format(seconds) if seconds < 60 else "{} min {} s".format(seconds // 60, seconds % 60)


def _tilde(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path


def run(args, root=None) -> int:
    root = root or create_root()
    App(root, args)
    root.mainloop()
    return 0
