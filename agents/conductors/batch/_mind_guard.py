"""Where a lane may write into a PyAutoMind checkout — the one git probe.

The main checkout of any Mind clone may be the shared, canonical one other
sessions work in, so writes go only into a LINKED worktree (a temp worktree on
`origin/main`) or into a directory that is not a git checkout at all (a test
fixture, a scratch copy). `_batch.write_hold` (the keep-Heart-green lane and
`brief --check`) and the maintenance writer (`_maintain_write`) share it.
Stdlib only; it runs `git rev-parse` and nothing else.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def is_linked_worktree(path: Path) -> bool:
    """True only for a LINKED git worktree (`--git-dir` differs from
    `--git-common-dir`). The main checkout of any clone, wherever it lives,
    is False — so is anything git cannot read."""
    dirs = []
    for flag in ("--git-dir", "--git-common-dir"):
        try:
            out = subprocess.run(["git", "-C", str(path), "rev-parse", flag],
                                 capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if out.returncode != 0 or not out.stdout.strip():
            return False
        dirs.append((path / out.stdout.strip()).resolve())
    return dirs[0] != dirs[1]


def in_git_checkout(path: Path) -> bool:
    """True when `path` is inside any git working tree. Fails closed: when git
    cannot be run, any `.git` entry in `path` or an ancestor counts as one."""
    path = Path(path).resolve()
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse",
                              "--is-inside-work-tree"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return any((p / ".git").exists() for p in (path, *path.parents))
    return out.returncode == 0 and out.stdout.strip() == "true"
