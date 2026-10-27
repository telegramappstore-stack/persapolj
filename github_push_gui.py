#!/usr/bin/env python3
"""
github_push_gui.py - standalone, graphical (Tkinter) tool to push a local
project folder to GitHub using ONLY a Personal Access Token (REST API,
no `git` CLI needed). Same dark color palette as aether_tool2.py so it
feels like part of the same toolset.

pip install requests
python3 github_push_gui.py
"""
import base64
import json
import os
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import requests

API = "https://api.github.com"
SKIP_DIRS = {".git", "__pycache__", ".buildozer", "bin", ".gradle", ".tox", "venv", ".venv"}
SKIP_EXT = {".pyc", ".pyo"}

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "github_push_settings.json")

C = {
    "bg": "#070a13", "card": "#101828", "input": "#0b1220", "border": "#1d2a45",
    "text": "#eaeefb", "muted": "#8d99b8", "cyan": "#22d3ee", "blue": "#4f8cff",
    "violet": "#9b6bff", "green": "#34d399", "red": "#f87171",
}


def ts():
    return time.strftime("%H:%M:%S")


# ======================================================================
# GitHub REST API helpers (same logic as push_to_github.py)
# ======================================================================
def gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_authenticated_user(token: str) -> str:
    r = requests.get(f"{API}/user", headers=gh_headers(token), timeout=20)
    r.raise_for_status()
    return r.json()["login"]


def create_or_get_repo(token: str, name: str, private: bool, description: str, log) -> dict:
    r = requests.post(f"{API}/user/repos", headers=gh_headers(token),
                       json={"name": name, "private": private,
                             "description": description, "auto_init": False}, timeout=20)
    if r.status_code == 201:
        log(f"Repo created: {r.json()['full_name']}")
        return r.json()
    if r.status_code == 422:
        log(f"Repo '{name}' already exists - reusing it.")
        owner = get_authenticated_user(token)
        r2 = requests.get(f"{API}/repos/{owner}/{name}", headers=gh_headers(token), timeout=20)
        r2.raise_for_status()
        return r2.json()
    r.raise_for_status()


def iter_project_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and d != ".git"]
        for fn in filenames:
            if os.path.splitext(fn)[1] in SKIP_EXT:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            yield full, rel


def upload_file(token, owner, repo, branch, full_path, rel_path, log, retries=3):
    with open(full_path, "rb") as fh:
        content_b64 = base64.b64encode(fh.read()).decode()
    url = f"{API}/repos/{owner}/{repo}/contents/{rel_path}"
    sha = None
    r = requests.get(url, headers=gh_headers(token), params={"ref": branch}, timeout=20)
    if r.status_code == 200:
        sha = r.json().get("sha")
    body = {"message": f"add {rel_path}" if sha is None else f"update {rel_path}",
            "content": content_b64, "branch": branch}
    if sha:
        body["sha"] = sha
    for attempt in range(1, retries + 1):
        resp = requests.put(url, headers=gh_headers(token), json=body, timeout=60)
        if resp.status_code in (200, 201):
            log(f"  ok    {rel_path}")
            return True
        if resp.status_code == 409 and attempt < retries:
            time.sleep(1)
            continue
        log(f"  FAIL  {rel_path}: {resp.status_code} {resp.text[:200]}")
        return False
    return False


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass


