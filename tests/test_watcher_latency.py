"""M3.7c (PyAutoBrain#690): watcher latency — a short tick, an early shift
close, and a `decision-taken` PR refused at PR-open.

The human's rulings of 2026-11-19 (AUTONOMY.md "Shift speed — 2026-11-19"):

- The timer ticks every 60 seconds; a path unit starts the same tick when a
  worker or close-out session touches the kick file after its verdict file.
- S7: a `decision-taken` PR is refused at PR-open from its label alone, with
  no close-out session, no merge slot and no CI read. It keeps its place as
  an earlier PR in the merge order (M3.6j ruling c), and the digest names the
  PRs that waited behind it.
- Early close: with nothing live, nothing startable and no PR still to judge,
  the shift posts its digest on that tick. A paused shift never closes early;
  a task parked on a question does not hold the shift open.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_closeout as tc  # noqa: E402 — the phase-4b and M3.6j fixtures
from test_orchestrator_closeout import GA7, GA8, Agents  # noqa: E402
from test_orchestrator_digest import orch  # noqa: E402

t = tc.t
NOW = t.NOW
SYSTEMD = BRAIN / "bin" / "systemd"


def _at(minutes):
    return NOW + _dt.timedelta(minutes=minutes)


# --- 1. the 60 s timer, the kick path unit and the kick file ---------------------------

def test_the_timer_ticks_every_60_seconds():
    timer = (SYSTEMD / "pyauto-orchestrator.timer").read_text()
    assert "OnUnitActiveSec=1min" in timer and "OnBootSec=1min" in timer
    assert "2min" not in timer


def test_the_path_unit_starts_the_tick_when_the_kick_file_changes():
    unit = (SYSTEMD / "pyauto-orchestrator.path").read_text()
    assert "PathChanged=%S/pyauto/orchestrator.kick" in unit
    assert "Unit=pyauto-orchestrator.service" in unit
    assert "MakeDirectory=yes" in unit
    assert "WantedBy=paths.target" in unit
    assert "/home/" not in unit and "Workspace" not in unit      # a template, no path


def test_kick_path_matches_systemds_state_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert orch.kick_path() == tmp_path / "state" / "pyauto" / "orchestrator.kick"
    monkeypatch.delenv("XDG_STATE_HOME")
    monkeypatch.setenv("HOME", str(tmp_path / "h"))
    assert orch.kick_path() == tmp_path / "h" / ".local" / "state" / "pyauto" / \
        "orchestrator.kick"


def test_worker_env_points_every_session_at_the_kick_file(tmp_path):
    env = orch.worker_env(tmp_path / "leases", base={"XDG_STATE_HOME": str(tmp_path / "s")})
    assert env["PYAUTO_SHIFT_KICK"] == str(tmp_path / "s" / "pyauto" / "orchestrator.kick")


@pytest.mark.parametrize("which", ["worker", "closeout", "update"])
def test_every_session_kicks_the_watcher_after_its_verdict_file(which):
    if which == "worker":
        text = orch.worker_prompt("t1", "draft/x/t1.md", Path("b.md"), Path("leases"))
        marker = "t1.done"
    elif which == "closeout":
        text = orch.closeout_prompt("t1", GA7, "draft/x/t1.md", Path("b.md"), Path("leases"),
                                    ci_until="2026-11-04T09:31:00Z")
        marker = "t1.closeout"
    else:
        text = orch.update_prompt("t1", GA7, "draft/x/t1.md", Path("b.md"), Path("leases"),
                                  [GA8])
        marker = "t1.closeout"
    assert '"$PYAUTO_SHIFT_KICK"' in text
    # The kick comes after the verdict file is written.
    assert text.rindex(marker) < text.rindex('"$PYAUTO_SHIFT_KICK"')
    if which == "worker":
        # The obsolete exit writes `.done` too, and kicks after it.
        obsolete = text.split("- `ok`:", 1)[0]
        assert '"$PYAUTO_SHIFT_KICK"' in obsolete


# --- 2-4. S7: `decision-taken` refused at PR-open from the label -----------------------

def _labelled(states=None, labels=None):
    """`gh pr view` with labels: OPEN unless named; GA7 carries `decision-taken`."""
    labels = {GA7: ["decision-taken"], **(labels or {})}
    base = tc._gh_states(states or {})

    def read(url):
        gh = base(url)
        return None if gh is None else {**gh, "labels": labels.get(url, [])}
    return read


class _Health:
    def __init__(self, word="RUNNING"):
        self.word, self.calls = word, []

    def __call__(self, url):
        self.calls.append(url)
        return self.word


def _ltick(brief, mind, home, sp, minutes, states=None, health=None, poster=None):
    return orch.tick(brief, mind, home=home, now=_at(minutes), spawner=sp, agents=Agents(),
                     health=health or _Health(), pr_state=_labelled(states), poster=poster)


def _keeper(brief, home):
    """A worker still running on another task: holds the shift open, so the
    merge-order wait can be watched over several ticks."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    lease = {"task": "keeper", "prompt": "draft/x/keeper.md", "started": orch._iso(NOW),
             "heartbeat": orch._iso(NOW), "expires": orch._iso(_at(600)), "pid": proc.pid,
             "session_id": None, "worktree": None}
    (orch.slot_dir(brief, home) / "leases" / "keeper.json").write_text(json.dumps(lease))
    return proc


