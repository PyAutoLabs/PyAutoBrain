"""tests/test_worktree_orphan_guard.py — unregistered on-disk worktrees (#470).

`worktree_check_conflict` reads only the `active.md` registry, so a linked git
worktree that exists on disk but is claimed by no task (an "orphan": a dead
session, a hand-made `git worktree add`, a bundle whose ledger row was pruned)
was invisible to it. Two sessions could then work the same repo with the guard
reporting clear.

The guard now prints a `WARNING:` per unregistered worktree of each requested
repo — exit code unchanged, because a hard conflict would block nearly every
task while historical orphans exist. `worktree_audit_orphans` is the
report-only sweep across every repo; it removes nothing.

Hermetic: synthetic git repos under tmp_path, on the `_run` idiom of
test_worktree_conflict_guard.py. Repo names are synthetic (tenant firewall).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

WORKTREE_SH = Path(__file__).resolve().parents[1] / "bin" / "worktree.sh"


def _git(*args):
    subprocess.run(
        ["git", *map(str, args)], check=True, capture_output=True, text=True
    )


def _repo(main: Path, name: str, *, with_origin: bool = True) -> Path:
    """A flat checkout <main>/<name> with one commit and an origin/main ref."""
    repo = main / name
    repo.mkdir(parents=True)
    _git("init", "-q", "-b", "main", repo)
    _git("-C", repo, "config", "user.email", "test@example.com")
    _git("-C", repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("x\n")
    _git("-C", repo, "add", "README.md")
    _git("-C", repo, "commit", "-q", "-m", "initial")
    if with_origin:
        remote = main.parent / f"{name}.git"
        _git("init", "-q", "--bare", remote)
        _git("-C", repo, "remote", "add", "origin", remote)
        _git("-C", repo, "push", "-q", "-u", "origin", "main")
    return repo


def _worktree(repo: Path, path: Path, branch: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _git("-C", repo, "worktree", "add", "-q", path, "-b", branch)
    _git("-C", path, "config", "user.email", "test@example.com")
    _git("-C", path, "config", "user.name", "Test")
    return path


def _main(tmp_path: Path, active: str | None, parked: str | None = None) -> Path:
    main = tmp_path / "main"
    mind = main / "PyAutoMind"
    mind.mkdir(parents=True)
    if active is not None:
        (mind / "active.md").write_text(active)
    if parked is not None:
        (mind / "parked.md").write_text(parked)
    return main


def _run(tmp_path: Path, snippet: str):
    return subprocess.run(
        ["bash", "-c", f'source "{WORKTREE_SH}"; {snippet}'],
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "PYAUTO_MAIN": str(tmp_path / "main"),
            "PYAUTO_WT_ROOT": str(tmp_path / "wt"),
        },
        capture_output=True,
        text=True,
    )


EMPTY = "# Active Tasks\n"


def _claim(task: str, wt: Path | str, repo: str = "RepoA") -> str:
    return (
        f"## {task}\n- worktree: {wt}\n- repos:\n  - {repo} (feature/{task})\n\n"
    )


def test_unregistered_worktree_warns_but_exit_0(tmp_path):
    main = _main(tmp_path, EMPTY)
    repo = _repo(main, "RepoA")
    ghost = _worktree(repo, tmp_path / "x" / "RepoA", "feature/ghost")

    r = _run(tmp_path, "worktree_check_conflict new-task RepoA")

    assert r.returncode == 0, r.stderr
    assert "WARNING: RepoA has unregistered worktree" in r.stderr
    assert str(ghost) in r.stderr
    assert "feature/ghost" in r.stderr


def test_registered_worktree_no_warning(tmp_path):
    wt = tmp_path / "wt" / "claimed-task" / "RepoA"
    main = _main(tmp_path, "# Active Tasks\n\n" + _claim("claimed-task", wt))
    repo = _repo(main, "RepoA")
    _worktree(repo, wt, "feature/claimed-task")

    r = _run(tmp_path, "worktree_check_conflict claimed-task RepoA")

    assert r.returncode == 0, r.stderr
    assert "WARNING" not in r.stderr


def test_bundle_root_claim_covers_child(tmp_path):
    # Real claims name the bundle root (`~/…-wt/<task>`), with the repo a child.
    main = _main(tmp_path, "# Active Tasks\n\n" + _claim("bundle-task", "~/wt/bundle-task"))
    repo = _repo(main, "RepoA")
    _worktree(repo, tmp_path / "wt" / "bundle-task" / "RepoA", "feature/bundle-task")

    r = _run(tmp_path, "worktree_check_conflict bundle-task RepoA")

    assert r.returncode == 0, r.stderr
    assert "WARNING" not in r.stderr


def test_parked_claim_not_orphan(tmp_path):
    wt = tmp_path / "wt" / "parked-task"
    parked = "# Parked tasks\n\n" + _claim("parked-task", wt)
    main = _main(tmp_path, EMPTY, parked)
    repo = _repo(main, "RepoA")
    _worktree(repo, wt / "RepoA", "feature/parked-task")

    guard = _run(tmp_path, "worktree_check_conflict new-task RepoA")
    audit = _run(tmp_path, "worktree_audit_orphans")

    assert guard.returncode == 0, guard.stderr
    assert "WARNING" not in guard.stderr
    assert audit.returncode == 0, audit.stderr
    assert "ORPHAN" not in audit.stdout
    assert "STALE?" not in audit.stdout  # parked is deliberate, never stale


def test_other_repo_orphan_not_reported(tmp_path):
    main = _main(tmp_path, EMPTY)
    _repo(main, "RepoA")
    repo_b = _repo(main, "RepoB")
    _worktree(repo_b, tmp_path / "x" / "RepoB", "feature/ghost-b")

    r = _run(tmp_path, "worktree_check_conflict new-task RepoA")

    assert r.returncode == 0, r.stderr
    assert "WARNING" not in r.stderr


def test_audit_lists_orphan_with_ahead_behind_dirty(tmp_path):
    main = _main(tmp_path, EMPTY)
    repo = _repo(main, "RepoA")
    ghost = _worktree(repo, tmp_path / "x" / "RepoA", "feature/ghost")
    (ghost / "a.txt").write_text("a\n")
    _git("-C", ghost, "add", "a.txt")
    _git("-C", ghost, "commit", "-q", "-m", "one")
    (ghost / "b.txt").write_text("b\n")
    _git("-C", ghost, "add", "b.txt")
    _git("-C", ghost, "commit", "-q", "-m", "two")
    (ghost / "dirty1.txt").write_text("d\n")
    (ghost / "README.md").write_text("changed\n")

    r = _run(tmp_path, "worktree_audit_orphans")

    assert r.returncode == 0, r.stderr
    rows = [ln.split("\t") for ln in r.stdout.splitlines() if ln.startswith("ORPHAN")]
    assert len(rows) == 1, r.stdout
    row = rows[0]
    assert row[1] == "RepoA"
    assert row[2] == str(ghost)
    assert row[3] == "feature/ghost"
    assert "ahead=2" in row and "behind=0" in row and "dirty=2" in row, row
    assert ghost.is_dir()  # report-only: nothing removed
    assert "nothing removed" in r.stdout


def test_audit_flags_zero_commit_claim(tmp_path):
    busy = tmp_path / "wt" / "busy-task"
    idle = tmp_path / "wt" / "idle-task"
    active = "# Active Tasks\n\n" + _claim("busy-task", busy) + _claim("idle-task", idle, "RepoB")
    main = _main(tmp_path, active)
    repo_a = _repo(main, "RepoA")
    repo_b = _repo(main, "RepoB")
    busy_wt = _worktree(repo_a, busy / "RepoA", "feature/busy-task")
    (busy_wt / "c.txt").write_text("c\n")
    _git("-C", busy_wt, "add", "c.txt")
    _git("-C", busy_wt, "commit", "-q", "-m", "work")
    _worktree(repo_b, idle / "RepoB", "feature/idle-task")

    r = _run(tmp_path, "worktree_audit_orphans")

    assert r.returncode == 0, r.stderr
    stale = [ln.split("\t") for ln in r.stdout.splitlines() if ln.startswith("STALE?")]
    assert len(stale) == 1, r.stdout
    assert stale[0][1] == "idle-task"
    assert stale[0][2] == "RepoB"
    assert "ORPHAN" not in r.stdout


def test_missing_registry_still_fails_closed(tmp_path):
    main = _main(tmp_path, None)
    repo = _repo(main, "RepoA")
    _worktree(repo, tmp_path / "x" / "RepoA", "feature/ghost")

    guard = _run(tmp_path, "worktree_check_conflict new-task RepoA")
    audit = _run(tmp_path, "worktree_audit_orphans")

    assert guard.returncode == 3, guard.stderr
    assert "CANNOT VERIFY" in guard.stderr
    assert "WARNING" not in guard.stderr
    assert audit.returncode == 3, audit.stdout + audit.stderr
    assert "ORPHAN" not in audit.stdout
