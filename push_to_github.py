#!/usr/bin/env python3
"""
push_to_github.py - creates a GitHub repo (if needed) and uploads this whole
project folder to it, using ONLY a GitHub Personal Access Token (REST API,
no `git` CLI required).

Usage:
    pip install requests
    export GITHUB_TOKEN="ghp_xxx...xxx"        # a GitHub PAT with "repo" scope
    python3 push_to_github.py --repo aether-warp-android --private

    # or pass the token directly instead of the env var:
    python3 push_to_github.py --repo aether-warp-android --token ghp_xxx

What it does:
  1. Creates the repo under your account (skips if it already exists).
  2. Walks the local project folder (default: the folder this script is in)
     and uploads every file through GitHub's Contents API
     (PUT /repos/{owner}/{repo}/contents/{path}), which both creates the
     file AND makes a commit - no local git needed at all.
  3. Skips junk (.git, __pycache__, .buildozer, bin/, .buildozer output,
     *.pyc) automatically.

After this finishes, GitHub Actions (.github/workflows/build.yml) will
start building the APK automatically - check the repo's "Actions" tab.
"""
import argparse
import base64
import os
import sys
import time

import requests

API = "https://api.github.com"

SKIP_DIRS = {".git", "__pycache__", ".buildozer", "bin", ".gradle", ".tox", "venv", ".venv"}
SKIP_EXT = {".pyc", ".pyo"}


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


def create_repo(token: str, name: str, private: bool, description: str) -> dict:
    r = requests.post(
        f"{API}/user/repos",
        headers=gh_headers(token),
        json={"name": name, "private": private, "description": description, "auto_init": False},
        timeout=20,
    )
    if r.status_code == 201:
        print(f"created repo: {r.json()['full_name']}")
        return r.json()
    if r.status_code == 422:
        print(f"repo '{name}' already exists under your account - reusing it.")
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


def upload_file(token: str, owner: str, repo: str, branch: str, full_path: str, rel_path: str, retries=3):
    with open(full_path, "rb") as fh:
        content_b64 = base64.b64encode(fh.read()).decode()

    url = f"{API}/repos/{owner}/{repo}/contents/{rel_path}"

    # check if the file already exists (needed to update instead of create)
    sha = None
    r = requests.get(url, headers=gh_headers(token), params={"ref": branch}, timeout=20)
    if r.status_code == 200:
        sha = r.json().get("sha")

    body = {
        "message": f"add {rel_path}" if sha is None else f"update {rel_path}",
        "content": content_b64,
        "branch": branch,
    }
    if sha:
        body["sha"] = sha

    for attempt in range(1, retries + 1):
        resp = requests.put(url, headers=gh_headers(token), json=body, timeout=60)
        if resp.status_code in (200, 201):
            print(f"  ok   {rel_path}")
            return
        if resp.status_code == 409 and attempt < retries:
            # branch moved under us (race) - just retry
            time.sleep(1)
            continue
        print(f"  FAIL {rel_path}: {resp.status_code} {resp.text[:300]}")
        return


def main():
    ap = argparse.ArgumentParser(description="Push this project to GitHub using only a PAT (no git CLI).")
    ap.add_argument("--repo", required=True, help="repository name to create/use")
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"),
                     help="GitHub PAT (or set GITHUB_TOKEN env var)")
    ap.add_argument("--private", action="store_true", help="create the repo as private")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--path", default=os.path.dirname(os.path.abspath(__file__)),
                     help="local project folder to upload (default: this script's folder)")
    ap.add_argument("--description", default="Aether WARP - Kivy Android app")
    args = ap.parse_args()

    if not args.token:
        sys.exit("No token given. Use --token or set GITHUB_TOKEN.")

    owner = get_authenticated_user(args.token)
    repo_info = create_repo(args.token, args.repo, args.private, args.description)
    branch = repo_info.get("default_branch") or args.branch

    files = list(iter_project_files(args.path))
    print(f"uploading {len(files)} files to {owner}/{args.repo} ({branch}) ...")
    for full, rel in files:
        upload_file(args.token, owner, args.repo, branch, full, rel)

    print(f"\ndone: https://github.com/{owner}/{args.repo}")
    print("GitHub Actions should start the APK build automatically - check the 'Actions' tab.")


if __name__ == "__main__":
    main()
