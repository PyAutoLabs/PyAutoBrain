"""Autonomous orchestrators phase 3c (PyAutoBrain#559): one Mind writer per shift.

Real git throughout: a bare `PyAutoMind.git` remote, a "canonical" clone the
orchestrator commits through, and a second clone that races it. Workers queue
ops with `bin/shift_ledger.py`; only `commit_ledger` writes to the remote, from
a temporary worktree, and a hook in the worker's environment refuses a direct
Mind commit.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
BATCH = BRAIN / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BATCH))
import _mind_writer as mw  # noqa: E402
import _orchestrator as orch  # noqa: E402

LEDGER_MERGE = BRAIN.parent / "PyAutoMind" / "scripts" / "ledger_merge.py"
if not LEDGER_MERGE.is_file():
    LEDGER_MERGE = Path(os.environ.get("PYAUTO_MIND", "/nonexistent")) / "scripts" / "ledger_merge.py"
pytestmark = pytest.mark.skipif(
    not LEDGER_MERGE.is_file() or shutil.which("git") is None,
    reason="needs git and a PyAutoMind checkout beside this Brain (scripts/ledger_merge.py)")

ACTIVE = """# Active tasks

## t2
- issue: https://example.invalid/issues/2
- prompt: active/t2.md
"""


def git(cwd, *args, env=None, check=True):
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)
    if check:
        assert res.returncode == 0, (args, res.stderr)
    return res


def _identity(repo):
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")


@pytest.fixture
def mind(tmp_path):
    """(bare remote, canonical clone, second clone)."""
    bare = tmp_path / "remote" / "PyAutoMind.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(bare), str(seed))
    _identity(seed)
    (seed / "scripts").mkdir()
    shutil.copy(LEDGER_MERGE, seed / "scripts" / "ledger_merge.py")
    (seed / "active.md").write_text(ACTIVE)
    (seed / "draft" / "feature" / "x").mkdir(parents=True)
    (seed / "draft" / "feature" / "x" / "t1.md").write_text("# t1\n")
    (seed / "active").mkdir()
    (seed / "active" / "t2.md").write_text("# t2\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "seed")
    git(seed, "push", "-q", "origin", "HEAD:main")
    canon = tmp_path / "canon"
    other = tmp_path / "other"
    for c in (canon, other):
        git(tmp_path, "clone", "-q", str(bare), str(c))
        _identity(c)
    # The canonical checkout is shared and may be dirty with someone else's work.
    (canon / "someone_elses_notes.md").write_text("untracked, not ours\n")
    return bare, canon, other


def _queue(slot, *argv, mind_repo):
    env = {**os.environ, "PYAUTO_SHIFT_LEDGER_DIR": str(slot / "ledger"),
           "PYAUTO_MIND": str(mind_repo)}
    return subprocess.run([sys.executable, str(BRAIN / "bin" / "shift_ledger.py"), *argv],
                          capture_output=True, text=True, env=env)


def _claim_and_close(tmp_path, slot, canon):
    """Worker t1 claims its task; worker t2 closes its out."""
    entry = tmp_path / "entry.md"
    entry.write_text("\n## t1\n- issue: https://example.invalid/issues/1\n")
    record = tmp_path / "record.md"
    record.write_text("## t2\n- completed: 2026-11-04\n")
    for argv in (["move", "draft/feature/x/t1.md", "active/t1.md"],
                 ["append", "active.md", "--text-file", str(entry)],
                 ["write", "complete/2026/11/t2.md", "--text-file", str(record)],
                 ["drop-section", "active.md", "t2"],
                 ["remove", "active/t2.md"]):
        res = _queue(slot, *argv, mind_repo=canon)
        assert res.returncode == 0, res.stderr


def _remote_tree(bare, path):
    return git(bare, "show", f"main:{path}", check=False)


def test_two_workers_land_in_one_orchestrator_commit(tmp_path, mind, monkeypatch):
    # Bytecode writing ON, whatever the shell says: CI writes it, and an import
    # of Mind's scripts once left scripts/__pycache__/ in the canonical tree.
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    bare, canon, _ = mind
    slot = tmp_path / "slot"
    before = (git(canon, "status", "--porcelain").stdout, git(canon, "rev-parse", "HEAD").stdout)
    _claim_and_close(tmp_path, slot, canon)
    res = mw.commit_ledger(slot, canon, "shift test: ledger from workers")
    assert res["ops"] == 5 and res["tries"] == 1 and res["committed"]
    log = git(bare, "log", "--format=%s", "main").stdout.splitlines()
    assert log == ["shift test: ledger from workers", "seed"]          # one commit
    assert _remote_tree(bare, "active/t1.md").returncode == 0
    assert _remote_tree(bare, "draft/feature/x/t1.md").returncode != 0
    assert _remote_tree(bare, "active/t2.md").returncode != 0
    assert "completed: 2026-11-04" in _remote_tree(bare, "complete/2026/11/t2.md").stdout
    active = _remote_tree(bare, "active.md").stdout
    assert "## t1" in active and "## t2" not in active
    # The canonical checkout was never touched: same status, same HEAD, and
    # no temporary worktree left registered.
    after = (git(canon, "status", "--porcelain").stdout, git(canon, "rev-parse", "HEAD").stdout)
    assert after == before
    assert len(git(canon, "worktree", "list").stdout.splitlines()) == 1
    assert mw.pending_ops(slot) == []
    assert len(list((slot / "ledger" / "committed").glob("*.json"))) == 5


def test_a_concurrent_commit_is_replayed_over_never_forced(tmp_path, mind, monkeypatch):
    bare, canon, other = mind
    slot = tmp_path / "slot"
    _claim_and_close(tmp_path, slot, canon)
    real_git, raced = mw._git, []

    def racing_git(cwd, *args, check=True):
        if args[:1] == ("push",) and not raced:
            # Someone else moves main between our fetch and our push.
            (other / "planned.md").write_text("# Planned\n")
            git(other, "add", "planned.md")
            git(other, "commit", "-q", "-m", "someone else")
            git(other, "push", "-q", "origin", "HEAD:main")
            raced.append(True)
        assert "--force" not in args and "-f" not in args and "reset" not in args
        return real_git(cwd, *args, check=check)

    monkeypatch.setattr(mw, "_git", racing_git)
    res = mw.commit_ledger(slot, canon, "shift test: ledger from workers")
    assert res["tries"] == 2
    log = git(bare, "log", "--format=%s", "main").stdout.splitlines()
    assert log == ["shift test: ledger from workers", "someone else", "seed"]


def test_a_non_ledger_path_is_refused_before_anything_moves(tmp_path, mind):
    bare, canon, _ = mind
    slot = tmp_path / "slot"
    res = _queue(slot, "write", "scripts/evil.py", "--text", "x", mind_repo=canon)
    assert res.returncode == 1 and "not a ledger path" in res.stderr
    (slot / "ledger").mkdir(parents=True, exist_ok=True)
    (slot / "ledger" / "0-x.json").write_text(json.dumps(
        {"op": "write", "path": ".github/workflows/x.yml", "text": "x"}))
    head = git(bare, "rev-parse", "main").stdout
    with pytest.raises(mw.MindWriteError, match="not a ledger path"):
        mw.commit_ledger(slot, canon, "nope")
    assert git(bare, "rev-parse", "main").stdout == head


def test_an_op_that_cannot_apply_stays_pending(tmp_path, mind):
    bare, canon, _ = mind
    slot = tmp_path / "slot"
    assert _queue(slot, "remove", "active/missing.md", mind_repo=canon).returncode == 0
    head = git(bare, "rev-parse", "main").stdout
    with pytest.raises(mw.MindWriteError, match="does not exist"):
        mw.commit_ledger(slot, canon, "nope")
    assert git(bare, "rev-parse", "main").stdout == head
    assert len(mw.pending_ops(slot)) == 1
    assert len(git(canon, "worktree", "list").stdout.splitlines()) == 1


def test_the_worker_hook_refuses_a_direct_mind_commit(tmp_path, mind):
    _, canon, _ = mind
    env = orch.worker_env(tmp_path / "slot" / "leases", base=dict(os.environ))
    res = git(canon, "commit", "--allow-empty", "-q", "-m", "direct", env=env, check=False)
    assert res.returncode != 0
    assert "never commit to PyAutoMind" in res.stderr and "shift_ledger.py" in res.stderr


def test_the_worker_hook_allows_other_repos_and_chains_their_own_hook(tmp_path):
    repo = tmp_path / "OtherRepo"
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _identity(repo)
    git(repo, "remote", "add", "origin", "https://example.invalid/OtherRepo.git")
    env = orch.worker_env(tmp_path / "slot" / "leases", base=dict(os.environ))
    assert git(repo, "commit", "--allow-empty", "-q", "-m", "ok", env=env,
               check=False).returncode == 0
    own = repo / ".git" / "hooks" / "pre-commit"
    own.write_text("#!/bin/sh\necho repo-own-hook-ran >&2\nexit 1\n")
    own.chmod(0o755)
    res = git(repo, "commit", "--allow-empty", "-q", "-m", "x", env=env, check=False)
    assert res.returncode != 0 and "repo-own-hook-ran" in res.stderr


def test_worker_env_marks_points_and_hooks():
    env = orch.worker_env(Path("/s/leases"), base={"GIT_CONFIG_COUNT": "1",
                                                   "GIT_CONFIG_KEY_0": "a.b",
                                                   "GIT_CONFIG_VALUE_0": "c"})
    assert env["PYAUTO_SHIFT_WORKER"] == "1"
    assert env["PYAUTO_SHIFT_LEDGER_DIR"] == "/s/ledger"
    assert env["GIT_CONFIG_COUNT"] == "2" and env["GIT_CONFIG_KEY_0"] == "a.b"
    assert env["GIT_CONFIG_KEY_1"] == "core.hooksPath"
    assert env["GIT_CONFIG_VALUE_1"] == str(orch.WORKER_HOOKS)


def test_the_module_never_resets_or_forces():
    src = (BATCH / "_mind_writer.py").read_text()
    code = "\n".join(l.split("#")[0] for l in src.splitlines())
    assert '"reset"' not in code and "--force" not in code and '"-f"' not in code


def test_a_tick_commits_what_the_workers_queued(tmp_path, mind):
    bare, canon, _ = mind
    (canon / "draft" / "feature" / "pyautobrain").mkdir(parents=True)
    brief = tmp_path / "shift.md"
    brief.write_text("""\
# Batch 2026-11-04 am
- dispatched: 2026-11-04T08:30Z
- review-at: 2026-11-04T11:30Z
- brief:
  - goals:
    - 1. ledger
  - backlog: none
  - review-minutes: 45
  - lanes: any
  - merge-cap: 0
  - token-budget: 1000
""")
    home = tmp_path / "home"
    slot = orch.slot_dir(brief, home)
    entry = tmp_path / "e.md"
    entry.write_text("\n## t9\n- issue: x\n")
    assert _queue(slot, "append", "active.md", "--text-file", str(entry),
                  mind_repo=canon).returncode == 0
    r = orch.tick(brief, canon, home=home,
                  now=_dt.datetime(2026, 11, 4, 9, 0, tzinfo=_dt.timezone.utc),
                  spawner=orch.FakeSpawner(), records=[])
    assert r["ledger"]["ops"] == 1 and r["ledger"]["committed"]
    assert "## t9" in _remote_tree(bare, "active.md").stdout
