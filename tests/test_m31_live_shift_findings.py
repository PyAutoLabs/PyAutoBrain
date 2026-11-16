"""PyAutoBrain#637: fixes from the M3.1 live shifts of 2026-11-14 (pm2 + pm3).

One offline test per item; each fails on 421ef0f.

1. A killed worker is re-dispatched even when dips used every session (+1).
2. Killed and never re-dispatched reads as crashed, with the reason.
3. A task an earlier shift parked on a question is not picked again.
4. A task whose repo a claim on Mind origin/main holds is skipped.
5. A review-minutes-actual pushed through a linked worktree counts at once.
6. `backlog: scoped` reaches beyond queue.md only for small single-repo tasks.
7. A shift never dips a draft targeting Brain, Mind or Hands.
8. The token reservation holds a finished worker's measured spend.
9. A bare `pr:` key in an active.md row is refused.
10. A merged close-out removes the worktree or says why not.
11. An in-turn merge retires the task's queue.md entry.
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_dispatch as d  # noqa: E402 — the real-spawner fixtures
import test_worktree_claim_guard as g  # noqa: E402 — the worktree.sh fixtures
from test_orchestrator_dispatch import _brief, _digest, orch  # noqa: E402
import _batch  # noqa: E402
import _mind_writer as mw  # noqa: E402

NOW = d.NOW
PR = "https://github.com/example-org/repo/pull/7"
QUESTION = "https://github.com/example-org/repo/issues/9"


def _later(minutes):
    return NOW + _dt.timedelta(minutes=minutes)


def git(cwd, *args):
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert res.returncode == 0, (args, res.stderr)
    return res.stdout.strip()


def _commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-q",
        "-m", msg)


PROMPT = """\
# {name}

Type: docs
Target: {target}
Repos:
{repos}
Difficulty: {size}
Autonomy: safe
Priority: normal
Status: draft
Consequence: notify
Witness: a unit test
Review-minutes: 3
Unattended: ready
Lane: any

Body.
"""

SHIFT = """\
# Batch 2026-11-04 am
- dispatched: 2026-11-04T08:30Z
- review-at: 2026-11-04T11:30Z
- brief:
  - goals:
    - 1. a shift
  - tasks:
{tasks}
  - backlog: {backlog}
{scoped}  - review-minutes: 45
  - lanes: any local-dev
  - merge-cap: 0
  - token-budget: {budget}
  - max-workers: {workers}
  - max-sessions: {sessions}