def test_s7_a_decision_taken_pr_is_refused_at_pr_open_with_no_session(tmp_path):
    mind, brief, home, sp = tc._order_shift(tmp_path)
    health = _Health("RUNNING")
    r = _ltick(brief, mind, home, sp, 1, health=health)
    r = r.get("tick", r)
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["closeouts"][GA7]["state"] == "refused"
    assert c["closeouts"][GA7]["why"] == "decision-taken — the human's /prm"
    assert GA7 in r["closeouts"]["refused"]
    assert sp.closeouts == []                          # no close-out session at all
    assert GA7 not in health.calls                     # CI never read for it
    assert tc._slots(brief, home) == {}                # no merge slot
    assert c["pr_labels"][GA7] == ["decision-taken"]
    # It keeps its place as the earlier PR (ruling c): #8 waits behind it.
    assert c["merge_waits"][GA8]["behind"] == [GA7]


def test_s7_an_unreadable_label_waits_and_is_never_assumed_clean(tmp_path):
    mind, brief, home, sp = tc._order_shift(tmp_path)
    proc = _keeper(brief, home)
    try:
        _ltick(brief, mind, home, sp, 1, states={GA7: None})
        c = orch.read_counters(orch.slot_dir(brief, home))
        assert GA7 not in c["closeouts"] and GA7 not in c.get("pr_labels", {})
        assert sp.closeouts == []
    finally:
        proc.kill()


@pytest.mark.parametrize("end", ["MERGED", "CLOSED"])
def test_s7_a_later_pr_waits_behind_the_refused_one_until_github_ends_it(tmp_path, end):
    mind, brief, home, sp = tc._order_shift(tmp_path)
    proc = _keeper(brief, home)
    try:
        for minute in (1, 2, 3):
            _ltick(brief, mind, home, sp, minute)
        c = orch.read_counters(orch.slot_dir(brief, home))
        assert c["merge_waits"][GA8]["behind"] == [GA7]
        assert sp.closeouts == []
        ended = {GA7: (end, "2026-11-04T09:30:00Z" if end == "MERGED" else "")}
        _ltick(brief, mind, home, sp, 31, states=ended)
        c = orch.read_counters(orch.slot_dir(brief, home))
        assert GA8 not in c["merge_waits"]
        assert [(task, pr) for task, pr, _ in sp.closeouts] == [("picked", GA8)]
    finally:
        proc.kill()


def test_s7_the_digest_names_what_waited_behind_a_prm_bound_pr(tmp_path):
    mind, brief, home, sp = tc._order_shift(tmp_path)
    poster = t.Poster()
    _ltick(brief, mind, home, sp, 1, poster=poster)
    slot = orch.slot_dir(brief, home)
    d = (slot / orch.DIGEST_FILE).read_text()
    assert "- autogalaxy: #8 waited behind #7 (/prm-bound: decision-taken)" in d
    assert "1 PR(s) waited behind a /prm-bound PR" in d


def test_the_digest_has_no_waited_line_when_nothing_waited(tmp_path):
    from test_orchestrator_digest import _brief, _digest
    mind, brief, home = t._shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot,
                      orch.read_counters(slot), health=t._health)
    assert "/prm-bound" not in d


# --- 5. early close -------------------------------------------------------------------

class _Spawner(t.FilesSpawner):
    """Workers that finish at once; a launch of a task in `fail` raises."""

    def __init__(self, done, fail=()):
        super().__init__(done=done, proofs={})
        self.fail, self.closeouts = set(fail), []

    def spawn(self, task, prompt_path, lease_dir, **_kw):
        if task in self.fail:
            raise orch.OrchestratorError("launch refused (test)")
        return super().spawn(task, prompt_path, lease_dir)

    def spawn_closeout(self, task, pr_url, prompt_path, lease_dir, **_kw):
        self.closeouts.append((task, pr_url))
        return {"pid": 0, "agent_id": f"co{len(self.closeouts):06d}"}


def _early(tmp_path, done, fail=(), health="FAILED"):
    mind = t._mind(tmp_path / "mind")
    brief = tmp_path / "shift.md"
    brief.write_text(t.BRIEF.format(issue=t.ISSUE, packet=""))
    home = tmp_path / "home"
    sp = _Spawner(done, fail)
    poster = t.Poster()
    run = {"mind": mind, "brief": brief, "home": home, "sp": sp, "poster": poster}

    def tick(minutes, word=health, agents=None):
        return orch.tick(brief, mind, home=home, now=_at(minutes), spawner=sp,
                         agents=agents or Agents(), health=lambda u: word, poster=poster)
    run["tick"] = tick
    first = tick(0)
    assert first.get("action") == "ticked" and "closed_early" not in first, first
    return run


