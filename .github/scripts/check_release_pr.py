#!/usr/bin/env python3
"""Refuse to auto-merge a release PR unless it only bumps versions and
prepends to CHANGELOG.md.

Usage: check_release_pr.py BASE_REF HEAD_SHA
Compares git objects directly, so the merge must be pinned to HEAD_SHA.
"""
import json
import subprocess
import sys

VERSION_FILES = [
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    ".github/plugin/plugin.json",
    ".qoder-plugin/plugin.json",
]
MANIFEST = ".release-please-manifest.json"
CHANGELOG = "CHANGELOG.md"
ALLOWED = set(VERSION_FILES) | {MANIFEST, CHANGELOG}


def git(*args):
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def show(ref, path):
    try:
        return git("show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return None


def check(base, head):
    errors = []
    changed = set(git("diff", "--name-only", f"{base}...{head}").split())
    for path in sorted(changed - ALLOWED):
        errors.append(f"unexpected file changed: {path}")

    for path in VERSION_FILES:
        old, new = show(base, path), show(head, path)
        if old is None or new is None:
            errors.append(f"{path}: missing on base or head")
            continue
        old, new = json.loads(old), json.loads(new)
        old.pop("version", None)
        new.pop("version", None)
        if old != new:
            errors.append(f"{path}: changes something other than version")

    manifest = show(head, MANIFEST)
    if manifest is None or list(json.loads(manifest)) != ["."]:
        errors.append(f"{MANIFEST}: must contain only the '.' package")

    old_log, new_log = show(base, CHANGELOG) or "", show(head, CHANGELOG)
    if new_log is None:
        errors.append(f"{CHANGELOG}: missing on head")
    else:
        # release-please inserts the new entry under the title line.
        title, _, rest = old_log.partition("\n")
        if not (new_log.startswith(title + "\n") and new_log.endswith(rest)):
            errors.append(f"{CHANGELOG}: existing entries were modified")

    return errors


if __name__ == "__main__":
    problems = check(sys.argv[1], sys.argv[2])
    for p in problems:
        print(f"::error::{p}")
    sys.exit(1 if problems else 0)