"""


def _write(mind: Path, name: str, *, target="PyAutoHeart", repos=("PyAutoHeart",),
           size="small", folder="draft/docs/x") -> str:
    f = mind / folder / f"{name}.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(PROMPT.format(name=name, target=target, size=size,
                               repos="\n".join(f"- {r}" for r in repos)))
    return f"{folder}/{name}.md"


def _shift(tmp_path, named=(), *, backlog="none", scoped="", queue=("draft/docs/x/elsewhere.md",),
           budget=100000, workers=2, sessions=6, name="shift.md"):
    mind = tmp_path / "mind"
    mind.mkdir(exist_ok=True)
    (mind / "queue.md").write_text(
        "# Queue\n\n" + "".join(f"## {i}. q\n- kind: prompt\n- ref: {q}\n\n"
                                for i, q in enumerate(queue, 1)))
    tasks = "\n".join(f"    - {t}" for t in named) or "    - draft/docs/x/none.md"
    brief = tmp_path / name
    brief.write_text(SHIFT.format(tasks=tasks, backlog=backlog, scoped=scoped, budget=budget,
                                  workers=workers, sessions=sessions))
    return mind, brief, tmp_path / "home"


def _rec(mind, path):
    return _batch.grade(mind / path, mind) | {"epic": "", "phase": float("inf"),
                                              "done": False, "themes": [], "title": path,
                                              "looks_shipped": False}


# --- 1. the re-dispatch reserve ---------------------------------------------------

def test_1_a_killed_worker_is_redispatched_after_dips_used_every_session(tmp_path):
    mind, brief, home = d._shift(tmp_path, names=("t1", "t2", "t3"),
                                 extra="  - max-workers: 2\n  - max-sessions: 2\n")
    slot = orch.slot_dir(brief, home)
    claude = d.FakeClaude()
    r = d._tick(brief, mind, home, NOW, claude)
    assert [s["task"] for s in r["spawned"]] == ["t1", "t2"]     # every session used
    # The human kills t1's worker: the same tick re-dispatches it, one past the cap.
    r = d._tick(brief, mind, home, _later(30), claude,
                agents=d._agents({"t1": "stopped", "t2": "working"}, slot))
    assert [s["task"] for s in r["spawned"]] == ["t1"], r
    c = orch.read_counters(slot)
    assert c["redispatched"] == {"t1": 1} and c["sessions"] == 3
    assert c["pending_redispatch"] == []
    # Never a fresh pick past the cap: t3 waits on max-workers, then on max-sessions.
    r = d._tick(brief, mind, home, _later(60), claude,
                agents=d._agents({"t1": "done", "t2": "done"}, slot))
    assert r["spawned"] == []
    assert {"task": "t3", "why": "max-sessions 2 reached"} in r["refused"]


# --- 2. killed, never re-dispatched ------------------------------------------------

def test_2_killed_and_not_redispatched_reads_as_crashed_with_the_reason():
    counters = {"picks": {"t1": {"title": "One", "prompt": "draft/x/t1.md"}},
                "outcomes": {}, "pending_redispatch": ["t1"],
                "refusals": [{"task": "t1", "class": "max-sessions 4 reached", "count": 9,
                              "at": "2026-11-14T18:00:00Z", "last": "2026-11-14T19:30:00Z",
                              "why": "max-sessions 4 reached"}]}
    line = _digest._line("t1", counters, "notify", lambda u: "?")
    assert line.startswith("- **Crashed — not re-dispatched** — One"), line
    assert "Not started" not in line
    state, _ = _digest.task_state("t1", counters, lambda u: "?")
    assert state.startswith(_digest.NOT_REDISPATCHED)
    assert "max-sessions 4 reached" in state and "2026-11-14T19:30:00Z" in state
    # With no refusal on record, review-at came first.
    counters["refusals"] = []
    assert "review-at" in _digest.task_state("t1", counters, lambda u: "?")[0]


# --- 3. a parked task is not picked again ------------------------------------------

def _earlier_slot(home: Path, counters: dict, name="2026-11-04-aa") -> Path:
    slot = home / name
    slot.mkdir(parents=True)
    (slot / orch.COUNTERS_FILE).write_text(json.dumps(counters))
    return slot


def test_3_a_task_parked_on_a_question_by_an_earlier_shift_is_not_picked(tmp_path):
    mind = tmp_path / "mind"
    p1, p2 = _write(mind, "p1"), _write(mind, "p2")
    _, brief, home = _shift(tmp_path, backlog="fill-idle")
    _earlier_slot(home, {"outcomes": {"p1": {"prs": [], "merged": [], "issues": [QUESTION],
                                             "questions": [QUESTION]}}})
    slot = orch.slot_dir(brief, home)
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert [s["task"] for s in r["spawned"]] == ["p2"], r
    gates = orch.read_counters(slot)["backlog_gates"]
    assert p1 in gates["parked"] and "until answered" in gates["parked"][p1]
    assert any("Parked on a question" in ln for ln in _digest.backlog_gate_lines(
        orch.read_counters(slot)))
    assert p2 not in gates["parked"]
    # Once a later shift finished it (answered), it is startable again.
    _earlier_slot(home, {"outcomes": {"p1": {"prs": [PR], "merged": [], "issues": []}}},
                  name="2026-11-04-ab")
    assert orch.parked_elsewhere(slot) == {}


def test_3_a_malformed_earlier_counters_file_is_no_hold_and_never_a_crash(tmp_path, capsys):
    home = tmp_path / "home"
    _earlier_slot(home, {"outcomes": {"t": None}}, name="2026-11-04-aa")
    _earlier_slot(home, {"outcomes": {"p1": {"questions": [QUESTION]}}}, name="2026-11-04-ab")
    for name, body in (("2026-11-04-ac", []), ("2026-11-04-ad", {"parked": "p2"})):
        (home / name).mkdir()
        (home / name / orch.COUNTERS_FILE).write_text(json.dumps(body))
    slot = home / "shift"
    held = orch.parked_elsewhere(slot)
    assert list(held) == ["p1"]                       # the good file still holds
    err = capsys.readouterr().err
    assert "2026-11-04-aa/counters.json has the wrong shape" in err
    assert "2026-11-04-ac" in err and "2026-11-04-ad" in err
    assert orch.worker_token_estimate(slot, orch.read_counters(slot), 1000) is None


# --- 4. repo claims across shifts ---------------------------------------------------

def test_4_a_task_on_a_repo_claimed_on_origin_is_skipped_unless_coordinated(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("needs git")
    bare, mind = tmp_path / "mind.git", tmp_path / "mind"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(tmp_path, "clone", "-q", str(bare), str(mind))
    paths = [_write(mind, n, repos=(r,)) for n, r in
             (("a1", "PyAutoEyes"), ("a2", "PyAutoPulse"), ("a3", "PyAutoCortex"))]
    (mind / "active.md").write_text(
        "# Active\n\n## earlier-pick\n- status: workspace-dev\n- repos:\n"
        "  - PyAutoEyes: feature/earlier-pick\n- prompt: active/z.md\n\n"
        "## shared-claim\n- repos:\n  - PyAutoPulse (feature/shared)\n"
        "- coordination: human approved sharing this repo\n")
    _commit(mind, "seed")
    git(mind, "push", "-q", "origin", "HEAD:main")
    git(mind, "fetch", "-q", "origin")
    records = [{k: _rec(mind, p)[k] for k in ("path", "repos", "declared_repos")}
               for p in paths]
    kept, out = orch.on_origin(records, mind, own=set())
    assert [r["path"] for r in kept] == [paths[1], paths[2]]
    assert out == {paths[0]: "repo PyAutoEyes claimed by `earlier-pick` in active.md on "
                             "Mind origin/main"}
    # This shift's own pick stays (its re-dispatch).
    kept, mine = orch.on_origin(records, mind, own={"a1"})
    assert len(kept) == 3 and mine == {}
    # A named task the gate kept out says why, never a bare "Not started".
    state, _ = _digest.task_state("a1", {"backlog_gates": {"origin": out}}, lambda u: "?")
    assert state == "not started — skipped: " + out[paths[0]]
    # A repo only mentioned in passing is not a declared one: never a skip.
    mentioned = _write(mind, "a4", repos=("PyAutoCortex",))
    (mind / mentioned).write_text((mind / mentioned).read_text() + "\nSee @PyAutoEyes.\n")
    rec = _rec(mind, mentioned)
    assert "pyautoeyes" in rec["repos"] and "pyautoeyes" not in rec["declared_repos"]
    # An active.md on origin that cannot be read fails closed: no claim
    # check, no pick (its blob is lost from the local object store).
    blob = git(mind, "rev-parse", "origin/main:active.md")
    (mind / ".git" / "objects" / blob[:2] / blob[2:]).unlink()
    kept, closed = orch.on_origin(records, mind, own={"a2"})
    assert [r["path"] for r in kept] == [paths[1]]   # only this shift's own pick
    assert closed[paths[0]].startswith("Mind origin/main:active.md unreadable")
    assert closed[paths[0]].endswith("fail closed")
    line = _digest.backlog_gate_lines({"backlog_gates": {"origin": {
        paths[0]: "repo PyAutoEyes claimed by `earlier-pick` in active.md on Mind origin/main"}}})
    assert any(ln.startswith("Repo claimed on Mind origin/main: 1") for ln in line)


# --- 5. the calibration gate reads the pushed record --------------------------------

def test_5_minutes_pushed_through_a_linked_worktree_count_on_the_next_tick(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("needs git")
    bare, mind = tmp_path / "mind.git", tmp_path / "mind"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(tmp_path, "clone", "-q", str(bare), str(mind))
    (mind / "batches").mkdir()
    prev = "# Batch 2026-11-04 aa\n- dispatched: 2026-11-04T06:00Z\n- review-at: 2026-11-04T08:00Z\n"
    (mind / "batches" / "2026-11-04-aa.md").write_text(prev)
    _commit(mind, "shift A")
    git(mind, "push", "-q", "origin", "HEAD:main")
    # The check-in: the lead pushes the minutes from a linked worktree; the
    # canonical working tree is not fast-forwarded.
    wt = tmp_path / "wt"
    git(mind, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    (wt / "batches" / "2026-11-04-aa.md").write_text(
        prev + "- review-minutes-actual: 5\n")
    _commit(wt, "check-in")
    git(wt, "push", "-q", "origin", "HEAD:main")
    assert "review-minutes-actual" not in (mind / "batches" / "2026-11-04-aa.md").read_text()
    brief = mind / "batches" / "2026-11-04-ab.md"
    brief.write_text(SHIFT.format(tasks="    - draft/docs/x/none.md", backlog="none", scoped="",
                                  budget=1000, workers=1, sessions=1)
                     .replace("2026-11-04T08:30Z", "2026-11-04T09:00Z"))
    errors = _brief.check(brief, mind)["errors"]
    assert not [e for e in errors if "review-minutes-actual" in e], errors
    # And a record that is measured nowhere still refuses.
    (mind / "batches" / "2026-11-04-a0.md").write_text(prev)
    brief2 = mind / "batches" / "2026-11-04-a1.md"
    brief2.write_text(brief.read_text())
    assert any("review-minutes-actual: missing on the previous record 2026-11-04-a0.md" in e
               for e in _brief.check(brief2, mind)["errors"])


# --- 6. backlog reach: queue first, then small single-repo ---------------------------

def test_6_a_scoped_dip_beyond_the_queue_takes_only_small_single_repo_tasks(tmp_path):
    mind = tmp_path / "mind"
    queued = _write(mind, "queued_medium", size="medium", repos=("PyAutoHeart", "PyAutoEyes"))
    small = _write(mind, "small_single")
    medium = _write(mind, "medium_single", size="medium")
    multi = _write(mind, "small_multi", repos=("PyAutoHeart", "PyAutoEyes"))
    _, brief_path, _ = _shift(tmp_path, backlog="scoped", scoped="  - scoped:\n    - tiers: notify\n",
                              queue=(queued,))
    brief = _brief.parse(brief_path.read_text())["brief"]
    records = [_rec(mind, p) for p in (queued, small, medium, multi)]
    d_ = _batch.plan(records, session_lane="local-dev", brief=brief,
                     queue=_batch.read_queue(mind))
    assert sorted(m["path"] for m in d_["members"]) == sorted([queued, small])
    why = dict(d_["rejected"])
    assert "medium, 1 repo(s)" in why[medium] and "ruling 2026-11-16" in why[medium]
    assert "small, 2 repo(s)" in why[multi]
    assert sorted(d_["scoped_reach"]) == sorted([medium, multi])
    # The ruling is recorded once in the doctrine.
    doctrine = (BRAIN / "AUTONOMY.md").read_text()
    assert doctrine.count("Human ruling 2026-11-16 (backlog reach, PyAutoBrain#637)") == 1


# --- 7. organ targets are never dipped ------------------------------------------------

def test_7_a_shift_never_dips_a_draft_targeting_its_own_organs(tmp_path):
    mind = tmp_path / "mind"
    brain = _write(mind, "brain_fix", target="PyAutoBrain", repos=("PyAutoBrain",))
    minds = _write(mind, "mind_fix", target="PyAutoMind", repos=("PyAutoMind",))
    hands = _write(mind, "hands_fix", target="PyAutoHands", repos=("PyAutoHands",))
    heart = _write(mind, "heart_fix")
    named = _write(mind, "named_brain", target="PyAutoBrain", repos=("PyAutoBrain",))
    _, brief_path, _ = _shift(tmp_path, named=(named,), backlog="fill-idle")
    brief = _brief.parse(brief_path.read_text())["brief"]
    records = [_rec(mind, p) for p in (brain, minds, hands, heart, named)]
    d_ = _batch.plan(records, session_lane="local-dev", brief=brief,
                     queue=_batch.read_queue(mind))
    assert sorted(m["path"] for m in d_["members"]) == sorted([heart, named])
    why = dict(d_["rejected"])
    for p, organ in ((brain, "PyAutoBrain"), (minds, "PyAutoMind"), (hands, "PyAutoHands")):
        assert why[p] == (f"targets {organ} — a shift never changes its own watcher, "
                          "writer or release path")


# --- 8. the token cap binds before the session cap when sized to ---------------------

def test_8_the_reservation_holds_a_finished_workers_measured_spend(tmp_path):
    names = ("t1", "t2", "t3", "t4")
    mind, brief, home = d._shift(tmp_path, names=names, budget=400000,
                                 extra="  - max-workers: 4\n  - max-sessions: 4\n")
    # The shift before: two workers finished at ~125k each (shift B's measure).
    _earlier_slot(home, {
        "token_budget": 400000,
        "usage": {"w1": {"kind": "worker", "total": 125000, "final": True},
                  "w2": {"kind": "worker", "total": 126000, "final": True},
                  "w3": {"kind": "worker", "total": 4000, "final": True}},   # killed early
        "workers": [{"key": "w1", "exits": ["spawned", "finished"]},
                    {"key": "w2", "exits": ["spawned", "finished"]},
                    {"key": "w3", "exits": ["spawned", "crashed"]}]})
    slot = orch.slot_dir(brief, home)
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert [s["task"] for s in r["spawned"]] == ["t1", "t2", "t3"]
    assert r["refused"] == [{"task": "t4", "why": "token-budget 400000: 376500 committed + "
                                                  "125500 reserved per worker"}]
    assert orch.worker_token_estimate(slot, orch.read_counters(slot)) == 125500
    # No measure yet: the even share, as before.
    assert orch.default_token_reserve(400000, 4) == 100000
    assert orch.default_token_reserve(400000, 4, 90000) == 100000


def test_8_one_outlier_worker_never_refuses_the_first_spawn(tmp_path):
    """Review of 1ae5d5f: one past worker at 450k in a 400k shift must not
    make the reservation 450k. Clamped to half the budget, the median of
    comparable shifts only (a 2M shift's workers are not counted)."""
    names = ("t1", "t2", "t3")
    mind, brief, home = d._shift(tmp_path, names=names, budget=400000,
                                 extra="  - max-workers: 4\n  - max-sessions: 4\n")
    _earlier_slot(home, {"token_budget": 400000,
                         "usage": {"w1": {"kind": "worker", "total": 450000, "final": True}},
                         "workers": [{"key": "w1", "exits": ["spawned", "finished"]}]})
    _earlier_slot(home, {"token_budget": 2000000,       # not comparable: never read
                         "usage": {"w9": {"kind": "worker", "total": 10, "final": True}},
                         "workers": [{"key": "w9", "exits": ["spawned", "finished"]}]},
                  name="2026-11-04-ab")
    slot = orch.slot_dir(brief, home)
    assert orch.worker_token_estimate(slot, orch.read_counters(slot), 400000) == 450000
    assert orch.default_token_reserve(400000, 4, 450000) == 200000
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert [s["task"] for s in r["spawned"]] == ["t1", "t2"]
    assert r["refused"] == [{"task": "t3", "why": "token-budget 400000: 400000 committed + "
                                                  "200000 reserved per worker"}]
    assert orch.read_counters(slot)["token_budget"] == 400000
    # The median, not the mean: one outlier among three does not move it.
    _earlier_slot(home, {"token_budget": 400000,
                         "usage": {k: {"kind": "worker", "total": 100000, "final": True}
                                   for k in ("a", "b")},
                         "workers": [{"key": k, "exits": ["finished"]} for k in ("a", "b")]},
                  name="2026-11-04-ac")
    assert orch.worker_token_estimate(slot, orch.read_counters(slot), 400000) == 100000


# --- 9. PR keys -------------------------------------------------------------------------

def test_9_a_bare_pr_key_in_an_active_md_row_is_refused():
    lm = SimpleNamespace(is_ledger_path=lambda p: True, ENTRY_MERGED_FILES=("active.md",))
    bad = {"op": "append", "path": "active.md",
           "text": f"\n## t1\n- status: awaiting-merge\n- pr: {PR}\n"}
    errs = mw.validate_op(bad, lm)
    assert errs and "`pr:`" in errs[0] and "library-pr:" in errs[0]
    good = dict(bad, text=f"\n## t1\n- status: awaiting-merge\n- workspace-pr: {PR}\n"
                          f"- library-pr: {PR}\n- pending-release: x@{PR}\n- prompt: active/t1.md\n")
    assert mw.validate_op(good, lm) == []
    # The worker is told the keys up front.
    prompt = orch.worker_prompt("t1", "draft/x/t1.md", Path("b.md"), Path("leases"))
    assert "- library-pr: <url>" in prompt and "bare `pr:`" in prompt


# --- 10. worktree clean-up after an unattended merge ------------------------------------

def test_10_the_stale_claim_guard_counts_a_release_queued_in_the_shift_ledger(tmp_path):
    main = tmp_path / "main"
    (main / "PyAutoMind").mkdir(parents=True)
    (main / "PyAutoMind" / "active.md").write_text(g.CLAIMED)    # stale canonical claim
    wt_root = tmp_path / "wt" / "task-x"
    wt_root.mkdir(parents=True)
    g._repo_with_branch(wt_root, merged=True)
    ledger = tmp_path / "ledger"

    def stale():
        return subprocess.run(
            ["bash", "-c", f'source "{g.WORKTREE_SH}"; worktree_claim_is_stale task-x "{wt_root}"'],
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PYAUTO_MAIN": str(main),
                 "PYAUTO_WT_ROOT": str(tmp_path / "wt"), "PYAUTO_SHIFT_LEDGER_DIR": str(ledger)},
            capture_output=True).returncode
    assert stale() == 0                                       # nothing queued: refuse
    mw.queue_op(ledger, {"op": "drop-section", "path": "active.md", "section": "task-x-2"})
    assert stale() == 0                                       # another task's release
    mw.queue_op(ledger, {"op": "drop-section", "path": "active.md", "section": "task-x"})
    assert stale() == 1                                       # its own release: removable