# ======================================================================
# GUI
# ======================================================================
class Field(tk.Frame):
    def __init__(self, parent, label, var, browse=None, show=None):
        super().__init__(parent, bg=C["bg"])
        tk.Label(self, text=label, bg=C["bg"], fg=C["muted"], font=("Segoe UI", 9),
                 anchor="w").pack(fill="x")
        box = tk.Frame(self, bg=C["input"], highlightthickness=1,
                        highlightbackground=C["border"])
        box.pack(fill="x", pady=(4, 0))
        self.entry = tk.Entry(box, textvariable=var, bg=C["input"], fg=C["text"],
                               insertbackground=C["cyan"], relief="flat", bd=0,
                               font=("Consolas", 10), show=show)
        self.entry.pack(side="left", fill="x", expand=True, padx=8, pady=7)
        if browse:
            lk = tk.Label(box, text="Browse", bg=C["input"], fg=C["cyan"],
                          font=("Segoe UI", 9, "bold"), cursor="hand2")
            lk.pack(side="right", padx=(0, 8))
            lk.bind("<Button-1>", lambda e: browse())


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Push to GitHub - Aether WARP")
        self.configure(bg=C["bg"])
        self.geometry("640x620")
        self.minsize(560, 520)

        default_path = os.path.dirname(os.path.abspath(__file__))
        settings = load_settings()

        self.v_token = tk.StringVar(value=settings.get("token", ""))
        self.v_repo = tk.StringVar(value=settings.get("repo", ""))
        self.v_desc = tk.StringVar(value=settings.get("description", "Aether WARP - Kivy Android app"))
        self.v_branch = tk.StringVar(value=settings.get("branch", "main"))
        self.v_private = tk.BooleanVar(value=settings.get("private", True))
        self.v_path = tk.StringVar(value=settings.get("path", default_path))

        self._build()

    def _build(self):
        pad = tk.Frame(self, bg=C["bg"])
        pad.pack(fill="both", expand=True, padx=18, pady=16)

        tk.Label(pad, text="Push project to GitHub", bg=C["bg"], fg=C["text"],
                 font=("Segoe UI", 15, "bold"), anchor="w").pack(fill="x")
        tk.Label(pad, text="Uses only a Personal Access Token via the GitHub REST API - no git required.",
                 bg=C["bg"], fg=C["muted"], font=("Segoe UI", 9), anchor="w",
                 justify="left").pack(fill="x", pady=(0, 12))

        Field(pad, "GitHub token (PAT, repo scope)", self.v_token, show="*").pack(fill="x", pady=(0, 10))
        Field(pad, "Local project folder", self.v_path, browse=self._browse_folder).pack(fill="x", pady=(0, 10))
        Field(pad, "Repository name", self.v_repo).pack(fill="x", pady=(0, 10))
        Field(pad, "Description", self.v_desc).pack(fill="x", pady=(0, 10))
        Field(pad, "Branch", self.v_branch).pack(fill="x", pady=(0, 10))

        row = tk.Frame(pad, bg=C["bg"])
        row.pack(fill="x", pady=(0, 12))
        tk.Checkbutton(row, text="Private repository", variable=self.v_private,
                       bg=C["bg"], fg=C["text"], selectcolor=C["input"],
                       activebackground=C["bg"], activeforeground=C["text"],
                       font=("Segoe UI", 10)).pack(side="left")

        btn_row = tk.Frame(pad, bg=C["bg"])
        btn_row.pack(fill="x", pady=(0, 12))
        self.btn_push = tk.Button(btn_row, text="Push to GitHub", command=self.on_push,
                                   bg=C["blue"], fg="white", activebackground=C["violet"],
                                   activeforeground="white", relief="flat",
                                   font=("Segoe UI", 11, "bold"), padx=18, pady=8, cursor="hand2")
        self.btn_push.pack(side="left")
        tk.Button(btn_row, text="Open repo in browser", command=self.open_repo,
                  bg=C["card"], fg=C["text"], activebackground=C["border"],
                  relief="flat", font=("Segoe UI", 10), padx=14, pady=8,
                  cursor="hand2").pack(side="left", padx=(8, 0))

        tk.Label(pad, text="Log", bg=C["bg"], fg=C["muted"], font=("Segoe UI", 9),
                 anchor="w").pack(fill="x")
        log_box = tk.Frame(pad, bg=C["input"], highlightthickness=1,
                            highlightbackground=C["border"])
        log_box.pack(fill="both", expand=True, pady=(4, 0))
        sb = ttk.Scrollbar(log_box, orient="vertical")
        sb.pack(side="right", fill="y")
        self.log_text = tk.Text(log_box, bg=C["input"], fg="#c3cbe0", relief="flat",
                                 font=("Consolas", 9), wrap="word", state="disabled",
                                 yscrollcommand=sb.set, padx=10, pady=8)
        self.log_text.pack(side="left", fill="both", expand=True)
        sb.config(command=self.log_text.yview)
        for tag, col in (("ok", C["green"]), ("err", C["red"]), ("info", C["cyan"])):
            self.log_text.tag_configure(tag, foreground=col)

        self._repo_url = None

    def _browse_folder(self):
        d = filedialog.askdirectory(initialdir=self.v_path.get() or os.getcwd())
        if d:
            self.v_path.set(d)

    def log(self, msg, tag="plain"):
        def add():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"[{ts()}] {msg}\n", tag)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, add)

    def open_repo(self):
        if self._repo_url:
            import webbrowser
            webbrowser.open(self._repo_url)
        else:
            messagebox.showinfo("No repo yet", "Push the project first.")

    def on_push(self):
        token = self.v_token.get().strip()
        repo = self.v_repo.get().strip()
        path = self.v_path.get().strip()
        branch = self.v_branch.get().strip() or "main"
        desc = self.v_desc.get().strip()
        private = self.v_private.get()

        if not token:
            return messagebox.showwarning("Missing token", "Enter your GitHub token first.")
        if not repo:
            return messagebox.showwarning("Missing repo name", "Enter a repository name first.")
        if not path or not os.path.isdir(path):
            return messagebox.showwarning("Invalid folder", "Pick a valid local project folder.")

        save_settings({"token": token, "repo": repo, "description": desc, "branch": branch,
                       "private": private, "path": path})

        self.btn_push.config(state="disabled", text="Pushing...")

        def work():
            try:
                owner = get_authenticated_user(token)
                self.log(f"Authenticated as {owner}", "info")
                repo_info = create_or_get_repo(token, repo, private, desc, self.log)
                b = repo_info.get("default_branch") or branch
                files = list(iter_project_files(path))
                self.log(f"Uploading {len(files)} files to {owner}/{repo} ({b}) ...", "info")
                ok_count = 0
                for full, rel in files:
                    if upload_file(token, owner, repo, b, full, rel, self.log):
                        ok_count += 1
                self._repo_url = f"https://github.com/{owner}/{repo}"
                self.log(f"Done: {ok_count}/{len(files)} files uploaded.", "ok")
                self.log(self._repo_url, "ok")
                self.log("GitHub Actions should start the APK build automatically "
                         "(check the Actions tab).", "info")
            except requests.HTTPError as e:
                self.log(f"GitHub API error: {e}", "err")
            except Exception as e:  # noqa: BLE001
                self.log(f"Error: {type(e).__name__}: {e}", "err")
            finally:
                self.after(0, lambda: self.btn_push.config(state="normal", text="Push to GitHub"))

        threading.Thread(target=work, daemon=True).start()


if __name__ == "__main__":
    App().mainloop()
