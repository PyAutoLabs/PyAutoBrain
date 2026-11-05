"""`batch watch` (PyAutoBrain#575): a live, read-only view of a running shift.

One group per clause of the prompt's `Witness:`: the view shows every task's
state, pick reason and PR / CI health plus the shift's budgets; `--once` prints
one snapshot; it writes nothing (the slot is byte-identical afterwards); and its
task wording is the digest's own.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
BATCH = BRAIN / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BATCH))
import _brief  # noqa: E402
import _digest  # noqa: E402
import _orchestrator as orch  # noqa: E402
import _watch  # noqa: E402

NOW = _dt.datetime(2026, 11, 4, 9, 30, tzinfo=_dt.timezone.utc)
PR_OPEN = "https://github.com/example-org/example-repo/pull/11"
PR_CLOSING = "https://github.com/example-org/example-repo/pull/12"
PR_MERGED = "https://github.com/example-org/example-repo/pull/13"

BRIEF = """\
# Batch 2026-11-04 am
- dispatched: 2026-11-04T09:00Z
- review-at: 2026-11-04T11:00Z
- issue: https://github.com/example-org/example-mind/issues/9999
- brief:
  - goals:
    - 1. live shift
  - tasks:
    - draft/feature/pyautobrain/named.md
  - backlog: scoped
  - scoped:
    - tiers: notify, glance
  - review-minutes: 30
  - lanes: any local-dev
  - merge-cap: 2
  - token-budget: 5000
  - max-workers: 3
{extra}"""


class Agents:
    def __init__(self, states):
        self.states, self.calls = states, 0

    def state(self, agent_id):
        self.calls += 1
        return self.states.get(agent_id)


def _health(url):
    return {PR_OPEN: "RUNNING"}.get(url, "FAILED")


def _record(tmp_path, extra=""):
    brief = tmp_path / "2026-11-04-am.md"
    brief.write_text(BRIEF.format(extra=extra))
    return brief


def _live_slot(tmp_path) -> Path:
    slot = tmp_path / "home" / "2026-11-04-am"
    (slot / "leases").mkdir(parents=True)
    pick = lambda why, tier="glance": {"prompt": "draft/x.md", "why": why, "tier": tier}  # noqa: E731
    counters = orch.read_counters(slot)
    counters.update({
        "sessions": 4, "tokens": 1234, "crashes": 1, "glance_auto_merges": 1,
        "picks": {"named": pick("named"), "running": pick("scoped tier glance"),
                  "blocked": pick("scoped tier glance"), "pr_open": pick("scoped tier notify", "notify"),
                  "closing": pick("scoped tier glance"), "merged": pick("scoped tier glance"),
                  "parked": pick("scoped tier glance"), "crashed": pick("scoped tier glance")},
        "outcomes": {"pr_open": {"prs": [PR_OPEN], "merged": []},
                     "closing": {"prs": [PR_CLOSING], "merged": []},
                     "merged": {"prs": [PR_MERGED], "merged": [PR_MERGED]}},
        "closeouts": {PR_CLOSING: {"task": "closing", "state": "running"},
                      PR_MERGED: {"task": "merged", "state": "merged", "model": "opus"}},
        "parked": ["parked"], "pending_redispatch": ["crashed"],
        "redispatched": {"running": 1},
    })
    (slot / orch.COUNTERS_FILE).write_text(json.dumps(counters))
    (slot / "leases" / "running.json").write_text(json.dumps(
        {"task": "running", "agent_id": "a1", "started": "2026-11-04T09:05:00Z"}))
    (slot / "leases" / "blocked.json").write_text(json.dumps(
        {"task": "blocked", "agent_id": "a2", "started": "2026-11-04T09:06:00Z",
         "stalled_since": "2026-11-04T09:20:00Z"}))
    (slot / orch.LOG_FILE).write_text("\n".join(json.dumps(
        {"action": "dispatch", "at": f"2026-11-04T09:{m:02d}:00Z", "spawned": ["running"],
         "proposed": [], "reaped": [], "refused": []}) for m in range(0, 30, 3)) + "\n")
    return slot


def _tree_digest(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# --- what it shows ------------------------------------------------------------

def test_live_snapshot_shows_every_task_state_reason_health_and_budget(tmp_path):
    brief, slot = _record(tmp_path), _live_slot(tmp_path)
    agents = Agents({"a1": "working", "a2": "blocked"})
    text = _watch.render(_watch.snapshot(brief, slot, NOW, agents=agents, health=_health))
    assert "Shift 2026-11-04-am — LIVE · 1h 30m left" in text
    assert "- named — not started — glance — why: named in the brief" in text
    assert "- running — running (agent a1, working, since 2026-11-04T09:05:00Z)" in text
    assert "re-dispatched 1×" in text
    assert "- blocked — blocked on a person since 2026-11-04T09:20:00Z" in text
    assert f"- pr_open — {PR_OPEN} — RUNNING — notify — why: scoped tier notify" in text
    assert f"{PR_CLOSING} — close-out running" in text
    assert f"{PR_MERGED} — merged unattended (close-out, opus)" in text
    assert "- parked — parked: awaiting-input" in text
    assert "- crashed — crashed — awaiting re-dispatch" in text
    assert "- workers: 2 live of 3" in text
    assert "- sessions: 4 of 6" in text  # the max-sessions default
    assert "- tokens: 1234 of 5000" in text
    assert "- merges: 1 of 2 (1 unattended)" in text
    assert "- workers crashed: 1" in text
    # The last five ticks only, oldest first.
    assert text.count("dispatch — proposed 0, spawned 1") == 5
    assert "09:27Z dispatch" in text and "09:12Z" not in text


def test_shadow_snapshot_reads_like_the_shadow_digest(tmp_path):
    brief = _record(tmp_path, extra="  - shadow: yes\n")
    slot = tmp_path / "home" / "2026-11-04-am"
    slot.mkdir(parents=True)
    counters = orch.read_counters(slot)
    counters["picks"] = {"a": {"prompt": "draft/a.md", "why": "scoped tier notify",
                               "tier": "notify", "proposed": True}}
    (slot / orch.COUNTERS_FILE).write_text(json.dumps(counters))
    text = _watch.render(_watch.snapshot(brief, slot, NOW, health=_health))
    assert "SHADOW" in text
    assert "- a — proposed (shadow) — notify — why: scoped tier notify" in text
    assert "Last ticks\n  none" in text


def test_no_tick_yet_and_closed_and_stop(tmp_path):
    brief = _record(tmp_path)
    slot = tmp_path / "home" / "2026-11-04-am"
    text = _watch.render(_watch.snapshot(brief, slot, NOW, health=_health))
    assert _watch.NO_TICK in text
    assert not slot.exists()  # looking never creates the slot

    slot = _live_slot(tmp_path)
    (slot / orch.STOP_FILE).write_text("")
    (slot / orch.DIGEST_MARKER).write_text("")
    late = NOW + _dt.timedelta(hours=2)
    text = _watch.render(_watch.snapshot(brief, slot, late, agents=Agents({}), health=_health))
    assert "closed — review-at has passed" in text
    assert "STOP present" in text and "digest posted" in text


def test_before_dispatched_the_header_says_not_yet_open(tmp_path):
    brief = _record(tmp_path)                       # dispatched: 09:00Z
    early = NOW.replace(hour=8, minute=15)
    text = _watch.render(_watch.snapshot(brief, tmp_path / "none", early, health=_health))
    assert "not yet open — opens in 45m" in text


def test_time_left_formats():
    at = NOW + _dt.timedelta(minutes=7)
    assert _watch._time_left(NOW, at) == "7m left"
    assert _watch._time_left(NOW, at + _dt.timedelta(hours=1)) == "1h 07m left"
    assert _watch._time_left(at, NOW).startswith("closed")


# --- read-only ---------------------------------------------------------------

def test_once_writes_nothing_to_the_slot(tmp_path):
    brief, slot = _record(tmp_path), _live_slot(tmp_path)
    before = _tree_digest(tmp_path)
    out = io.StringIO()
    rc = _watch.watch(brief, slot, once=True, out=out, clock=lambda: NOW,
                      agents=Agents({"a1": "working", "a2": "working"}), health=_health)
    assert rc == 0 and "Tasks" in out.getvalue()
    assert _tree_digest(tmp_path) == before


def test_cli_once_through_pyauto_brain(tmp_path):
    brief = _record(tmp_path, extra="  - shadow: yes\n")
    home = tmp_path / "home"
    res = subprocess.run([sys.executable, str(BATCH / "_batch.py"), "watch",
                          "--record", str(brief), "--home", str(home), "--once"],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert "SHADOW" in res.stdout and _watch.NO_TICK in res.stdout
    assert not home.exists()
    res = subprocess.run([sys.executable, str(BATCH / "_batch.py"), "watch"],
                         capture_output=True, text=True)
    assert res.returncode == 2 and "--record" in res.stderr


# --- shared wording ------------------------------------------------------------

def test_digest_and_watch_word_every_task_the_same(tmp_path):
    """With no lease held (as at review-at), each watch line carries the digest
    line's state verbatim."""
    brief, slot = _record(tmp_path), _live_slot(tmp_path)
    for f in (slot / "leases").glob("*.json"):
        f.unlink()
    counters = json.loads((slot / orch.COUNTERS_FILE).read_text())
    counters["pending_redispatch"] = []
    (slot / orch.COUNTERS_FILE).write_text(json.dumps(counters))
    block = _brief.parse(brief.read_text())["brief"]
    digest = _digest.build(block, slot, orch.read_counters(slot), health=_health)
    snap = _watch.snapshot(brief, slot, NOW, health=_health)
    for row in snap["tasks"]:
        assert f"- {row['task']} — {row['state']}" in digest, row


def test_refresh_interval_floor_and_cached_health():
    calls = []
    t = [0.0]
    h = _watch.CachedHealth(30, health=lambda u: calls.append(u) or "RUNNING", clock=lambda: t[0])
    h(PR_OPEN), h(PR_OPEN)
    t[0] = 31
    h(PR_OPEN)
    assert calls == [PR_OPEN, PR_OPEN]

    slept = []

    def sleep(s):
        slept.append(s)
        raise KeyboardInterrupt

    tmp = Path(__import__("tempfile").mkdtemp())
    brief = _record(tmp)
    assert _watch.watch(brief, tmp / "none", interval=1, out=io.StringIO(), sleep=sleep,
                        clock=lambda: NOW, health=_health) == 0
    assert slept == [_watch.MIN_INTERVAL_S]
