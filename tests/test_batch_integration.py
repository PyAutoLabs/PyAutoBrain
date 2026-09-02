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


# --------------------------------------------------------- the merge engine --
import importlib.util  # noqa: E402
import sys  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

#: Loaded standalone, by file location — no `_batch`, no sizing faculty, no
#: `sys.path` surgery. That it imports at all is the first assertion: the merge
#: engine is stdlib-only and knows nothing about the conductor that calls it.
_INTEG_SPEC = importlib.util.spec_from_file_location(
    "_batch_integration_leg_under_test",
    BRAIN / "agents" / "conductors" / "batch" / "_integration.py")
INTEG = importlib.util.module_from_spec(_INTEG_SPEC)
_INTEG_SPEC.loader.exec_module(INTEG)

SLOT = "2026-09-03-pm"
STAMP = "2026-09-03T08:00Z"


def _out(repo: Path, *args: str) -> str:
    got = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                         text=True)
    return got.stdout.strip()


def _seed(origins: Path, main: Path, name: str) -> Path:
    """A repo with `main` and three pushed member heads.

    `feature/alpha` and `feature/beta` both rewrite `a.py`, so each merges
    cleanly onto `origin/main` alone and the SECOND of them collides — the
    merge-order case the whole leg exists to preview. `feature/gamma` touches
    `b.py` only, so it is the clean-alongside case.
    """
    origin = origins / f"{name}.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)],
                   check=True, capture_output=True)
    repo = main / name
    subprocess.run(["git", "clone", str(origin), str(repo)], check=True,
                   capture_output=True)
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("base\n")
    (repo / "b.py").write_text("base\n")
    _git(repo, "add", "a.py", "b.py")
    _git(repo, "commit", "-m", "base")
    _git(repo, "push", "-u", "origin", "main")
    for branch, path, body in (("feature/alpha", "a.py", "alpha"),
                               ("feature/beta", "a.py", "beta"),
                               ("feature/gamma", "b.py", "gamma")):
        _git(repo, "checkout", "-B", branch, "main")
        (repo / path).write_text(body + "\n")
        _git(repo, "add", path)
        _git(repo, "commit", "-m", branch)
        _git(repo, "push", "-u", "origin", branch)
    _git(repo, "checkout", "main")
    return repo


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A throwaway workspace root: `main/` holds the checkouts, `wt/` is where
    task roots go. Both are declared through the same environment variables the
    laptop uses, so nothing here is a special path this module invented."""
    origins, main, wt = tmp_path / "origins", tmp_path / "main", tmp_path / "wt"
    origins.mkdir()
    main.mkdir()
    (main / "some_workspace").mkdir()   # symlinked into the root, not a worktree
    monkeypatch.setenv("PYAUTO_ROOT", str(main))
    monkeypatch.setenv("PYAUTO_MAIN", str(main))
    monkeypatch.setenv("PYAUTO_WT_ROOT", str(wt))
    monkeypatch.delenv("PYAUTO_WT_BRANCH", raising=False)
    return SimpleNamespace(main=main, wt=wt, root=wt / f"integration-{SLOT}",
                           seed=lambda name: _seed(origins, main, name))


def member(slug: str, branch: str, repo: str = "MyRepo", **over) -> dict:
    """A scored member, cut down to what `plan_jobs` reads."""
    row = {"repo": f"Example/{repo}", "number": 7, "state": "OPEN",
           "merged": False, "head_ref": branch, "head_sha": "",
           "head_repo": f"Example/{repo}"}
    row.update(over)
    return {"slug": slug, "prs": [row]}


def test_two_members_merge_in_dispatch_order_and_the_conflicting_one_is_left_out(ws):
    """**The Witness.** Two members rewrote the same file. Each is green on its
    own; the batch is not. The leg answers "how would these resolve at the
    end?" by merging in DISPATCH order and naming the collision — it never
    resolves it, and it never touches the canonical checkout."""
    ws.seed("MyRepo")
    was = _out(ws.main / "MyRepo", "rev-parse", "HEAD")
    block, _notes = INTEG.run(
        [member("alpha", "feature/alpha"), member("beta", "feature/beta")],
        ["alpha", "beta"], SLOT, lane="local-dev")

    r = block["repos"][0]
    assert r["status"] == "conflicted"
    assert r["merged"] == ["alpha"]
    assert r["conflicts"] == [{"member": "beta", "branch": "feature/beta",
                               "paths": ["a.py"]}]
    assert r["branch"] == f"integration/{SLOT}"

    wt = Path(r["path"])
    assert (wt / "a.py").read_text() == "alpha\n"       # the merge of base+alpha
    assert _head(wt) == f"integration/{SLOT}"
    # The abort really aborted: no half-merge is left for the human to find.
    assert _out(wt, "status", "--porcelain") == ""
    assert subprocess.run(["git", "-C", str(wt), "rev-parse", "--verify",
                           "MERGE_HEAD"], capture_output=True).returncode != 0

    # The canonical checkout is untouched — same branch, same commit.
    assert _out(ws.main / "MyRepo", "rev-parse", "HEAD") == was
    assert _out(ws.main / "MyRepo", "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_a_clean_repo_reports_clean_and_carries_every_member(ws):
    """Two members that never touch the same file both land, and the branch
    carries one merge commit each — the case the human can actually run."""
    ws.seed("MyRepo")
    block, _notes = INTEG.run(
        [member("alpha", "feature/alpha"), member("gamma", "feature/gamma")],
        ["alpha", "gamma"], SLOT, lane="local-dev")
    r = block["repos"][0]
    assert r["status"] == "clean" and r["conflicts"] == []
    assert r["merged"] == ["alpha", "gamma"]
    wt = Path(r["path"])
    assert (wt / "a.py").read_text() == "alpha\n"
    assert (wt / "b.py").read_text() == "gamma\n"
    assert _out(wt, "rev-list", "--count", "--merges",
                "origin/main..HEAD") == "2"


def test_a_re_run_reproduces_the_branch_rather_than_stacking_on_it(ws):
    """The branch is re-cut from `origin/main` every run. The merge result is a
    function of the current base and the current heads, so a second run that
    stacked onto the first would preview a base that no longer exists."""
    ws.seed("MyRepo")
    args = ([member("alpha", "feature/alpha"), member("gamma", "feature/gamma")],
            ["alpha", "gamma"], SLOT)
    first, _n = INTEG.run(*args, lane="local-dev")
    wt = Path(first["repos"][0]["path"])
    tree = _out(wt, "rev-parse", "HEAD^{tree}")
    count = _out(wt, "rev-list", "--count", "origin/main..HEAD")

    second, _n = INTEG.run(*args, lane="local-dev")
    assert second["repos"][0]["status"] == "clean"
    assert _out(wt, "rev-parse", "HEAD^{tree}") == tree
    assert _out(wt, "rev-list", "--count", "origin/main..HEAD") == count


def test_a_dirty_integration_worktree_is_left_alone(ws):
    """The refusal that makes re-cutting the branch safe at all. The one thing
    a re-cut could destroy is a human's uncommitted experiment inside the
    review root — so it is not re-cut, and the report says why."""
    ws.seed("MyRepo")
    first, _n = INTEG.run([member("alpha", "feature/alpha")], ["alpha"], SLOT,
                          lane="local-dev")
    wt = Path(first["repos"][0]["path"])
    (wt / "scratch.py").write_text("the human was mid-experiment\n")

    block, notes = INTEG.run([member("gamma", "feature/gamma")], ["gamma"],
                             SLOT, lane="local-dev")
    r = block["repos"][0]
    assert r["status"] == "skipped"
    assert "uncommitted" in r["note"]
    assert any("uncommitted" in n for n in notes)
    assert (wt / "scratch.py").read_text() == "the human was mid-experiment\n"
    assert (wt / "b.py").read_text() == "base\n"     # gamma was NOT merged in


def test_a_fork_head_a_merged_pr_and_a_missing_head_ref_are_reported_not_merged(ws):
    """Three heads that cannot honestly be merged, three notes, zero merges. A
    fork's head is not on `origin` at all; a merged PR is history; a PR with no
    `head_ref` was scored from evidence gathered before Phase 1 widened the
    field list, and guessing a branch name is how a preview becomes a lie."""
    ws.seed("MyRepo")
    block, notes = INTEG.run(
        [member("forked", "feature/alpha", head_repo="Someone/MyRepo"),
         member("landed", "feature/beta", merged=True),
         member("blind", "")],
        ["forked", "landed", "blind"], SLOT, lane="local-dev")
    assert block is None
    joined = "\n".join(notes)
    assert "is from a fork (Someone/MyRepo)" in joined
    assert "is already merged — not re-merged" in joined
    assert "has no head_ref in the evidence" in joined
    assert not ws.root.exists()


def test_the_worktree_root_carries_activate_sh_and_the_symlinks(ws):
    """The root is built by `bin/worktree.sh`, not re-derived here: its value is
    the layout — the PYTHONPATH, the per-task caches, and the symlink of every
    other top-level entry so relative workspace paths still resolve."""
    ws.seed("MyRepo")
    block, _n = INTEG.run([member("alpha", "feature/alpha")], ["alpha"], SLOT,
                          lane="local-dev")
    root = Path(block["root"])
    assert root == ws.root
    activate = (root / "activate.sh").read_text()
    assert "PYTHONPATH" in activate and "NUMBA_CACHE_DIR" in activate
    assert f'PYAUTO_TASK="integration-{SLOT}"' in activate
    assert block["activate"] == str(root / "activate.sh")
    # A linked worktree's `.git` is a FILE; an untouched entry stays a symlink.
    assert (root / "MyRepo" / ".git").is_file()
    assert (root / "some_workspace").is_symlink()
