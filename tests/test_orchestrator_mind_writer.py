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


def _queue(slot, *argv, mind_repo, worker=False):
    env = {k: v for k, v in os.environ.items() if k != "PYAUTO_SHIFT_WORKER"}
    env.update({"PYAUTO_SHIFT_LEDGER_DIR": str(slot / "ledger"), "PYAUTO_MIND": str(mind_repo)})
    if worker:
        env["PYAUTO_SHIFT_WORKER"] = "1"
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
    res = mw.commit_ledger(slot, canon, "nope")
    assert res["committed"] is None and "not a ledger path" in res["set_aside"][0]["why"]
    assert git(bare, "rev-parse", "main").stdout == head
    assert not mw.pending_ops(slot)


def test_an_op_that_cannot_apply_is_set_aside_and_the_rest_commit(tmp_path, mind):
    """PyAutoBrain#632 (B1): one bad op never strands the others."""
    bare, canon, _ = mind
    slot = tmp_path / "slot"
    assert _queue(slot, "remove", "active/missing.md", mind_repo=canon).returncode == 0
    entry = tmp_path / "e.md"
    entry.write_text("\n## t7\n- issue: x\n")
    assert _queue(slot, "append", "active.md", "--text-file", str(entry),
                  mind_repo=canon).returncode == 0
    (slot / "ledger" / "99999999999999999999-0-junk.json").write_text("{not json")
    res = mw.commit_ledger(slot, canon, "ledger")
    assert res["committed"] and res["ops"] == 1
    assert sorted(a["why"][:6] for a in res["set_aside"]) == ["not JS", "remove"]
    assert "## t7" in _remote_tree(bare, "active.md").stdout
    assert not mw.pending_ops(slot)
    aside = slot / "ledger" / mw.SET_ASIDE_DIR
    assert len(list(aside.glob("*.json"))) == 2 and len(list(aside.glob("*.why"))) == 2
    assert len(git(canon, "worktree", "list").stdout.splitlines()) == 1


def test_a_reapplied_claim_is_a_skipped_note(tmp_path, mind):
    """PyAutoBrain#632 (B1): a move already done and an `active.md` section
    already there are notes, not failures; a section that is new still lands."""
    bare, canon, _ = mind
    slot = tmp_path / "slot"
    _claim_and_close(tmp_path, slot, canon)
    assert mw.commit_ledger(slot, canon, "first")["committed"]
    entry = tmp_path / "again.md"
    entry.write_text("\n## t1\n- issue: again\n\n## t8\n- issue: new\n")
    for argv in (["move", "draft/feature/x/t1.md", "active/t1.md"],
                 ["append", "active.md", "--text-file", str(entry)]):
        assert _queue(slot, *argv, mind_repo=canon).returncode == 0
    res = mw.commit_ledger(slot, canon, "again", own_tasks={"t1"})
    assert res["committed"] and res["set_aside"] == []
    assert res["skipped"] == [
        "move: draft/feature/x/t1.md → active/t1.md is already on main from this shift's "
        "own claim (re-dispatch of t1) — skipped",
        "append: ## t1 already in active.md from this shift's own claim — skipped"]
    active = _remote_tree(bare, "active.md").stdout
    assert active.count("## t1") == 1 and "## t8" in active
    assert [e["kind"] for e in mw.report(slot)] == ["skipped", "skipped"]   # for the digest


@pytest.mark.parametrize("case", ["not-redispatched", "other-content"])
def test_a_claim_already_on_main_from_someone_else_is_a_conflict(tmp_path, mind, case):
    """#632 review (2): a repeat is skipped only for this shift's own
    re-dispatch whose earlier claim it committed and main still matches;
    anything else is a conflict, set aside and reported loudly."""
    bare, canon, other = mind
    slot = tmp_path / "slot"
    _claim_and_close(tmp_path, slot, canon)
    assert mw.commit_ledger(slot, canon, "first")["committed"]
    if case == "other-content":   # another session rewrote the t1 entry since
        git(other, "pull", "-q", "origin", "main")
        (other / "active.md").write_text((other / "active.md").read_text()
                                         .replace("issues/1", "issues/99"))
        git(other, "commit", "-qam", "someone else's t1")
        git(other, "push", "-q", "origin", "HEAD:main")
    entry = tmp_path / "again.md"
    entry.write_text("\n## t1\n- issue: again\n")
    assert _queue(slot, "append", "active.md", "--text-file", str(entry),
                  mind_repo=canon).returncode == 0
    if case == "not-redispatched":
        assert _queue(slot, "move", "draft/feature/x/t1.md", "active/t1.md",
                      mind_repo=canon).returncode == 0
    res = mw.commit_ledger(slot, canon, "again",
                           own_tasks=set() if case == "not-redispatched" else {"t1"})
    assert res["set_aside"] and {a["kind"] for a in res["set_aside"]} == {"conflict"}
    assert all("conflict" in a["why"] for a in res["set_aside"])
    assert _remote_tree(bare, "active.md").stdout.count("## t1") == 1
    import _digest
    assert any("CONFLICT" in ln for ln in _digest.report_lines(slot))


