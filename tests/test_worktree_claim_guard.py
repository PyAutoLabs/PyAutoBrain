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

import pytest

from _helpers import git_in as _git, hermetic_worktree_env, source_worktree


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


def _is_stale(tmp_path: Path, active_body: str | None, make_repo, **repo_kw) -> int:
    """`worktree_claim_is_stale task-x <worktree>` against a fixture main whose
    `active.md` holds `active_body` (None: no registry at all)."""
    main = tmp_path / "main"
    if active_body is None:
        main.mkdir()
    else:
        (main / "PyAutoMind").mkdir(parents=True)
        (main / "PyAutoMind" / "active.md").write_text(active_body)
    wt_root = tmp_path / "wt" / "task-x"
    wt_root.mkdir(parents=True)
    make_repo(wt_root, **repo_kw)
    return source_worktree(f'worktree_claim_is_stale "task-x" "{wt_root}"',
                           hermetic_worktree_env(tmp_path)).returncode


CLAIMED = "# Active Tasks\n\n## task-x\n- issue: http://x\n- worktree: ~/wt/task-x\n"
OTHER = "# Active Tasks\n\n## other-task\n- issue: http://y\n"


@pytest.mark.parametrize("active_body,merged,code", [
    pytest.param(CLAIMED, True, 0, id="merged-work-with-live-claim-is-stale"),
    # Real in-flight work: removing is the caller's business, no refusal.
    pytest.param(CLAIMED, False, 1, id="unmerged-work-is-not-stale"),
    # The normal, correct end-state: record written, entry dropped.
    pytest.param(OTHER, True, 1, id="released-claim-is-not-stale"),
    pytest.param(None, True, 1, id="missing-active-md-fails-open"),
    # `## task-x-phase-2` must not read as a claim on `task-x`.
    pytest.param("# Active Tasks\n\n## task-x-phase-2\n- issue: http://z\n", True, 1,
                 id="prefixed-task-heading-does-not-false-match"),
    # `## task-x (phase 3 of 4)` IS a claim on task-x.
    pytest.param("# Active Tasks\n\n## task-x (phase 3 of 4)\n- issue: http://z\n", True, 0,
                 id="heading-with-trailing-note-still-matches"),
])
def test_claim_staleness(tmp_path, active_body, merged, code):
    assert _is_stale(tmp_path, active_body, _repo_with_branch, merged=merged) == code


# --- the false positive caught before shipping --------------------------------

@pytest.mark.parametrize("main_moves", [
    # Task registered, worktree created, no commits yet, user abandons it.
    # is-ancestor alone would call this "merged" and refuse — a false positive.
    pytest.param(False, id="never-committed"),
    # The nastier variant: other tasks merged meanwhile, so the untouched
    # branch tip is a strict ancestor of origin/main. Still nothing to record.
    pytest.param(True, id="never-committed-even-if-main-moved"),
])
def test_never_committed_worktree_is_not_stale(tmp_path, main_moves):
    assert _is_stale(tmp_path, CLAIMED, _repo_never_committed, main_moves=main_moves) == 1
