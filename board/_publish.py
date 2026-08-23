#!/usr/bin/env python3
"""board/_publish.py — push a distilled dev-box observation into the Brain repo.

The board's cloud render is honest about what it cannot see: hygiene debt and
worktree state are local-machine facts. This is the sanctioned enrichment path
(the Heart's heart/publish.py pattern): the dev box distills BOTH into
``state/devbox_board.json``, commits, and pushes to the Brain's own repo —
brain_board.yml re-publishes on that push, so the board shows them age-stamped
("observed Nh ago via morning.sh"), going stale at 48h and dropping after 7d.

The natural caller is ``bin/morning.sh`` — the one command a human already
runs each morning on the machine that has the observations.

Distilled, never raw:
  * hygiene — the conductor's own fast pre-scan (`hygiene.sh --json`, the
    HygieneDecision rows verbatim; this module re-derives nothing).
  * worktrees — repos under $PYAUTO_ROOT that are off their default branch,
    carry unpushed commits, are dirty, or hold stashes. Repo names only.

Privacy: the repo is public. Any text naming a local filesystem path has the
home directory collapsed to ``~`` before it leaves the machine; repo and
branch names are fine.

Usage:
    pyauto-brain board publish              # distill + commit + push
    pyauto-brain board publish --dry-run    # print the JSON, write nothing
    pyauto-brain board publish --no-hygiene # worktrees only (fast)

Env (hermetic tests override): PYAUTO_ROOT, BOARD_HYGIENE_CMD (the hygiene
entrypoint), BOARD_DEVBOX_FILE (the output path).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
PYAUTO_ROOT = Path(os.environ.get("PYAUTO_ROOT", BRAIN_HOME.parent))
DEVBOX_FILE = Path(os.environ.get(
    "BOARD_DEVBOX_FILE", BRAIN_HOME / "state" / "devbox_board.json"))
HYGIENE_CMD = os.environ.get(
    "BOARD_HYGIENE_CMD",
    str(BRAIN_HOME / "agents" / "conductors" / "hygiene" / "hygiene.sh"))

SCHEMA_VERSION = 1


def _scrub(text):
    """Collapse the home directory in any outbound string to `~`."""
    home = os.path.expanduser("~")
    out = str(text)
    if home and home != "~":
        out = out.replace(home, "~")
    return out


def collect_hygiene():
    """The hygiene conductor's fast pre-scan, verbatim (its --json footing).
    None on any failure — the payload degrades to worktrees-only."""
    try:
        r = subprocess.run(["bash", HYGIENE_CMD, "--json"],
                           capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        decision = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    rows = []
    for row in decision.get("rows", []):
        rows.append({
            "mode": row.get("mode"),
            "status": row.get("status"),
            "count": row.get("count"),
            "summary": _scrub(row.get("summary", ""))[:200],
            "delegate": row.get("delegate"),
        })
    return {"rows": rows}


def _git_out(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip() if r.returncode == 0 else None


def collect_worktrees():
    """Repos under PYAUTO_ROOT worth a morning glance: off their default
    branch, ahead of upstream, dirty, or holding stashes. Names only."""
    rows = []
    if not PYAUTO_ROOT.is_dir():
        return rows
    for repo in sorted(PYAUTO_ROOT.iterdir()):
        if not (repo / ".git").exists():
            continue
        branch = _git_out(repo, "branch", "--show-current") or "?"
        ahead_out = _git_out(repo, "rev-list", "--count", "@{u}..HEAD")
        ahead = int(ahead_out) if ahead_out and ahead_out.isdigit() else 0
        dirty = bool(_git_out(repo, "status", "--porcelain",
                              "--untracked-files=no"))
        stash_out = _git_out(repo, "stash", "list") or ""
        stashes = len([l for l in stash_out.splitlines() if l.strip()])
        off_default = branch not in ("main", "master")
        if off_default or ahead or dirty or stashes:
            rows.append({"repo": repo.name, "branch": branch, "ahead": ahead,
                         "dirty": dirty, "stashes": stashes})
    return rows


def build_payload(with_hygiene=True):
    payload = {
        "schema": SCHEMA_VERSION,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "worktrees": collect_worktrees(),
    }
    if with_hygiene:
        hygiene = collect_hygiene()
        if hygiene is not None:
            payload["hygiene"] = hygiene
    return payload


# The repo the observation is committed to — the Brain checkout itself, or a
# fabricated repo in hermetic tests (which point BOARD_DEVBOX_FILE inside it).
PUBLISH_REPO = Path(os.environ.get("BOARD_PUBLISH_REPO", BRAIN_HOME))


def _git(*args):
    return subprocess.run(["git", "-C", str(PUBLISH_REPO), *args],
                          capture_output=True, text=True, timeout=120)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="board publish", description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the distilled JSON, write and push nothing")
    ap.add_argument("--no-hygiene", action="store_true",
                    help="skip the hygiene pre-scan (worktrees only)")
    ns = ap.parse_args(argv)

    payload = build_payload(with_hygiene=not ns.no_hygiene)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if ns.dry_run:
        print(text, end="")
        return 0

    branch = _git("branch", "--show-current").stdout.strip()
    if branch != "main":
        print(f"board publish: Brain checkout is on '{branch}' — publish "
              "commits to main only; switch to main first (or --dry-run)",
              file=sys.stderr)
        return 2

    DEVBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Idempotence ignores the timestamp: an unchanged observation must not
    # bump the file (and re-trigger brain_board.yml) just because the clock
    # moved between two runs.
    if DEVBOX_FILE.exists():
        try:
            prev = json.loads(DEVBOX_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            prev = None
        if prev is not None and \
                {k: v for k, v in prev.items() if k != "ts"} == \
                {k: v for k, v in payload.items() if k != "ts"}:
            print("board publish: devbox observation already current — "
                  "nothing to push")
            return 0
    DEVBOX_FILE.write_text(text)

    rel = os.path.relpath(DEVBOX_FILE, PUBLISH_REPO)
    _git("add", rel)
    committed = _git("commit", "-m",
                     "brain: publish dev-box observation (hygiene + worktrees)")
    if committed.returncode != 0:
        blob = committed.stdout + committed.stderr
        if "nothing to commit" in blob:
            print("board publish: unchanged after staging — nothing to push")
            return 0
        print(blob, file=sys.stderr)
        return 1

    # Concurrent pushes to main are normal; rebase our one commit and retry.
    for _attempt in (1, 2, 3):
        pushed = _git("push", "origin", "HEAD")
        if pushed.returncode == 0:
            print(f"board publish: pushed {rel} "
                  f"({len(payload['worktrees'])} worktree row(s)"
                  + (", hygiene included" if "hygiene" in payload else "")
                  + f", ts {payload['ts']}) — brain_board.yml republishes on "
                  "this push")
            return 0
        rebased = _git("pull", "--rebase", "origin", "main")
        if rebased.returncode != 0:
            print(rebased.stderr or rebased.stdout, file=sys.stderr)
            return 1
    print("board publish: could not push after 3 attempts", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