def test_a_watcher_op_is_held_and_retried_never_set_aside(tmp_path, mind):
    """#632 review (1): a critical op (here a stage-2 row whose heading is not
    on main) stays pending and is reported once; the worker op beside it
    commits; once main has the heading the held op lands."""
    bare, canon, other = mind
    slot = tmp_path / "slot"
    row = {"op": "table-append", "path": "autonomy_log.md", "heading": "## Stage 2",
           "row": "| 2026-11-14 | t1 (pr) | slot |", "unique": "| t1 (pr) | slot |"}
    mw.queue_op(slot / "ledger", row)
    mw.queue_op(slot / "ledger", {"op": "append", "path": "active.md",
                                  "text": "\n## t5\n- x\n"})
    for _ in range(2):
        res = mw.commit_ledger(slot, canon, "try")
        assert [h["op"] for h in res["held"]] == ["table-append"] and not res["set_aside"]
        assert len(mw.pending_ops(slot)) == 1
    assert "## t5" in _remote_tree(bare, "active.md").stdout
    assert [e["kind"] for e in mw.report(slot)] == ["held"]           # reported once
    git(other, "pull", "-q", "origin", "main")
    (other / "autonomy_log.md").write_text("# Log\n\n## Stage 2\n\n| a | b | c |\n")
    git(other, "add", "-A")
    git(other, "commit", "-qm", "heading")
    git(other, "push", "-q", "origin", "HEAD:main")
    assert mw.commit_ledger(slot, canon, "now")["committed"] and not mw.pending_ops(slot)
    mw.queue_op(slot / "ledger", row)                                  # re-queued after a crash
    res = mw.commit_ledger(slot, canon, "again")
    assert res["committed"] is None and "already there" in res["skipped"][0]
    assert _remote_tree(bare, "autonomy_log.md").stdout.count("t1 (pr)") == 1


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


# --- M3.6d (PyAutoBrain#660): the edit op, a task's ops land together ----------------

def _push_from(other, path, text, message):
    """Another session changes one Mind file on main."""
    git(other, "pull", "-q", "origin", "main")
    f = other / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    git(other, "add", "-A")
    git(other, "commit", "-qm", message)
    git(other, "push", "-q", "origin", "HEAD:main")


def test_a_write_on_a_path_on_main_is_refused_at_queue_time(tmp_path, mind):
    """Shift 2026-11-16-pm: `write` edits to existing drafts were set aside
    after the worker had ended. Now the worker is told when it queues."""
    bare, canon, _ = mind
    slot = tmp_path / "slot"
    res = _queue(slot, "--task", "t1", "write", "draft/feature/x/t1.md", "--text", "# t1 v2\n",
                 mind_repo=canon, worker=True)
    assert res.returncode == 1, res.stderr
    assert "already exists on Mind origin/main" in res.stderr and "edit" in res.stderr
    assert mw.pending_ops(slot) == []
    # A path a pending op of this shift creates is refused the same way.
    assert _queue(slot, "--task", "t1", "write", "complete/2026/11/t1.md", "--text", "a\n",
                  mind_repo=canon, worker=True).returncode == 0
    res = _queue(slot, "--task", "t1", "write", "complete/2026/11/t1.md", "--text", "b\n",
                 mind_repo=canon, worker=True)
    assert res.returncode == 1 and "edit" in res.stderr
    # An edit whose base is not there, and a table-append with no heading.
    res = _queue(slot, "--task", "t1", "edit", "draft/feature/x/t1.md", "--old", "# nope\n",
                 "--new", "# t1 v2\n", mind_repo=canon, worker=True)
    assert res.returncode == 1 and "expected base" in res.stderr
    res = _queue(slot, "--task", "t1", "table-append", "active.md", "## Calibration runs",
                 "--text", "| a | b |", mind_repo=canon, worker=True)
    assert res.returncode == 1 and "Calibration runs" in res.stderr
    # A shift worker must name its task.
    res = _queue(slot, "append", "active.md", "--text", "\n## t9\n- x\n", mind_repo=canon,
                 worker=True)
    assert res.returncode != 0 and "--task" in res.stderr
    assert len(mw.pending_ops(slot)) == 1


