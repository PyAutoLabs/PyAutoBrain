"""Autonomous orchestrators phase 3b (PyAutoBrain#557): real dispatch.

Real workers are `claude --bg` sessions started from one session template. In
these tests the `claude` binary is a recorded fake and liveness comes from a
fake `claude agents --json`, so no session is started; the one live check is
opt-in (`PYAUTO_ORCHESTRATOR_LIVE=1`).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

BRAIN = Path(__file__).resolve().parents[1]
BATCH = BRAIN / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BATCH))
import _brief  # noqa: E402
import _digest  # noqa: E402
import _orchestrator as orch  # noqa: E402

NOW = _dt.datetime(2026, 11, 4, 9, 0, tzinfo=_dt.timezone.utc)

BRIEF = """\
# Batch 2026-11-04 am
- dispatched: 2026-11-04T08:30Z
- review-at: 2026-11-04T11:30Z
- brief:
  - goals:
    - 1. sandbox shift
  - tasks:
{tasks}
  - backlog: none
  - review-minutes: 45
  - lanes: any local-dev
  - merge-cap: 0
  - token-budget: {budget}
  - sandbox: yes
{extra}"""

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


def _shift(tmp_path, names=("t1",), budget=100000, extra=""):
    mind = tmp_path / "mind"
    folder = mind / "draft" / "feature" / "pyautobrain"
    folder.mkdir(parents=True)
    for n in names:
        (folder / f"{n}.md").write_text(PROMPT.format(name=n))
    tasks = "\n".join(f"    - draft/feature/pyautobrain/{n}.md" for n in names)
    brief = tmp_path / "shift.md"
    brief.write_text(BRIEF.format(tasks=tasks, budget=budget, extra=extra))
    return mind, brief, tmp_path / "home"


class FakeClaude:
    """Records every `claude --bg` argv; prints a short id like the real CLI."""

    def __init__(self, rc=0):
        self.calls, self.rc = [], rc

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        name = argv[argv.index("--name") + 1] if "--name" in argv else "x"
        out = (f"backgrounded \u00b7 {len(self.calls):08x} \u00b7 {name}\n"
               f"  claude agents             list sessions\n"
               f"  claude stop {len(self.calls):08x}      stop this session\n")
        return SimpleNamespace(returncode=self.rc, stdout="" if self.rc else out,
                               stderr="Workspace not trusted." if self.rc else "")


def _agents(state_by_task: dict, slot: Path) -> orch.AgentsView:
    """A `claude agents --json` view giving each leased task the named state."""
    sessions = []
    for task, lease in orch.leases(slot).items():
        if task in state_by_task and state_by_task[task] != "absent":
            sessions.append({"id": lease["agent_id"],
                             "sessionId": f"{lease['agent_id']}-full-session",
                             "kind": "background", "state": state_by_task[task]})
    return orch.AgentsView(sessions)


def _tick(brief, mind, home, now, claude, agents=None, tokens=lambda s: 0, grace_s=0):
    return orch.tick(brief, mind, home=home, now=now, grace_s=grace_s,
                     spawner=orch.RealSpawner(brief, "auto", run=claude),
                     agents=agents or orch.AgentsView([]), tokens=tokens)


# --- the session template: never bare -------------------------------------------

def test_session_command_is_never_bare(tmp_path):
    argv = orch.session_command("t1", "draft/feature/pyautobrain/t1.md",
                                tmp_path / "shift.md", tmp_path / "leases", "auto")
    assert argv[:2] == ["claude", "--bg"]
    assert argv[argv.index("--name") + 1] == "shift:t1"
    assert "--session-id" not in argv     # --bg assigns its own (CLI 2.1.316)
    assert argv[argv.index("--permission-mode") + 1] == "auto"
    prompt = argv[-1]
    for must in ("Use the start-dev skill. draft/feature/pyautobrain/t1.md --auto",
                 str(tmp_path / "shift.md"),
                 "Never commit to PyAutoMind yourself",
                 str(tmp_path / "leases" / "t1.done"),
                 "Never arm anything that outlives your turn"):
        assert must in prompt, must


def test_bypass_permissions_is_never_a_worker_mode(tmp_path):
    with pytest.raises(orch.OrchestratorError, match="not one of"):
        orch.session_command("t1", "p.md", tmp_path, tmp_path, "bypassPermissions")
    mind, brief, _ = _shift(tmp_path, extra="  - worker-mode: bypassPermissions\n")
    res = _brief.check(brief, mind)
    assert not res["ok"]
    assert any("never a worker mode" in e for e in res["errors"])


def test_default_worker_mode_is_auto_and_overridable():
    assert _brief.worker_mode_of({}) == "auto"
    assert _brief.worker_mode_of({"worker-mode": {"value": "dontAsk"}}) == "dontAsk"


# --- dispatch --------------------------------------------------------------------

def test_real_spawn_records_the_session_in_the_lease(tmp_path):
    mind, brief, home = _shift(tmp_path)
    claude = FakeClaude()
    r = _tick(brief, mind, home, NOW, claude)
    assert [s["task"] for s in r["spawned"]] == ["t1"]
    lease = orch.leases(orch.slot_dir(brief, home))["t1"]
    assert lease["agent_id"] == "00000001" and lease["mode"] == "auto"
    assert lease["pid"] == 0 and lease["session_id"] is None


def test_a_failed_spawn_leaves_no_lease(tmp_path):
    mind, brief, home = _shift(tmp_path)
    with pytest.raises(orch.OrchestratorError, match="claude --bg failed"):
        _tick(brief, mind, home, NOW, FakeClaude(rc=1))
    assert orch.leases(orch.slot_dir(brief, home)) == {}


def test_real_dispatch_no_longer_needs_a_sandbox_brief(tmp_path):
    # 3c (one Mind writer) lifted 3b's fence — human decision 2026-11-03.
    mind, brief, home = _shift(tmp_path)
    brief.write_text(brief.read_text().replace("  - sandbox: yes\n", ""))
    r = _tick(brief, mind, home, NOW, FakeClaude())
    assert [s["task"] for s in r["spawned"]] == ["t1"]


# --- liveness: running, blocked → parked, done, gone ---------------------------------

def test_a_running_worker_keeps_its_lease(tmp_path):
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    claude = FakeClaude()
    _tick(brief, mind, home, NOW, claude)
    later = NOW + _dt.timedelta(minutes=30)
    r = _tick(brief, mind, home, later, claude, agents=_agents({"t1": "running"}, slot))
    assert r["reaped"] == [] and r["spawned"] == [] and r["live"] == ["t1"]
    assert orch.leases(slot)["t1"]["heartbeat"] == orch._iso(later)


def test_a_blocked_worker_is_parked_after_the_grace_and_never_redispatched(tmp_path):
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    claude = FakeClaude()
    _tick(brief, mind, home, NOW, claude)
    blocked = lambda: _agents({"t1": "blocked"}, slot)  # noqa: E731
    r = _tick(brief, mind, home, NOW + _dt.timedelta(minutes=1), claude, agents=blocked())
    assert r["reaped"] == [] and orch.leases(slot)["t1"]["stalled_since"]
    past = NOW + _dt.timedelta(minutes=1, seconds=orch.STALL_GRACE_S)
    r = _tick(brief, mind, home, past, claude, agents=blocked())
    assert r["reaped"][0]["event"] == "parked"
    c = orch.read_counters(slot)
    assert c["parked"] == ["t1"] and c["crashes"] == 0
    r = _tick(brief, mind, home, past + _dt.timedelta(minutes=5), claude)
    assert r["spawned"] == [] and len(claude.calls) == 1   # never killed, never re-sent


def test_a_worker_that_unblocks_clears_its_stall(tmp_path):
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    claude = FakeClaude()
    _tick(brief, mind, home, NOW, claude)
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=1), claude,
          agents=_agents({"t1": "blocked"}, slot))
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=2), claude,
          agents=_agents({"t1": "running"}, slot))
    assert "stalled_since" not in orch.leases(slot)["t1"]


def test_done_with_its_marker_is_released_and_its_tokens_counted(tmp_path):
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    claude = FakeClaude()
    _tick(brief, mind, home, NOW, claude)
    (slot / "leases" / "t1.done").write_text("https://example.invalid/pr/1\n")
    seen = []
    r = _tick(brief, mind, home, NOW + _dt.timedelta(minutes=5), claude,
              agents=_agents({"t1": "done"}, slot),
              tokens=lambda s: seen.append(s) or 1234)
    assert r["reaped"] == [{"task": "t1", "event": "done"}]
    assert seen == ["00000001-full-session"]   # the transcript is named by sessionId
    c = orch.read_counters(slot)
    assert c["done"] == ["t1"] and c["tokens"] == 1234 and c["crashes"] == 0


def test_done_without_its_marker_is_a_crash(tmp_path):
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    claude = FakeClaude()
    _tick(brief, mind, home, NOW, claude)
    r = _tick(brief, mind, home, NOW + _dt.timedelta(minutes=5), claude,
              agents=_agents({"t1": "done"}, slot), tokens=lambda s: 10)
    assert r["reaped"][0]["event"] == "dead"
    assert [s["task"] for s in r["spawned"]] == ["t1"]       # the one re-dispatch
    assert orch.read_counters(slot)["crashes"] == 1


@pytest.mark.parametrize("state", ["failed", "killed", "error"])
def test_an_ended_worker_is_a_crash_at_once_and_redispatched(tmp_path, state):
    """PyAutoBrain#592: systemd killed three workers; `claude agents` said
    `failed` and the watcher read them as alive for 40 minutes."""
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    claude = FakeClaude()
    _tick(brief, mind, home, NOW, claude, grace_s=3600)
    # Well inside the lease grace: an ended session can never write a late .done.
    r = _tick(brief, mind, home, NOW + _dt.timedelta(minutes=3), claude,
              agents=_agents({"t1": state}, slot), tokens=lambda s: 7, grace_s=3600)
    assert r["reaped"] == [{"task": "t1", "event": "dead", "redispatch": "allowed"}]
    assert [s["task"] for s in r["spawned"]] == ["t1"]
    c = orch.read_counters(slot)
    assert c["crashes"] == 1 and c["redispatched"] == {"t1": 1} and c["tokens"] == 7


def test_an_ended_worker_with_its_done_marker_still_counts_as_done(tmp_path):
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    claude = FakeClaude()
    _tick(brief, mind, home, NOW, claude)
    (slot / "leases" / "t1.done").write_text("https://github.com/o/r/pull/5\n")
    r = _tick(brief, mind, home, NOW + _dt.timedelta(minutes=3), claude,
              agents=_agents({"t1": "failed"}, slot))
    assert r["reaped"][0]["event"] == "done"
    assert orch.read_counters(slot)["crashes"] == 0


def test_ended_states_are_the_digests():
    assert orch.ENDED_STATES is _digest.ENDED_STATES and "failed" in orch.ENDED_STATES
    assert "working" not in orch.ENDED_STATES and "blocked" not in orch.ENDED_STATES


def test_the_unit_template_keeps_workers_alive_after_the_tick():
    unit = (BRAIN / "bin" / "systemd" / "pyauto-orchestrator.service").read_text()
    lines = [l.strip() for l in unit.splitlines() if not l.strip().startswith("#")]
    assert "KillMode=process" in lines and "Type=oneshot" in lines


def test_a_vanished_worker_waits_out_the_lease_grace(tmp_path):
    mind, brief, home = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    claude = FakeClaude()
    _tick(brief, mind, home, NOW, claude, grace_s=120)
    gone = lambda: _agents({"t1": "absent"}, slot)  # noqa: E731
    r = _tick(brief, mind, home, NOW + _dt.timedelta(seconds=60), claude, agents=gone(),
              grace_s=120)
    assert r["reaped"] == []
    r = _tick(brief, mind, home, NOW + _dt.timedelta(seconds=200), claude, agents=gone(),
              grace_s=120)
    assert r["reaped"][0]["event"] == "dead"


# --- the token budget -------------------------------------------------------------

def test_a_spent_token_budget_refuses_the_next_spawn(tmp_path):
    mind, brief, home = _shift(tmp_path, names=("t1", "t2"), budget=1000,
                               extra="  - max-workers: 1\n")
    slot = orch.slot_dir(brief, home)
    claude = FakeClaude()
    _tick(brief, mind, home, NOW, claude)
    (slot / "leases" / "t1.done").write_text("")
    r = _tick(brief, mind, home, NOW + _dt.timedelta(minutes=5), claude,
              agents=_agents({"t1": "done"}, slot), tokens=lambda s: 1500)
    assert r["spawned"] == []
    assert r["refused"] == [{"task": "t2", "why": "token-budget 1000 spent (1500)"}]


def test_transcript_tokens_sums_input_output_and_cache_creation(tmp_path):
    sid = str(uuid.uuid4())
    d = tmp_path / "projects" / "-some-project"
    d.mkdir(parents=True)
    lines = [
        {"type": "user", "message": {"role": "user"}},
        {"message": {"usage": {"input_tokens": 10, "output_tokens": 5,
                               "cache_creation_input_tokens": 100,
                               "cache_read_input_tokens": 9999}}},
        {"message": {"usage": {"input_tokens": 1, "output_tokens": 2}}},
        "not json",
    ]
    (d / f"{sid}.jsonl").write_text("\n".join(
        x if isinstance(x, str) else json.dumps(x) for x in lines))
    assert orch.transcript_tokens(sid, root=tmp_path / "projects") == 118


def test_agents_view_reads_the_cli_once(tmp_path):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            [{"id": "a1", "sessionId": "a1-x", "state": "blocked"}, {"id": "a2"}]))
    view = orch.AgentsView(run=run)
    assert view.state("a1") == "blocked"
    assert view.state("a2") == "running"      # a listed session with no state is live
    assert view.state("a3") is None
    assert view.session_of("a1") == "a1-x"
    assert calls == [["claude", "agents", "--json", "--all"]]


def test_brief_validates_sandbox_and_worker_mode(tmp_path):
    mind, brief, _ = _shift(tmp_path, extra="  - worker-mode: dontAsk\n")
    assert _brief.check(brief, mind)["ok"]
    brief.write_text(brief.read_text().replace("sandbox: yes", "sandbox: maybe"))
    assert any(e.startswith("brief.sandbox") for e in _brief.check(brief, mind)["errors"])


# --- the live check (opt-in: starts one real, tiny worker) ------------------------------

def _trusted_root() -> Path:
    """`claude --bg` refuses an untrusted folder (it fails fast, it does not
    stall), so the live worker starts where real ones do: the workspace root."""
    if os.environ.get("PYAUTO_ORCHESTRATOR_LIVE_CWD"):
        return Path(os.environ["PYAUTO_ORCHESTRATOR_LIVE_CWD"])
    sys.path.insert(0, str(BRAIN / "agents"))
    from _pyauto_root import pyauto_root  # noqa: E402
    return pyauto_root()


def test_an_untrusted_folder_fails_the_spawn_fast(tmp_path):
    # Recorded from the CLI (2.1.316): exit 1, "Workspace not trusted". The
    # spawner turns it into an error and leaves no lease — never a silent stall.
    mind, brief, home = _shift(tmp_path)
    untrusted = FakeClaude(rc=1)
    with pytest.raises(orch.OrchestratorError, match="claude --bg failed"):
        _tick(brief, mind, home, NOW, untrusted)
    assert orch.leases(orch.slot_dir(brief, home)) == {}


@pytest.mark.skipif(os.environ.get("PYAUTO_ORCHESTRATOR_LIVE") != "1",
                    reason="starts a real claude --bg session; opt in with "
                           "PYAUTO_ORCHESTRATOR_LIVE=1")
def test_live_sandbox_worker():
    """One real worker on a no-op prompt, launched the way RealSpawner launches:
    its printed id is parsed, `claude agents --json` follows it to `done`,
    `claude logs` reads it (attach's non-interactive twin), and its transcript
    yields a non-zero token count. Removed afterwards."""
    import time
    res = subprocess.run(["claude", "--bg", "--name", "shift:live-witness",
                          "--permission-mode", "auto",
                          "Reply with the single word DONE and stop."],
                         cwd=_trusted_root(), capture_output=True, text=True,
                         timeout=120)
    assert res.returncode == 0, res.stderr
    m = orch._BG_ID_RE.search(res.stdout)
    assert m, res.stdout
    agent = m.group(1)
    states = []
    try:
        deadline = time.time() + 180
        while time.time() < deadline:
            view = orch.AgentsView()
            state = view.state(agent)
            if not states or states[-1] != state:
                states.append(state)
            if state in ("done", "blocked"):
                break
            time.sleep(5)
        print("live states:", states)
        assert states[-1] == "done", states
        logs = subprocess.run(["claude", "logs", agent], capture_output=True,
                              text=True, timeout=60)
        assert logs.returncode == 0
        tokens = orch.transcript_tokens(view.session_of(agent))
        print("live tokens:", tokens)
        assert tokens > 0
    finally:
        subprocess.run(["claude", "stop", agent], capture_output=True, timeout=60)
        subprocess.run(["claude", "rm", agent], capture_output=True, timeout=60)
