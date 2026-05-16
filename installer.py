#!/usr/bin/env python3
"""
OpenBlox Installer & Updater
Clones/updates OpenBlox from GitHub while preserving config, chats, and assets.
"""

import argparse
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
KEEP_PATHS = {"frontend/assets"}
VERSION_URL = "https://raw.githubusercontent.com/Artemcik5/OpenBlox/refs/heads/main/version"


def _is_kept(dest: str, file_path: str) -> bool:
    abs_file = os.path.normpath(os.path.abspath(file_path))
    for kept in KEEP_PATHS:
        kept_path = os.path.normpath(os.path.abspath(os.path.join(dest, kept)))
        if abs_file == kept_path or abs_file.startswith(kept_path + os.sep):
            return True
    return False


def _backup_kept(dest: str) -> str:
    backup = os.path.join(tempfile.gettempdir(), "openblox_backup")
    if os.path.isdir(backup):
        shutil.rmtree(backup)
    for kept in KEEP_PATHS:
        src = os.path.join(dest, kept)
        if not os.path.exists(src):
            continue
        dst = os.path.join(backup, kept)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
        else:
            shutil.copytree(src, dst)
    return backup


def _restore_kept(dest: str, backup: str):
    if not os.path.isdir(backup):
        return
    for kept in KEEP_PATHS:
        src = os.path.join(backup, kept)
        if not os.path.exists(src):
            continue
        dst = os.path.join(dest, kept)
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        else:
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
    shutil.rmtree(backup)


def get_remote_version() -> str:
    try:
        resp = urlopen(VERSION_URL, timeout=5)
        return resp.read().decode("utf-8").strip()
    except Exception:
        return "?"


def get_local_version(install_dir: str) -> str:
    version_path = os.path.join(install_dir, "version")
    if os.path.isfile(version_path):
        with open(version_path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    return "-"


def has_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=5, check=False)
        return True
    except Exception:
        return False


def should_skip_update(path: str, log_fn) -> bool:
    local = get_local_version(path)
    remote = get_remote_version()
    if local not in {"", "-", "?"} and remote not in {"", "?"} and local == remote:
        log_fn(f"Version v{local} is already up to date. Skipping update.")
        return True
    return False


def git_worktree_is_clean(path: str) -> bool:
    ok, out = run_git(["git", "status", "--porcelain"], path)
    if not ok:
        return False
    return not out.strip()


def run_git(cmd: list[str], cwd: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120, check=False)
        return result.returncode == 0, (result.stdout.strip() or result.stderr.strip() or "Done.")
    except subprocess.TimeoutExpired:
        return False, "Timed out"
    except FileNotFoundError:
        return False, "Git not found"
    except Exception as e:
        return False, str(e)


def install_from_zip(install_dir: str, log_fn) -> tuple[bool, str]:
    log_fn("Downloading repository...")
    tmp = tempfile.gettempdir()
    zip_path = os.path.join(tmp, "openblox.zip")
    extract_to = os.path.join(tmp, "openblox_extract")

    try:
        resp = urlopen(ZIP_URL, timeout=30)
        with open(zip_path, "wb") as handle:
            handle.write(resp.read())
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

    items = os.listdir(extract_to)
    source = os.path.join(extract_to, items[0]) if items else extract_to

    log_fn("Backing up config, chats, assets...")
    backup = _backup_kept(install_dir)

    log_fn("Copying files...")
    count = 0
    for root, _, files in os.walk(source):
        rel = os.path.relpath(root, source)
        rel = "" if rel == "." else rel
        for name in files:
            dst_file = os.path.normpath(os.path.join(install_dir, rel, name))
            if _is_kept(install_dir, dst_file):
                continue
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            src_file = os.path.join(root, name)
            try:
                shutil.copy2(src_file, dst_file)
                count += 1
            except Exception:
                pass

    log_fn("Restoring config, chats, assets...")
    _restore_kept(install_dir, backup)
    return True, f"{count} files updated."


def install_with_git(path: str, log_fn) -> tuple[bool, str]:
    is_update = os.path.isdir(os.path.join(path, ".git"))
    if not is_update:
        log_fn("Cloning repository...")
        ok, out = run_git(["git", "clone", REPO_URL, path], os.path.dirname(path) or ".")
        return (ok, out) if ok else (False, f"Clone failed:\n{out}")

    if should_skip_update(path, log_fn):
        return True, "Already on the latest version."

    log_fn("Backing up config, chats, assets...")
    backup = _backup_kept(path)

    if not git_worktree_is_clean(path):
        log_fn("Git worktree has local changes. Falling back to ZIP update.")
        _restore_kept(path, backup)
        return install_from_zip(path, log_fn)

    log_fn("Pulling latest changes...")
    ok, out = run_git(["git", "pull", "--ff-only", "origin", "main"], path)
    if not ok:
        log_fn("Git pull failed. Falling back to ZIP update.")
        _restore_kept(path, backup)
        return install_from_zip(path, log_fn)

    log_fn("Restoring config, chats, assets...")
    _restore_kept(path, backup)
    return True, "Update complete."


def install_or_update(path: str, log_fn) -> tuple[bool, str]:
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
    elif should_skip_update(path, log_fn):
        return True, "Already on the latest version."
    if has_git():
        log_fn("Git found. Using git method.")
        return install_with_git(path, log_fn)
    log_fn("Git not found. Downloading ZIP...")
    return install_from_zip(path, log_fn)