def test_the_edit_op_applies_on_a_matching_base_and_is_set_aside_on_a_moved_one(
        tmp_path, mind):
    bare, canon, other = mind
    slot = tmp_path / "slot"
    for task, path, old, new in (("t1", "draft/feature/x/t1.md", "# t1\n", "# t1\n\nMore.\n"),
                                 ("t2", "active/t2.md", "# t2\n", "# t2 done\n")):
        res = _queue(slot, "--task", task, "edit", path, "--old", old, "--new", new,
                     mind_repo=canon, worker=True)
        assert res.returncode == 0, res.stderr
    # Someone else changes t2's file between the queue and the commit.
    _push_from(other, "active/t2.md", "# t2 by someone else\n", "someone else's t2")
    res = mw.commit_ledger(slot, canon, "edits")
    assert res["committed"] and res["ops"] == 1
    assert _remote_tree(bare, "draft/feature/x/t1.md").stdout == "# t1\n\nMore.\n"
    assert _remote_tree(bare, "active/t2.md").stdout == "# t2 by someone else\n"   # not clobbered
    [aside] = res["set_aside"]
    assert aside["op"] == "edit" and aside["task"] == "t2" and aside["needs"] == "human"
    assert "expected base not found" in aside["why"]
    # The same edit again is already true on main: mechanical, not the human's.
    mw.queue_op(slot / "ledger", {"op": "edit", "path": "draft/feature/x/t1.md", "task": "t1",
                                  "old": "# t1\n", "new": "# t1\n\nMore.\n"})
    res = mw.commit_ledger(slot, canon, "again")
    assert res["committed"] is None and res["set_aside"][0]["needs"] == "mechanical"
    assert _remote_tree(bare, "draft/feature/x/t1.md").stdout == "# t1\n\nMore.\n"


def _close_out_t2(slot, canon):
    for argv in (["write", "complete/2026/11/t2.md", "--text", "## t2\n- completed: x\n"],
                 ["drop-section", "active.md", "t2"]):
        res = _queue(slot, "--task", "t2", *argv, mind_repo=canon, worker=True)
        assert res.returncode == 0, res.stderr


@pytest.mark.parametrize("when", ["same-commit", "earlier-commit"])
def test_a_worker_with_an_op_set_aside_has_its_complete_record_held(tmp_path, mind, when):
    """Shift 2026-11-16-pm: three edits were set aside but the complete/ record
    committed, so Mind recorded the task shipped. Now the record is withheld."""
    bare, canon, other = mind
    slot = tmp_path / "slot"
    assert _queue(slot, "--task", "t2", "edit", "active/t2.md", "--old", "# t2\n", "--new",
                  "# t2 done\n", mind_repo=canon, worker=True).returncode == 0
    _push_from(other, "active/t2.md", "# t2 by someone else\n", "someone else's t2")
    if when == "same-commit":
        _close_out_t2(slot, canon)       # queued after the edit: still applied last
    else:
        first = mw.commit_ledger(slot, canon, "first")
        assert [a["kind"] for a in first["set_aside"]] == ["set-aside"]
        _close_out_t2(slot, canon)
    assert _queue(slot, "--task", "t1", "move", "draft/feature/x/t1.md", "active/t1.md",
                  mind_repo=canon, worker=True).returncode == 0      # another task's op
    res = mw.commit_ledger(slot, canon, "close")
    assert res["committed"]                                          # t1's claim landed
    assert _remote_tree(bare, "active/t1.md").returncode == 0
    assert _remote_tree(bare, "complete/2026/11/t2.md").returncode != 0
    assert "## t2" in _remote_tree(bare, "active.md").stdout
    withheld = [a for a in res["set_aside"] if a["kind"] == "withheld"]
    assert sorted(a["op"] for a in withheld) == ["drop-section", "write"]
    assert all(a["task"] == "t2" and a["needs"] == "human" for a in withheld)
    assert all("held with its task" in a["why"] and "not recorded shipped" in a["why"]
               for a in withheld)
    aside = slot / "ledger" / mw.SET_ASIDE_DIR
    assert len(list(aside.glob("*.json"))) == 3 and not mw.pending_ops(slot)
    import _digest
    assert any("withheld" in ln and "ledger/set_aside/" in ln
               for ln in _digest.report_lines(slot))


