"""Autonomous orchestrators phase 3a (PyAutoBrain#555): the shift watcher's core.

A dry shift with fake workers — one test group per clause of the prompt's
`Witness:`: (a) overlapping ticks never double-dispatch, (b) a dead worker is
re-dispatched once per shift, (c) `STOP` is the first read, (d) the usage caps
refuse the N+1th spawn, (e) no open brief dispatches nothing.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
BATCH = BRAIN / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BATCH))
import _orchestrator as orch  # noqa: E402

NOW = _dt.datetime(2026, 11, 4, 9, 0, tzinfo=_dt.timezone.utc)

BRIEF = """\
# Batch 2026-11-04 am
- dispatched: 2026-11-04T08:30Z
- review-at: 2026-11-04T11:30Z
- brief:
  - goals:
    - 1. dry shift
  - tasks:
{tasks}
  - backlog: none
  - review-minutes: 45
  - lanes: any local-dev
  - merge-cap: 0
  - token-budget: 1000
{caps}"""

PROMPT = """\
# {name}

Type: feature
Target: PyAutoBrain
Repos:
- PyAutoBrain
Difficulty: small
Autonomy: supervised
Priority: normal
Status: formalised
Consequence: glance
Witness: a unit test
Review-minutes: 3
Unattended: ready