def launch_run_py_visible(path: str):
    run_path = os.path.join(path, "run.py")
    if not os.path.isfile(run_path):
        raise FileNotFoundError(f"run.py not found in {path}")
    subprocess.Popen(
        [sys.executable, run_path],
        cwd=path,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


class InstallerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("OpenBlox Installer")
        root.geometry("520x360")
        root.minsize(480, 320)
        root.configure(bg="#0f1622")
        self.install_dir = tk.StringVar()
        self._style()
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
        style.configure("Horizontal.TProgressbar", background="#58a6ff", troughcolor="#0d1117")

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=15)
        main.pack(fill=tk.BOTH, expand=True)
        ttk.Label(main, text="OpenBlox Installer",
                 font=("Segoe UI", 15, "bold"), foreground="#58a6ff").pack(anchor=tk.W)
        ttk.Label(main, text="Install or update OpenBlox from GitHub",
                 font=("Segoe UI", 9), foreground="#8b949e").pack(anchor=tk.W, pady=(0, 12))
        pf = ttk.Frame(main)
        pf.pack(fill=tk.X, pady=4)
        ttk.Label(pf, text="Install path:").pack(anchor=tk.W)
        row = ttk.Frame(pf)
        row.pack(fill=tk.X, pady=3)
        self.path_entry = ttk.Entry(row, textvariable=self.install_dir)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Browse", command=self._browse).pack(side=tk.RIGHT, padx=(6, 0))
        self.info_frame = ttk.LabelFrame(main, text="Status", padding=8)
        self.info_frame.pack(fill=tk.X, pady=10)
        self.local_label = ttk.Label(self.info_frame, text="Local: -", font=("Segoe UI", 9))
        self.local_label.pack(anchor=tk.W)
        self.remote_label = ttk.Label(self.info_frame, text="Remote: -", font=("Segoe UI", 9))
        self.remote_label.pack(anchor=tk.W)
        self.action_label = ttk.Label(self.info_frame, text="", font=("Segoe UI", 9, "bold"))
        self.action_label.pack(anchor=tk.W, pady=(4, 0))
        self.progress = ttk.Progressbar(main, mode="indeterminate", length=400)
        self.progress.pack(fill=tk.X, pady=(6, 0))
        self.log_text = tk.Text(main, height=4, wrap=tk.WORD, bg="#0d1117", fg="#8b949e",
                                font=("Consolas", 9), borderwidth=0, highlightthickness=1,
                                highlightbackground="#30363d", state=tk.DISABLED)
        self.log_text.pack(fill=tk.X, pady=(6, 0))
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
        selected = filedialog.askdirectory(title="Select install folder")
        if selected:
            self.install_dir.set(selected)
            self._detect_existing()

    def _detect_existing(self):
        path = self.install_dir.get()
        if not path or not os.path.isdir(path):
            self.local_label.config(text="Local: -")
            self.remote_label.config(text="Remote: -")
            self.action_label.config(text="")
            return
        local = get_local_version(path)
        remote = get_remote_version()
        self.local_label.config(text=f"Local: v{local}" if local != "-" else "Local: (not installed)")
        self.remote_label.config(text=f"Remote: v{remote}")
        if local == "-":
            self.action_label.config(text="New installation", foreground="#58a6ff")
        elif local != remote and remote != "?":
            self.action_label.config(text=f"Update available: v{local} -> v{remote}", foreground="#facc15")
        else:
            self.action_label.config(text="Up to date", foreground="#3fb950")

    def _start_install(self):
        path = self.install_dir.get().strip()
        if not path:
            messagebox.showerror("Error", "Select an install path first.")
            return
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
        try:
            ok, msg = install_or_update(path, self._log)
        except Exception as e:
            ok, msg = False, str(e)
        self.root.after(0, self._install_done, ok, msg)

    def _install_done(self, ok: bool, msg: str):
        self.progress.stop()
        self.install_btn.config(state=tk.NORMAL)
        self._log(msg)
        if ok:
            messagebox.showinfo("Success", msg)
        else:
            messagebox.showerror("Error", msg)
        self._detect_existing()


def parse_args():
    parser = argparse.ArgumentParser(description="Install or update OpenBlox.")
    parser.add_argument("--terminal", action="store_true",
                        help="Run the installer in the terminal instead of the GUI.")
    parser.add_argument("--path", default=os.path.dirname(os.path.abspath(__file__)),
                        help="Target install directory.")
    parser.add_argument("--launch", action="store_true",
                        help="After updating, start run.py in a visible terminal window.")
    return parser.parse_args()


def run_terminal_mode(path: str, launch: bool) -> int:
    print(f"OpenBlox installer (terminal mode)")
    print(f"Target: {path}")
    ok, msg = install_or_update(path, print)
    print(msg)
    if not ok:
        return 1
    if launch:
        print("Launching run.py in a visible terminal...")
        try:
            launch_run_py_visible(path)
        except Exception as e:
            print(f"Launch failed: {e}")
            return 1
    return 0


def main():
    args = parse_args()
    if args.terminal:
        raise SystemExit(run_terminal_mode(os.path.abspath(args.path), args.launch))

    root = tk.Tk()
    app = InstallerApp(root)
    app.install_dir.set(os.path.abspath(args.path))
    app._detect_existing()
    root.mainloop()


if __name__ == "__main__":
    main()