def test_10_a_merged_closeouts_worktree_cleanup_is_in_the_digest(tmp_path):
    slot = tmp_path / "home" / "shift"
    (slot / "leases").mkdir(parents=True)
    counters = orch.read_counters(slot)
    counters["picks"]["t1"] = {"prompt": "draft/x/t1.md", "tier": "glance", "title": "One"}
    counters["outcomes"]["t1"] = {"prs": [PR], "merged": [], "issues": []}
    counters["closeouts"][PR] = {"task": "t1", "state": "running", "pid": 0}
    (slot / "leases" / "t1.closeout").write_text(json.dumps(
        {"result": "merged", "pr": PR, "gate": "g", "model": "m",
         "cleanup": "worktree kept — dirty repo: repo-a"}))
    orch.reap_closeouts(slot, counters, NOW, orch.AgentsView([]), None)
    assert counters["closeouts"][PR]["cleanup"] == "worktree kept — dirty repo: repo-a"
    state, _ = _digest.task_state("t1", counters, lambda u: "?")
    assert "worktree: worktree kept — dirty repo: repo-a" in state
    # A close-out that said nothing is named too.
    counters["closeouts"][PR] = {"task": "t1", "state": "running", "pid": 0}
    counters["outcomes"]["t1"]["merged"] = []
    (slot / "leases" / "t1.closeout").write_text(json.dumps(
        {"result": "merged", "pr": PR, "gate": "g", "model": "m"}))
    orch.reap_closeouts(slot, counters, NOW, orch.AgentsView([]), None)
    assert counters["closeouts"][PR]["cleanup"] == orch.CLEANUP_UNREPORTED
    assert "worktree_remove" in (BRAIN / "agents" / "conductors" / "batch"
                                 / "closeout_template.md").read_text()


# --- 11. an in-turn merge retires its queue.md entry ------------------------------------

def test_11_an_in_turn_merge_queues_the_queue_retirement(tmp_path):
    slot = tmp_path / "home" / "shift"
    (slot / "leases").mkdir(parents=True)
    counters = orch.read_counters(slot)
    counters["picks"]["t1"] = {"prompt": "draft/x/t1.md", "tier": "notify"}
    (slot / "leases" / "t1.json").write_text(json.dumps(
        {"task": "t1", "prompt": "draft/x/t1.md", "pid": 0, "started": orch._iso(NOW),
         "expires": orch._iso(NOW)}))
    (slot / "leases" / "t1.done").write_text(f"merged {PR}\n")
    events = orch._reap(slot, counters, _later(5), 0, orch.AgentsView([]))
    assert events == [{"task": "t1", "event": "done"}]
    ops = [json.loads(f.read_text()) for f in mw.pending_ops(slot)]
    assert [o["op"] for o in ops] == ["queue-retire"]
    assert ops[0]["prompt"] == "t1.md" and PR in ops[0]["shipped_as"]
    assert "in-turn" in ops[0]["shipped_as"]
