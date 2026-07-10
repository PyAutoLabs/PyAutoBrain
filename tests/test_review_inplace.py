"""In-place (no-worktree) task resolution in the review faculty."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "faculties" / "review"))

import _review  # noqa: E402

ACTIVE = """\
# Active Tasks

## other-task
- worktree: ~/Code/PyAutoLabs-wt/other-task
- repos:
  - PyAutoArray: feature/other-task

## my-inplace-task
- issue: https://example/1
- status: workspace-dev
- worktree: none (in-place)
- repos:
  - repo_a: feature/my-inplace-task
  - repo_b: feature/my-inplace-task

## no-repos-task
- repos:
"""


def make_root(tmp_path, monkeypatch):
    (tmp_path / "PyAutoMind").mkdir()
    (tmp_path / "PyAutoMind" / "active.md").write_text(ACTIVE)
    for name in ("repo_a", "repo_b"):
        subprocess.run(["git", "init", "-q", str(tmp_path / name)], check=True)
    monkeypatch.setenv("PYAUTO_ROOT", str(tmp_path))
    return tmp_path


def test_in_place_repos_reads_only_the_named_tasks_block(tmp_path, monkeypatch):
    root = make_root(tmp_path, monkeypatch)
    repos = _review.in_place_repos("my-inplace-task")
    assert repos == [root / "repo_a", root / "repo_b"]


def test_in_place_repos_skips_missing_checkouts_and_unknown_tasks(tmp_path, monkeypatch):
    make_root(tmp_path, monkeypatch)
    # other-task claims PyAutoArray, which has no checkout under this root.
    assert _review.in_place_repos("other-task") == []
    assert _review.in_place_repos("nonexistent") == []
    assert _review.in_place_repos("no-repos-task") == []


def test_resolve_repos_falls_back_when_no_worktree(tmp_path, monkeypatch):
    root = make_root(tmp_path, monkeypatch)
    monkeypatch.setattr(_review, "WT_BASE", tmp_path / "no-such-wt-base")
    repos = _review.resolve_repos("my-inplace-task", [])
    assert repos == [root / "repo_a", root / "repo_b"]
