#!/usr/bin/env python3
"""
OpenBlox Installer & Updater
Clones/updates OpenBlox from GitHub while preserving config, chats, and assets.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.request import urlopen
import zipfile


REPO_URL = "https://github.com/Artemcik5/OpenBlox.git"
ZIP_URL = "https://github.com/Artemcik5/OpenBlox/archive/refs/heads/main.zip"
KEEP_FILES = {"config.json", "chats", os.path.join("frontend", "assets")}
VERSION_URL = "https://raw.githubusercontent.com/Artemcik5/OpenBlox/main/version"


def _to_abs(base: str, *parts: str) -> str:
    return os.path.normpath(os.path.join(base, *parts))


def get_remote_version() -> str:
    try:
        import urllib.request
        resp = urllib.request.urlopen(VERSION_URL, timeout=5)
        return resp.read().decode('utf-8').strip()
    except Exception:
        return "?"


def get_local_version(install_dir: str) -> str:
    vp = _to_abs(install_dir, "version")
    if os.path.isfile(vp):
        with open(vp, "r") as f:
            return f.read().strip()
    return "—"


def has_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def run_git(cmd: list[str], cwd: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
        return r.returncode == 0, r.stdout.strip() or r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "Timed out"
    except FileNotFoundError:
        return False, "Git not found"
    except Exception as e:
        return False, str(e)


def install_from_zip(install_dir: str, log_fn):
    log_fn("Downloading repository...")
    tmp = tempfile.gettempdir()
    zip_path = os.path.join(tmp, "openblox.zip")
    extract_to = os.path.join(tmp, "openblox_extract")

    try:
        resp = urlopen(ZIP_URL, timeout=30)
        with open(zip_path, "wb") as f:
            f.write(resp.read())
    except Exception as e:
        return False, f"Download failed: {e}"

    if os.path.isdir(extract_to):
        shutil.rmtree(extract_to)
    os.makedirs(extract_to, exist_ok=True)

    log_fn("Extracting...")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_to)
    except Exception as e:
        return False, f"Extract failed: {e}"

    # The zip contains a single top-level folder like "OpenBlox-main"
    items = os.listdir(extract_to)
    source = os.path.join(extract_to, items[0]) if items else extract_to

    return _copy_new_files(source, install_dir, log_fn)


def _copy_new_files(source: str, dest: str, log_fn):
    """Copy files from source to dest, preserving KEEP_FILES in dest."""
    keep_set = set()
    for k in KEEP_FILES:
        p = _to_abs(dest, k)
        if os.path.exists(p):
            keep_set.add(p)

    log_fn("Copying files...")
    count = 0
    for root, dirs, files in os.walk(source):
        rel = os.path.relpath(root, source)
        if rel == ".":
            rel = ""
        for f in files:
            src_file = os.path.join(root, f)
            dst_file = _to_abs(dest, rel, f)
            # Skip if this file is in a keep path
            if any(dst_file.startswith(kp) or dst_file.startswith(kp + os.sep) for kp in keep_set):
                continue
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            try:
                shutil.copy2(src_file, dst_file)
                count += 1
            except Exception:
                pass

    os.makedirs(dest, exist_ok=True)
    # Ensure version file is copied
    return True, f"{count} files updated."


class InstallerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("OpenBlox Installer")
        root.geometry("520x360")
        root.minsize(480, 320)
        root.configure(bg="#0f1622")
        self._style()

        self.install_dir = tk.StringVar()
        self.status = tk.StringVar(value="Ready")

        self._build_ui()
        self._detect_existing()

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background="#0f1622", foreground="#e2e8f0",
                        troughcolor="#0d1117", selectbackground="#1f6feb",
                        font=("Segoe UI", 10), borderwidth=0)
        style.configure("TFrame", background="#0f1622")
        style.configure("TLabel", background="#0f1622", foreground="#e2e8f0")
        style.configure("TButton", background="#1f6feb", foreground="#ffffff",
                        borderwidth=0, padding=(12, 5))
        style.map("TButton", background=[("active", "#58a6ff")])
        style.configure("TEntry", fieldbackground="#0d1117", foreground="#e2e8f0",
                        bordercolor="#30363d", borderwidth=1, padding=4)
        style.configure("Horizontal.TProgressbar", background="#58a6ff",
                        troughcolor="#0d1117")

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=15)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="OpenBlox Installer",
                 font=("Segoe UI", 15, "bold"), foreground="#58a6ff").pack(anchor=tk.W)

        ttk.Label(main, text="Install or update OpenBlox from GitHub",
                 font=("Segoe UI", 9), foreground="#8b949e").pack(anchor=tk.W, pady=(0, 12))

        # Path selection
        pf = ttk.Frame(main)
        pf.pack(fill=tk.X, pady=4)
        ttk.Label(pf, text="Install path:").pack(anchor=tk.W)
        row = ttk.Frame(pf)
        row.pack(fill=tk.X, pady=3)
        self.path_entry = ttk.Entry(row, textvariable=self.install_dir)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Browse", command=self._browse).pack(side=tk.RIGHT, padx=(6, 0))

        # Info
        self.info_frame = ttk.LabelFrame(main, text="Status", padding=8)
        self.info_frame.pack(fill=tk.X, pady=10)

        self.local_label = ttk.Label(self.info_frame, text="Local: —", font=("Segoe UI", 9))
        self.local_label.pack(anchor=tk.W)
        self.remote_label = ttk.Label(self.info_frame, text="Remote: —", font=("Segoe UI", 9))
        self.remote_label.pack(anchor=tk.W)
        self.action_label = ttk.Label(self.info_frame, text="", font=("Segoe UI", 9, "bold"))
        self.action_label.pack(anchor=tk.W, pady=(4, 0))

        # Progress
        self.progress = ttk.Progressbar(main, mode="indeterminate", length=400)
        self.progress.pack(fill=tk.X, pady=(6, 0))

        self.log_text = tk.Text(main, height=4, wrap=tk.WORD, bg="#0d1117", fg="#8b949e",
                                font=("Consolas", 9), borderwidth=0, highlightthickness=1,
                                highlightbackground="#30363d", state=tk.DISABLED)
        self.log_text.pack(fill=tk.X, pady=(6, 0))

        # Buttons
        btn_row = ttk.Frame(main)
        btn_row.pack(fill=tk.X, pady=(10, 0))
        self.install_btn = ttk.Button(btn_row, text="Install / Update", command=self._start_install)
        self.install_btn.pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="Refresh", command=self._detect_existing).pack(side=tk.RIGHT, padx=(6, 0))

        self._log("Ready. Select a folder and click Install / Update.")

    def _log(self, msg: str):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def _browse(self):
        d = filedialog.askdirectory(title="Select install folder")
        if d:
            self.install_dir.set(d)
            self._detect_existing()

    def _detect_existing(self):
        path = self.install_dir.get()
        if not path or not os.path.isdir(path):
            self.local_label.config(text="Local: —")
            self.remote_label.config(text="Remote: —")
            self.action_label.config(text="")
            return
        local = get_local_version(path)
        remote = get_remote_version()
        self.local_label.config(text=f"Local: v{local}" if local != "—" else "Local: (not installed)")
        self.remote_label.config(text=f"Remote: v{remote}")
        if local == "—":
            self.action_label.config(text="New installation", foreground="#58a6ff")
        elif local != remote and remote != "?":
            self.action_label.config(text=f"Update available: v{local} → v{remote}", foreground="#facc15")
        else:
            self.action_label.config(text="Up to date", foreground="#3fb950")

    def _start_install(self):
        path = self.install_dir.get().strip()
        if not path:
            messagebox.showerror("Error", "Select an install path first.")
            return
        if not os.path.isdir(path):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Error", f"Cannot create folder:\n{e}")
                return

        self.install_btn.config(state=tk.DISABLED)
        self.progress.start()
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

        threading.Thread(target=self._install_thread, args=(path,), daemon=True).start()

    def _install_thread(self, path: str):
        ok = False
        msg = ""
        try:
            if has_git():
                self._log("Git found. Using git clone/pull.")
                ok, msg = self._install_git(path)
            else:
                self._log("Git not found. Downloading ZIP...")
                ok, msg = install_from_zip(path, self._log)
        except Exception as e:
            ok, msg = False, str(e)

        self.root.after(0, self._install_done, ok, msg)

    def _install_git(self, path: str) -> tuple[bool, str]:
        repo_dir = path
        is_update = os.path.isdir(os.path.join(repo_dir, ".git"))

        if is_update:
            self._log("Pulling latest changes...")
            ok, out = run_git(["git", "pull", "origin", "main"], repo_dir)
            if not ok:
                return False, f"Git pull failed:\n{out}"
            # Restore any files we need to keep
            self._log("Restoring local config and chats...")
            for k in KEEP_FILES:
                kp = _to_abs(repo_dir, k)
                if os.path.exists(kp):
                    run_git(["git", "checkout", "--", k], repo_dir)
            return True, "Update complete."
        else:
            self._log("Cloning repository...")
            ok, out = run_git(["git", "clone", REPO_URL, repo_dir], os.path.dirname(repo_dir) or ".")
            if not ok:
                return False, f"Clone failed:\n{out}"
            return True, "Install complete."

    def _install_done(self, ok: bool, msg: str):
        self.progress.stop()
        self.install_btn.config(state=tk.NORMAL)
        self._log(msg)
        if ok:
            messagebox.showinfo("Success", msg)
        else:
            messagebox.showerror("Error", msg)
        self._detect_existing()


def main():
    root = tk.Tk()
    app = InstallerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
