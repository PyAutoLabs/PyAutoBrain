"""tests/test_worktree_claim_guard.py — worktree_remove's stale-claim refusal.

docs/agent_failure_modes.md mitigation 3 (F4): twice on 2026-07-16 a completed
task's `active.md` claim outlived its worktree, blocking the next task on a
phantom conflict while its completion record went unwritten. `worktree_remove`
is the cleanup choke-point, so the refusal lives there — same shape as the
dirty-repo guard, which is the mechanism that already works.

Drives the real bash function against a temp PYAUTO_MAIN fixture.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

WORKTREE_SH = Path(__file__).resolve().parents[1] / "bin" / "worktree.sh"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _repo_with_branch(root: Path, merged: bool) -> Path:
    """A repo whose HEAD is a feature branch, merged into origin/main or not."""
    origin = root / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True
    )
    repo = root / "MyRepo"
    subprocess.run(
        ["git", "clone", str(origin), str(repo)], check=True, capture_output=True
    )
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("base\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-m", "base")
    _git(repo, "push", "-u", "origin", "main")
    _git(repo, "checkout", "-b", "feature/task-x")
    (repo / "f.txt").write_text("work\n")
    _git(repo, "commit", "-am", "work")
    if merged:
        # A real merge commit, exactly as `gh pr merge --merge` produces: the
        # feature tip becomes the merge commit's SECOND parent (a fast-forward
        # push would be indistinguishable from a never-diverged branch).
        _git(repo, "checkout", "main")
        _git(repo, "merge", "--no-ff", "-m", "Merge feature/task-x", "feature/task-x")
        _git(repo, "push", "origin", "main")
        _git(repo, "checkout", "feature/task-x")
    _git(repo, "fetch", "origin")
    return repo


def _repo_never_committed(root: Path, main_moves: bool) -> Path:
    """A worktree-shaped repo whose branch has NO commits of its own."""
    origin = root / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True
    )
    seed = root.parent / "seed"
    subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True)
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / "f.txt").write_text("base\n")
    _git(seed, "add", "f.txt")
    _git(seed, "commit", "-m", "base")
    _git(seed, "push", "-u", "origin", "main")

    repo = root / "MyRepo"
    subprocess.run(["git", "clone", str(origin), str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-b", "feature/task-x")   # branch made, no commits
    if main_moves:
        (seed / "g.txt").write_text("other work\n")
        _git(seed, "add", "g.txt")
        _git(seed, "commit", "-m", "someone else's merge")
        _git(seed, "push", "origin", "main")
    _git(repo, "fetch", "origin")
    return repo


def _is_stale(tmp_path: Path, task: str, active_body: str, merged: bool) -> int:
    main = tmp_path / "main"
    (main / "PyAutoMind").mkdir(parents=True)
    (main / "PyAutoMind" / "active.md").write_text(active_body)
    wt_root = tmp_path / "wt" / task
    wt_root.mkdir(parents=True)
    _repo_with_branch(wt_root, merged=merged)
    proc = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{WORKTREE_SH}"; worktree_claim_is_stale "{task}" "{wt_root}"',
        ],
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "PYAUTO_MAIN": str(main),
            "PYAUTO_WT_ROOT": str(tmp_path / "wt"),
        },
        capture_output=True,
    )
    return proc.returncode


CLAIMED = "# Active Tasks\n\n## task-x\n- issue: http://x\n- worktree: ~/wt/task-x\n"
OTHER = "# Active Tasks\n\n## other-task\n- issue: http://y\n"


def test_merged_work_with_live_claim_is_stale(tmp_path):
    assert _is_stale(tmp_path, "task-x", CLAIMED, merged=True) == 0


def test_unmerged_work_is_not_stale(tmp_path):
    # Real in-flight work: removing is the caller's business, no refusal.
    assert _is_stale(tmp_path, "task-x", CLAIMED, merged=False) == 1


def test_released_claim_is_not_stale(tmp_path):
    # The normal, correct end-state: record written, entry dropped.
    assert _is_stale(tmp_path, "task-x", OTHER, merged=True) == 1


def test_missing_active_md_fails_open(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    wt_root = tmp_path / "wt" / "task-x"
    wt_root.mkdir(parents=True)
    _repo_with_branch(wt_root, merged=True)
    proc = subprocess.run(
        ["bash", "-c", f'source "{WORKTREE_SH}"; worktree_claim_is_stale "task-x" "{wt_root}"'],
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "PYAUTO_MAIN": str(main),
            "PYAUTO_WT_ROOT": str(tmp_path / "wt"),
        },
        capture_output=True,
    )
    assert proc.returncode == 1


def test_prefixed_task_heading_does_not_false_match(tmp_path):
    # `## task-x-phase-2` must not read as a claim on `task-x`.
    body = "# Active Tasks\n\n## task-x-phase-2\n- issue: http://z\n"
    assert _is_stale(tmp_path, "task-x", body, merged=True) == 1


def test_heading_with_trailing_note_still_matches(tmp_path):
    # `## task-x (phase 3 of 4)` IS a claim on task-x.
    body = "# Active Tasks\n\n## task-x (phase 3 of 4)\n- issue: http://z\n"
    assert _is_stale(tmp_path, "task-x", body, merged=True) == 0


# --- the false positive caught before shipping --------------------------------

def _is_stale_never_committed(tmp_path: Path, main_moves: bool) -> int:
    main = tmp_path / "main"
    (main / "PyAutoMind").mkdir(parents=True)
    (main / "PyAutoMind" / "active.md").write_text(CLAIMED)
    wt_root = tmp_path / "wt" / "task-x"
    wt_root.mkdir(parents=True)
    _repo_never_committed(wt_root, main_moves=main_moves)
    proc = subprocess.run(
        ["bash", "-c", f'source "{WORKTREE_SH}"; worktree_claim_is_stale "task-x" "{wt_root}"'],
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "PYAUTO_MAIN": str(main),
            "PYAUTO_WT_ROOT": str(tmp_path / "wt"),
        },
        capture_output=True,
    )
    return proc.returncode


def test_never_committed_worktree_is_not_stale(tmp_path):
    # Task registered, worktree created, no commits yet, user abandons it.
    # is-ancestor alone would call this "merged" and refuse — a false positive.
    assert _is_stale_never_committed(tmp_path, main_moves=False) == 1


def test_never_committed_worktree_is_not_stale_even_if_main_moved(tmp_path):
    # The nastier variant: other tasks merged meanwhile, so the untouched
    # branch tip is a strict ancestor of origin/main. Still nothing to record.
    assert _is_stale_never_committed(tmp_path, main_moves=True) == 1