Body.
"""


def _shift(tmp_path: Path, names=("t1", "t2"), caps="") -> tuple[Path, Path, Path]:
    """(mind, brief, home) for a dry shift naming `names`."""
    mind = tmp_path / "mind"
    folder = mind / "draft" / "feature" / "pyautobrain"
    folder.mkdir(parents=True)
    for n in names:
        (folder / f"{n}.md").write_text(PROMPT.format(name=n))
    tasks = "\n".join(f"    - draft/feature/pyautobrain/{n}.md" for n in names)
    brief = tmp_path / "shift.md"
    brief.write_text(BRIEF.format(tasks=tasks, caps=caps))
    return mind, brief, tmp_path / "home"


def _wait_exit(slot: Path, timeout=10.0):
    """Until every leased fake worker has exited."""
    end = time.time() + timeout
    while time.time() < end:
        if all(not orch._alive(int(l["pid"])) for l in orch.leases(slot).values()):
            return
        time.sleep(0.05)
    raise AssertionError("fake workers did not exit")


# --- (a) overlapping ticks -------------------------------------------------------

def test_overlapping_tick_processes_dispatch_one_worker_per_task(tmp_path):
    mind, brief, home = _shift(tmp_path)
    script = (
        "import sys, datetime as d\n"
        f"sys.path[:0] = [{str(BRAIN / 'agents' / 'faculties' / 'sizing')!r}, {str(BATCH)!r}]\n"
        "import _orchestrator as o\n"
        "now = d.datetime(2026, 11, 4, 9, 0, tzinfo=d.timezone.utc)\n"
        f"r = o.tick({str(brief)!r}, o.Path({str(mind)!r}), home=o.Path({str(home)!r}),"
        " now=now, spawner=o.FakeSpawner(seconds=3))\n"
        "print(len(r.get('spawned', [])))\n")
    procs = [subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                              text=True) for _ in range(4)]
    spawned = sum(int(p.communicate(timeout=60)[0].strip() or 0) for p in procs)
    slot = orch.slot_dir(brief, home)
    assert spawned == 2
    assert sorted(orch.leases(slot)) == ["t1", "t2"]
    assert orch.read_counters(slot)["sessions"] == 2


def test_a_held_lock_makes_the_second_tick_back_off(tmp_path):
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    slot.mkdir(parents=True)
    (slot / orch.LOCK_FILE).write_text(json.dumps({"pid": os.getpid(),
                                                   "at": NOW.timestamp()}))
    assert orch.tick(brief, mind, home=home, now=NOW,
                     spawner=orch.FakeSpawner())["action"] == "busy"


def test_an_existing_lease_is_never_spawned_twice(tmp_path):
    mind, brief, home = _shift(tmp_path)
    first = orch.tick(brief, mind, home=home, now=NOW,
                      spawner=orch.FakeSpawner(seconds=3))
    second = orch.tick(brief, mind, home=home, now=NOW,
                       spawner=orch.FakeSpawner(seconds=3))
    assert len(first["spawned"]) == 2 and second["spawned"] == []


# --- (b) crash recovery ----------------------------------------------------------

def test_a_dead_worker_is_redispatched_once_then_abandoned(tmp_path):
    mind, brief, home = _shift(tmp_path, names=("t1",))
    slot = orch.slot_dir(brief, home)
    crashy = orch.FakeSpawner(seconds=0.05, crash={"t1"})
    later = lambda s: NOW + _dt.timedelta(seconds=s)  # noqa: E731

    assert [s["task"] for s in orch.tick(brief, mind, home=home, now=NOW,
                                         spawner=crashy, grace_s=0)["spawned"]] == ["t1"]
    _wait_exit(slot)
    r = orch.tick(brief, mind, home=home, now=later(1), spawner=crashy, grace_s=0)
    assert r["reaped"] == [{"task": "t1", "event": "dead", "redispatch": "allowed"}]
    assert [s["task"] for s in r["spawned"]] == ["t1"]          # the one re-dispatch
    _wait_exit(slot)
    r = orch.tick(brief, mind, home=home, now=later(2), spawner=crashy, grace_s=0)
    assert r["reaped"][0]["redispatch"] == "spent — abandoned"
    assert r["spawned"] == []
    c = orch.read_counters(slot)
    assert c["crashes"] == 2 and c["redispatched"] == {"t1": 1}
    assert c["abandoned"] == ["t1"] and c["sessions"] == 2


def test_a_dead_lease_waits_out_its_grace(tmp_path):
    mind, brief, home = _shift(tmp_path, names=("t1",))
    slot = orch.slot_dir(brief, home)
    crashy = orch.FakeSpawner(seconds=0.05, crash={"t1"})
    orch.tick(brief, mind, home=home, now=NOW, spawner=crashy, grace_s=60)
    _wait_exit(slot)
    r = orch.tick(brief, mind, home=home, now=NOW + _dt.timedelta(seconds=30),
                  spawner=crashy, grace_s=60)
    assert r["reaped"] == [] and r["spawned"] == []           # still inside the grace


def test_a_finished_worker_is_released_and_never_redispatched(tmp_path):
    mind, brief, home = _shift(tmp_path, names=("t1",))
    slot = orch.slot_dir(brief, home)
    orch.tick(brief, mind, home=home, now=NOW, spawner=orch.FakeSpawner(seconds=0.05))
    _wait_exit(slot)
    r = orch.tick(brief, mind, home=home, now=NOW + _dt.timedelta(seconds=5),
                  spawner=orch.FakeSpawner(seconds=0.05), grace_s=0)
    assert r["reaped"] == [{"task": "t1", "event": "done"}] and r["spawned"] == []
    assert orch.read_counters(slot)["done"] == ["t1"]


# --- (c) the kill switch -----------------------------------------------------------

def test_stop_is_read_before_anything_else(tmp_path):
    home = tmp_path / "home"
    missing_brief = tmp_path / "never_written.md"   # reading it would raise
    slot = orch.slot_dir(missing_brief, home)
    slot.mkdir(parents=True)
    (slot / orch.STOP_FILE).write_text("")
    r = orch.tick(missing_brief, tmp_path / "no_mind", home=home, now=NOW,
                  spawner=orch.FakeSpawner())
    assert r == {"action": "stopped", "reason": "STOP present"}
    assert sorted(p.name for p in slot.iterdir()) == ["STOP"]


def test_stop_halts_a_running_shift_at_the_next_tick(tmp_path):
    mind, brief, home = _shift(tmp_path, names=("t1", "t2"), caps="  - max-workers: 1\n")
    slot = orch.slot_dir(brief, home)
    orch.tick(brief, mind, home=home, now=NOW, spawner=orch.FakeSpawner(seconds=3))
    (slot / orch.STOP_FILE).write_text("")
    assert orch.tick(brief, mind, home=home, now=NOW,
                     spawner=orch.FakeSpawner())["action"] == "stopped"
    assert orch.read_counters(slot)["sessions"] == 1


# --- (d) usage caps ---------------------------------------------------------------

def test_max_workers_refuses_the_next_spawn(tmp_path):
    mind, brief, home = _shift(tmp_path, names=("t1", "t2", "t3"))
    r = orch.tick(brief, mind, home=home, now=NOW, spawner=orch.FakeSpawner(seconds=3))
    assert len(r["spawned"]) == 2
    assert r["refused"] == [{"task": "t3", "why": "max-workers 2 reached"}]


def test_max_sessions_refuses_past_the_shift_total(tmp_path):
    mind, brief, home = _shift(tmp_path, names=("t1", "t2"),
                               caps="  - max-workers: 5\n  - max-sessions: 1\n")
    r = orch.tick(brief, mind, home=home, now=NOW, spawner=orch.FakeSpawner(seconds=3))
    assert len(r["spawned"]) == 1
    assert r["refused"][0]["why"] == "max-sessions 1 reached"
    slot = orch.slot_dir(brief, home)
    assert orch.read_counters(slot)["refusals"][0]["why"] == "max-sessions 1 reached"


def test_a_cap_that_is_not_a_number_refuses_the_brief(tmp_path):
    mind, brief, home = _shift(tmp_path, caps="  - max-workers: lots\n")
    r = orch.tick(brief, mind, home=home, now=NOW, spawner=orch.FakeSpawner())
    assert r["action"] == "idle" and "brief.max-workers" in r["reason"]


# --- (e) no open brief --------------------------------------------------------------

def test_a_brief_past_review_at_dispatches_nothing(tmp_path):
    mind, brief, home = _shift(tmp_path)
    r = orch.tick(brief, mind, home=home, now=NOW + _dt.timedelta(hours=3),
                  spawner=orch.FakeSpawner())
    assert r["action"] == "idle" and "has passed" in r["reason"]
    assert not (orch.slot_dir(brief, home) / "leases").exists()


def test_a_brief_before_dispatched_is_not_yet_open(tmp_path):
    """Landing a brief early grants nothing until its `dispatched:` (#589)."""
    mind, brief, home = _shift(tmp_path)
    early = NOW.replace(hour=8, minute=0)          # dispatched: 08:30Z
    r = orch.tick(brief, mind, home=home, now=early, spawner=orch.FakeSpawner())
    assert r["action"] == "idle" and r["reason"].startswith("not yet open")
    assert "2026-11-04T08:30Z" in r["reason"]
    assert not orch.slot_dir(brief, home).exists()  # nothing touched
    on_time = NOW.replace(hour=8, minute=30)
    r = orch.tick(brief, mind, home=home, now=on_time, spawner=orch.FakeSpawner())
    assert r["action"] != "idle"
    assert orch.slot_dir(brief, home).exists()


def test_a_refused_brief_dispatches_nothing(tmp_path):
    mind, brief, home = _shift(tmp_path)
    brief.write_text(brief.read_text().replace("- review-at: 2026-11-04T11:30Z\n", ""))
    r = orch.tick(brief, mind, home=home, now=NOW, spawner=orch.FakeSpawner())
    assert r["action"] == "idle" and "review-at: missing" in r["reason"]


# --- fake mode only, and the entry --------------------------------------------------

def test_without_the_fake_flag_the_spawner_is_real(tmp_path, monkeypatch):
    # No tick here: since 3c lifted the sandbox fence a tick would start a real
    # `claude --bg`. The choice of spawner is what this pins.
    monkeypatch.delenv(orch.FAKE_ENV, raising=False)
    sp = orch.default_spawner(tmp_path / "shift.md", {"worker-mode": {"value": "dontAsk"}})
    assert isinstance(sp, orch.RealSpawner) and sp.mode == "dontAsk"
    monkeypatch.setenv(orch.FAKE_ENV, "1")
    assert isinstance(orch.default_spawner(tmp_path / "shift.md", {}), orch.FakeSpawner)


def test_home_comes_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(orch.HOME_ENV, str(tmp_path / "h"))
    assert orch.slot_dir(Path("batches/2026-11-04-am.md")) == tmp_path / "h" / "2026-11-04-am"


def test_entry_script_runs_one_idle_tick(tmp_path):
    mind, brief, home = _shift(tmp_path)
    brief.write_text(brief.read_text().replace("2026-11-04T", "2020-01-01T"))
    out = subprocess.run(
        [sys.executable, str(BRAIN / "bin" / "orchestrator_watch.py"), "--brief",
         str(brief), "--mind", str(mind), "--home", str(home), "--json"],
        capture_output=True, text=True, env={**os.environ, orch.FAKE_ENV: "1"})
    assert out.returncode == 0, out.stderr
    # Real time is long past this brief's review-at, so the tick is idle.
    assert json.loads(out.stdout)["action"] == "idle"
