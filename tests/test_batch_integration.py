"""tests/test_batch_integration.py — the batch conductor's integration branches.

The Witness the task registers: *a batch-conductor test builds a temp repo with
two member branches, runs `collect --integration`, and asserts
`integration/<slot>` tree == merge of both heads plus a packet line `clean` /
`conflicted: <path>` per repo; evidence JSON carries `headRefName` for every
member PR.*

This module drives the real `bin/worktree.sh` against throwaway repos rather
than a re-implementation of it: the value of `worktree_create` is the root
layout (activate.sh's PYTHONPATH, the per-task caches, the symlink of every
other top-level entry), and a second definition of "a PyAuto worktree root"
would drift from the first.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
WORKTREE_SH = BRAIN / "bin" / "worktree.sh"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


def _repo(origins: Path, main: Path, name: str) -> Path:
    """A clone of a bare origin with one commit on `main`, as `worktree_create`
    expects: it branches from `origin/<default>`, so `origin/main` must exist."""
    origin = origins / f"{name}.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)],
                   check=True, capture_output=True)
    repo = main / name
    subprocess.run(["git", "clone", str(origin), str(repo)], check=True,
                   capture_output=True)
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("base\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-m", "base")
    _git(repo, "push", "-u", "origin", "main")
    return repo


def _create(tmp_path: Path, task: str, branch: str | None) -> tuple[Path, Path]:
    """Run the real `worktree_create` for one repo; return (root, worktree)."""
    origins = tmp_path / "origins"
    main = tmp_path / "main"
    origins.mkdir(parents=True, exist_ok=True)
    main.mkdir(parents=True, exist_ok=True)
    _repo(origins, main, "MyRepo")
    (main / "some_workspace").mkdir(exist_ok=True)  # symlinked, not a worktree

    env = {k: v for k, v in os.environ.items() if k != "PYAUTO_WT_BRANCH"}
    env.update({"HOME": str(tmp_path), "PYAUTO_ROOT": str(main),
                "PYAUTO_MAIN": str(main), "PYAUTO_WT_ROOT": str(tmp_path / "wt")})
    if branch is not None:
        env["PYAUTO_WT_BRANCH"] = branch
    proc = subprocess.run(
        ["bash", "-c", f'set -e; . "{WORKTREE_SH}"; worktree_create "$@"',
         "_", task, "MyRepo"],
        env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    root = tmp_path / "wt" / task
    return root, root / "MyRepo"


def _head(worktree: Path) -> str:
    got = subprocess.run(["git", "-C", str(worktree), "rev-parse",
                          "--abbrev-ref", "HEAD"],
                         check=True, capture_output=True, text=True)
    return got.stdout.strip()


def test_the_branch_name_override_is_honoured(tmp_path):
    """`collect --integration` builds a throwaway review root, and a root that
    calls itself `feature/<task>` masquerades as feature work — every branch
    sweep and every contribution check then has to guess. `PYAUTO_WT_BRANCH` is
    the one thing worktree.sh could not otherwise say."""
    _root, worktree = _create(tmp_path, "integration-2026-09-03-pm",
                              branch="integration/x")
    assert _head(worktree) == "integration/x"


def test_without_the_override_the_branch_is_still_feature_of_the_task(tmp_path):
    """The override is additive: unset, worktree.sh names branches exactly as
    every existing task worktree on disk is named."""
    _root, worktree = _create(tmp_path, "task-y", branch=None)
    assert _head(worktree) == "feature/task-y"