PRS = {"named": tc.PR1 + "\n", "picked": tc.PR2 + "\n"}


def test_early_close_posts_the_digest_on_the_tick_nothing_is_left(tmp_path):
    run = _early(tmp_path, PRS)
    r = run["tick"](1)                       # both PRs CI FAILED: refused, nothing left
    assert r["closed_early"] == "2026-11-04T09:01:00Z"
    slot = orch.slot_dir(run["brief"], run["home"])
    assert (slot / orch.DIGEST_MARKER).exists()
    c = orch.read_counters(slot)
    assert c["closed_early"] == "2026-11-04T09:01:00Z"
    assert len(run["poster"].calls) == 1
    body = run["poster"].calls[0][1]
    assert "Closed early at 2026-11-04T09:01Z; review-at was 2026-11-04T11:30Z" in body
    # The next tick posts nothing more and starts nothing.
    r2 = run["tick"](2)
    assert r2["action"] == "idle" and "closed early" in r2["reason"]
    assert len(run["poster"].calls) == 1
    events = (slot / "events.jsonl").read_text()
    assert "Shift closed early" in events


def test_a_live_worker_keeps_the_shift_open(tmp_path):
    run = _early(tmp_path, PRS)
    proc = _keeper(run["brief"], run["home"])
    try:
        r = run["tick"](1)
        assert "closed_early" not in r and run["poster"].calls == []
    finally:
        proc.kill()


def test_a_running_closeout_keeps_the_shift_open(tmp_path):
    run = _early(tmp_path, PRS, health="HEALTHY")
    r = run["tick"](1)
    assert r["closeouts"]["started"] and "closed_early" not in r
    assert run["poster"].calls == []


def test_a_startable_pick_keeps_the_shift_open(tmp_path):
    run = _early(tmp_path, {"named": tc.PR1 + "\n"}, fail={"picked"})
    r = run["tick"](1)
    assert any(x["task"] == "picked" for x in r["refused"])     # launch failed: retried
    assert "closed_early" not in r and run["poster"].calls == []


def test_a_pr_inside_the_no_checks_grace_keeps_the_shift_open(tmp_path):
    run = _early(tmp_path, PRS, health="NO-CHECKS")
    r = run["tick"](1)
    assert "closed_early" not in r and run["poster"].calls == []
    r = run["tick"](12)                      # the grace has run out: both refused
    assert r["closed_early"] == "2026-11-04T09:12:00Z"


def test_a_paused_shift_never_closes_early(tmp_path):
    run = _early(tmp_path, {"named": "", "picked": ""})
    slot = orch.slot_dir(run["brief"], run["home"])
    c = orch.read_counters(slot)
    c["paused"] = {"by": "someone", "at": "2026-11-04T09:00:30Z"}
    orch._write_counters(slot, c)
    r = run["tick"](1)
    assert "closed_early" not in r and run["poster"].calls == []


def test_a_task_parked_on_a_question_does_not_hold_the_shift_open(tmp_path):
    run = _early(tmp_path, {"named": "question: https://github.com/o/r/issues/5\n",
                            "picked": ""})
    r = run["tick"](1)
    assert r["closed_early"] == "2026-11-04T09:01:00Z"


def test_a_shadow_shift_never_closes_early(tmp_path):
    mind = t._mind(tmp_path / "mind")
    brief = tmp_path / "shift.md"
    brief.write_text(t.BRIEF.format(issue=t.ISSUE, packet="") + "  - shadow: yes\n")
    home = tmp_path / "home"
    poster = t.Poster()
    for minute in (0, 1):
        r = orch.tick(brief, mind, home=home, now=_at(minute), spawner=_Spawner({}),
                      agents=Agents(), health=lambda u: "FAILED", poster=poster)
    assert r["action"] == "shadow" and "closed_early" not in r and poster.calls == []


# --- 6. overlapping ticks -------------------------------------------------------------

def test_a_second_tick_while_the_lock_is_held_does_nothing(tmp_path):
    run = _early(tmp_path, PRS)
    slot = orch.slot_dir(run["brief"], run["home"])
    (slot / orch.LOCK_FILE).write_text(json.dumps({"pid": os.getpid(),
                                                   "at": _at(1).timestamp()}))
    spawned = len(run["sp"].closeouts)
    r = run["tick"](1)
    assert r == {"action": "busy", "reason": "another tick holds the lock"}
    assert run["poster"].calls == [] and len(run["sp"].closeouts) == spawned
    assert not (slot / orch.DIGEST_MARKER).exists()