AUTONOMY_LOG = """# Autonomy calibration log

Append-only record of `--auto` workflow runs.

## Calibration runs

| date | task | effective level | gates (tests/smoke/review/heart) | outcome |
|------|------|-----------------|----------------------------------|---------|
| 2026-11-13 | a | supervised | ok | merged-unchanged |

| 2026-11-15 | b | supervised | ok | merged-unchanged |

The calibration row goes in the table above, at the end of its last segment.

## Shadow window — the tier-`glance` merge decision

| date | task | human action |
|------|------|--------------|
| 2026-11-01 | s | merged |
"""


def test_shift_ledger_table_append_reaches_the_first_autonomy_log_table(tmp_path, mind):
    """Five workers of shift 2026-11-16-pm could not queue their calibration
    row: `table-append` needs a `## ` heading, and the CLI never set one."""
    bare, canon, other = mind
    _push_from(other, "autonomy_log.md", AUTONOMY_LOG, "log")
    git(canon, "fetch", "-q", "origin")
    slot = tmp_path / "slot"
    row = "| 2026-11-17 | t1 (PR) | supervised | ok | parked |"
    res = _queue(slot, "--task", "t1", "table-append", "autonomy_log.md", "## Calibration runs",
                 "--text", row, mind_repo=canon, worker=True)
    assert res.returncode == 0, res.stderr
    res = mw.commit_ledger(slot, canon, "row")
    assert res["committed"] and not res["set_aside"] and not res["held"]
    lines = _remote_tree(bare, "autonomy_log.md").stdout.splitlines()
    at = lines.index(row)
    assert lines[at - 1].startswith("| 2026-11-15 | b ")
    assert at < lines.index("## Shadow window — the tier-`glance` merge decision")
    # The real Mind log beside this Brain has the heading above its first table.
    live = BRAIN.parent / "PyAutoMind" / "autonomy_log.md"
    if not live.is_file():
        pytest.skip("no PyAutoMind checkout beside this Brain")
    text = live.read_text(encoding="utf-8")
    out = mw.table_append(text, "## Calibration runs", row).splitlines()
    first_table = next(i for i, ln in enumerate(text.splitlines()) if ln.startswith("|"))
    assert text.splitlines().index("## Calibration runs") < first_table
    at = out.index(row)
    assert out[at - 1].startswith("|")
    assert at < next(i for i, ln in enumerate(out) if ln.startswith("## Shadow window"))


def _events_of(slot, ledger):
    import _events
    slot.mkdir(parents=True, exist_ok=True)
    return _events.record_tick(slot, _dt.datetime(2026, 11, 17, 9, 0, tzinfo=_dt.timezone.utc),
                               {"action": "ticked", "ledger": ledger}, counters={})


def test_a_mechanical_set_aside_is_a_digest_line_not_a_needs_you_event(tmp_path, mind):
    bare, canon, _ = mind
    slot = tmp_path / "slot"
    # Already true on main: a remove of a file that is gone, a write of the
    # text the file already has.
    mw.queue_op(slot / "ledger", {"op": "remove", "path": "active/gone.md", "task": "t2"})
    mw.queue_op(slot / "ledger", {"op": "write", "path": "active/t2.md", "text": "# t2\n",
                                  "task": "t2"})
    mw.queue_op(slot / "ledger", {"op": "write", "path": "complete/2026/11/t2.md",
                                  "text": "## t2\n", "task": "t2"})
    res = mw.commit_ledger(slot, canon, "mechanical")
    assert {a["needs"] for a in res["set_aside"]} == {"mechanical"} and len(res["set_aside"]) == 2
    assert _remote_tree(bare, "complete/2026/11/t2.md").stdout == "## t2\n"   # not withheld
    events = _events_of(slot, res)
    assert not [e for e in events if e["needs_you"]], events
    import _digest
    lines = [ln for ln in _digest.report_lines(slot) if ln]
    assert len(lines) == 2 and all("mechanical" in ln and ln.startswith("- note:")
                                   for ln in lines)


def test_two_human_set_asides_for_one_task_are_one_needs_you_event(tmp_path, mind):
    bare, canon, _ = mind
    slot = tmp_path / "slot"
    for path in ("draft/feature/x/t1.md", "active/t2.md"):
        mw.queue_op(slot / "ledger", {"op": "edit", "path": path, "task": "t3",
                                      "old": "# nope\n", "new": "# t3\n"})
    res = mw.commit_ledger(slot, canon, "human")
    assert [a["needs"] for a in res["set_aside"]] == ["human", "human"]
    needs = [e for e in _events_of(slot, res) if e["needs_you"]]
    assert len(needs) == 1 and needs[0]["key"] == "impaired:ledger:task:t3"
    assert "`t3`" in needs[0]["line"] and "2 ops" in needs[0]["line"]
    assert "active/t2.md" in needs[0]["line"] and "draft/feature/x/t1.md" in needs[0]["line"]
