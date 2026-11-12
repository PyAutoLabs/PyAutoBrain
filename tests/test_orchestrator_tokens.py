"""PyAutoBrain#610 (M1.5) Witness (1) and (2): a shift's tokens are right.

Usage is read on every tick for every live, parked and close-out session and
stored per session — replaced, never added; a transcript repeating one message
id counts it once; an unreadable usage refuses the next spawn and is never
counted as 0; and a per-worker reservation makes the token budget bind on the
first tick. Real workers are `claude --bg` stand-ins (no session is started).
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
import uuid
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_dispatch as d  # noqa: E402 — the 3b fixtures
from test_orchestrator_dispatch import orch  # noqa: E402
import test_orchestrator_closeout as co  # noqa: E402 — the 4b fixtures

NOW = d.NOW
USAGE = {"input": 100, "output": 20, "cache_creation": 30, "cache_read": 5000, "total": 150}


def _later(minutes):
    return NOW + _dt.timedelta(minutes=minutes)


# --- (1) live, close-out, dedupe, unavailable --------------------------------------

def test_a_live_workers_usage_is_counted_on_the_tick_it_is_read(tmp_path):
    mind, brief, home = d._shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    claude = d.FakeClaude()
    d._tick(brief, mind, home, NOW, claude)
    d._tick(brief, mind, home, _later(1), claude, agents=d._agents({"t1": "working"}, slot),
            tokens=lambda sid: USAGE)
    c = orch.read_counters(slot)
    assert not (slot / "leases" / "t1.done").exists()          # no `.done` yet
    assert c["tokens"] == 150 and c["usage"]["00000001"]["cache_read"] == 5000
    # The next read replaces the last: a session is never added twice.
    d._tick(brief, mind, home, _later(2), claude, agents=d._agents({"t1": "working"}, slot),
            tokens=lambda sid: {**USAGE, "total": 400})
    assert orch.read_counters(slot)["tokens"] == 400


def test_a_parked_workers_usage_keeps_being_read(tmp_path):
    mind, brief, home = d._shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    claude = d.FakeClaude()
    d._tick(brief, mind, home, NOW, claude)
    blocked = lambda: d._agents({"t1": "blocked"}, slot)  # noqa: E731
    d._tick(brief, mind, home, _later(1), claude, agents=blocked(), tokens=lambda s: 10)
    past = _later(1 + orch.STALL_GRACE_S / 60)
    d._tick(brief, mind, home, past, claude, agents=blocked(), tokens=lambda s: 20)
    assert orch.leases(slot)["t1"]["state"] == "parked"
    d._tick(brief, mind, home, past + _dt.timedelta(minutes=5), claude, agents=blocked(),
            tokens=lambda s: 35)
    assert orch.read_counters(slot)["tokens"] == 35


class _SessionAgents(co.Agents):
    def session_of(self, agent_id):
        return f"{agent_id}-session"


def test_a_closeout_sessions_usage_is_added(tmp_path):
    mind, brief, home, sp = co._shift(tmp_path, cap=1)
    slot = orch.slot_dir(brief, home)
    co._tick(brief, mind, home, sp, 1)                        # starts the close-out
    assert sp.closeouts == [("named", co.PR1)]
    orch.tick(brief, mind, home=home, now=co.t.NOW + _dt.timedelta(minutes=2), spawner=sp,
              agents=_SessionAgents(), health=co._health({}),
              tokens=lambda sid: {"total": 77, "input": 70, "output": 7} if sid.startswith("co")
              else None)
    c = orch.read_counters(slot)
    assert c["usage"]["co000001"]["kind"] == "closeout"
    assert c["tokens"] == 77


def test_a_transcript_repeating_one_message_id_counts_it_once(tmp_path):
    sid = str(uuid.uuid4())
    folder = tmp_path / "projects" / "-a-project"
    folder.mkdir(parents=True)
    one = {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 100,
           "cache_read_input_tokens": 900}
    lines = [{"message": {"id": "msg_1", "usage": one}},       # one message, three blocks
             {"message": {"id": "msg_1", "usage": one}},
             {"message": {"id": "msg_1", "usage": one}},
             {"message": {"id": "msg_2", "usage": {"input_tokens": 1, "output_tokens": 2}}},
             {"type": "user", "message": {"role": "user"}}]
    (folder / f"{sid}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    u = orch.transcript_usage(sid, root=tmp_path / "projects")
    assert u == {"input": 11, "output": 7, "cache_creation": 100, "cache_read": 900,
                 "total": 118}
    assert orch.transcript_usage("no-such-session", root=tmp_path / "projects") is None
    assert orch.transcript_tokens("no-such-session", root=tmp_path / "projects") is None


def test_an_unreadable_usage_refuses_the_next_spawn_and_never_adds_zero(tmp_path):
    mind, brief, home = d._shift(tmp_path, names=("t1", "t2"), extra="  - max-workers: 1\n")
    slot = orch.slot_dir(brief, home)
    claude = d.FakeClaude()
    d._tick(brief, mind, home, NOW, claude)
    d._tick(brief, mind, home, _later(1), claude, agents=d._agents({"t1": "working"}, slot),
            tokens=lambda s: 500)
    (slot / "leases" / "t1.done").write_text("https://github.com/o/r/pull/1\n")
    r = d._tick(brief, mind, home, _later(2), claude, agents=d._agents({"t1": "done"}, slot),
                tokens=lambda s: None)
    assert r["spawned"] == []
    assert r["refused"] == [{"task": "t2", "why": "token usage unavailable (00000001)"}]
    c = orch.read_counters(slot)
    assert c["tokens"] == 500                                  # the last read stands
    assert c["usage"]["00000001"]["total"] == 500
    # Once usage can be read again, the spawn goes ahead.
    r = d._tick(brief, mind, home, _later(3), claude, tokens=lambda s: 500)
    assert [s["task"] for s in r["spawned"]] == ["t2"]


# --- (2) the reservation binds on tick one ----------------------------------------

def test_a_spawn_reservation_makes_the_budget_bind_on_tick_one(tmp_path):
    mind, brief, home = d._shift(tmp_path, names=("t1", "t2"), budget=100)
    r = orch.tick(brief, mind, home=home, now=NOW, grace_s=0, token_reserve=60,
                  spawner=orch.RealSpawner(brief, "auto", run=d.FakeClaude()),
                  agents=orch.AgentsView([]), tokens=lambda s: 0)
    assert [s["task"] for s in r["spawned"]] == ["t1"]
    assert r["refused"] == [{"task": "t2",
                             "why": "token-budget 100: 60 committed + 60 reserved per worker"}]


def test_the_default_reservation_shares_the_budget_among_the_sessions(tmp_path):
    mind, brief, home = d._shift(tmp_path, names=("t1", "t2", "t3"), budget=100,
                                 extra="  - max-workers: 3\n  - max-sessions: 3\n")
    slot = orch.slot_dir(brief, home)
    claude = d.FakeClaude()
    r = d._tick(brief, mind, home, NOW, claude)
    assert len(r["spawned"]) == 3                              # 33 each fits 100
    # Real usage past the reservation is what counts from then on.
    r = d._tick(brief, mind, home, _later(1), claude,
                agents=d._agents({"t1": "working", "t2": "working", "t3": "working"}, slot),
                tokens=lambda s: 40)
    assert orch._committed_tokens(orch.read_counters(slot)) == 120
