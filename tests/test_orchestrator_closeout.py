"""Autonomous orchestrators phase 4b (PyAutoBrain#572): the unattended `glance` close-out.

After CI lands green on a declared-`glance` PR a worker opened, the watcher
starts one independent close-out session; its verdict file decides the rest. A
merge lands one row in autonomy_log.md's stage-2 table through the one Mind
writer; every guard that fails starts nothing and is digested; nothing is ever
retried.
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_digest as t  # noqa: E402 — the 3d fixtures
from test_orchestrator_digest import _brief, _digest, orch  # noqa: E402
import _mind_writer as mw  # noqa: E402

PR1 = "https://github.com/o/r/pull/1"
PR2 = "https://github.com/o/r/pull/2"


class Spawner(t.FilesSpawner):
    """Workers that finished at once (PRs open, nothing merged in-turn) and a
    close-out whose verdict the test writes when it chooses."""

    def __init__(self):
        super().__init__(done={"named": PR1 + "\n", "picked": PR2 + "\n"}, proofs={})
        self.closeouts = []

    def spawn_closeout(self, task, pr_url, prompt_path, lease_dir):
        self.closeouts.append((task, pr_url))
        return {"pid": 0, "agent_id": f"co{len(self.closeouts):06d}"}


class Agents:
    """`claude agents --json`: every close-out still working unless told."""

    def __init__(self, states=None):
        self.states = states or {}

    def state(self, agent_id):
        return self.states.get(agent_id, "working")

    def session_of(self, agent_id):
        return None


def _health(verdicts):
    return lambda url: verdicts.get(url, "HEALTHY")


def _shift(tmp_path, cap=1, extra=""):
    mind = t._mind(tmp_path / "mind")
    brief = tmp_path / "shift.md"
    brief.write_text(t.BRIEF.format(issue=t.ISSUE, packet="")
                     .replace("merge-cap: 1", f"merge-cap: {cap}") + extra)
    home = tmp_path / "home"
    sp = Spawner()
    orch.tick(brief, mind, home=home, now=t.NOW, spawner=sp, agents=Agents(),
              health=_health({}))
    return mind, brief, home, sp


def _tick(brief, mind, home, sp, minutes, health=None, agents=None):
    return orch.tick(brief, mind, home=home, now=t.NOW + _dt.timedelta(minutes=minutes),
                     spawner=sp, agents=agents or Agents(), health=health or _health({}))


def _verdict(home, brief, task, **v):
    slot = orch.slot_dir(brief, home)
    (slot / "leases" / f"{task}.closeout").write_text(json.dumps(v))


# --- green + guards → exactly one close-out, merged → one stage-2 row -------------

def test_a_green_glance_pr_gets_exactly_one_closeout(tmp_path):
    mind, brief, home, sp = _shift(tmp_path, cap=2)
    r = _tick(brief, mind, home, sp, 1)       # reaps the workers, starts close-outs
    assert sorted(r["closeouts"]["started"]) == [PR1, PR2]
    _tick(brief, mind, home, sp, 2)
    _tick(brief, mind, home, sp, 3)
    assert sorted(sp.closeouts) == [("named", PR1), ("picked", PR2)]   # never twice


def test_a_merged_verdict_counts_and_queues_one_stage2_row(tmp_path):
    mind, brief, home, sp = _shift(tmp_path)
    _tick(brief, mind, home, sp, 1)
    _verdict(home, brief, "named", result="merged", pr=PR1, gate="tests PASS / witness PASS",
             model="claude-opus-5-5")
    r = _tick(brief, mind, home, sp, 2)
    assert r["closeouts"]["merged"] == [PR1]
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    assert c["glance_auto_merges"] == 1
    assert c["outcomes"]["named"]["merged"] == [PR1]
    ops = [json.loads(f.read_text()) for f in mw.pending_ops(slot)]
    rows = [o for o in ops if o["op"] == "table-append"]
    assert len(rows) == 1 and rows[0]["heading"] == orch.STAGE2_HEADING
    assert rows[0]["row"].startswith("| 2026-11-04 | named (" + PR1 + ") | shift |")
    assert "adversary: independent close-out session (claude-opus-5-5)" in rows[0]["row"]
    assert rows[0]["row"].endswith("| merged-unchanged |")
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot, c, health=t._health)
    assert "merged unattended (close-out, claude-opus-5-5)" in d
    assert "- glance-auto-merges: 1" in d and "- merges: 1" in d


# --- each guard failing on its own → nothing started, the reason digested -------

def test_a_non_glance_task_is_never_closed_out(tmp_path):
    mind, brief, home, sp = _shift(tmp_path, cap=2)
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    c["picks"]["named"]["tier"] = "notify"
    orch._write_counters(slot, c)
    _tick(brief, mind, home, sp, 1)
    assert ("named", PR1) not in sp.closeouts
    co = orch.read_counters(slot)["closeouts"][PR1]
    assert co["state"] == "refused" and "only glance merges unattended" in co["why"]


def test_red_ci_is_refused_and_pending_ci_waits(tmp_path):
    mind, brief, home, sp = _shift(tmp_path, cap=2)
    h = _health({PR1: "FAILED", PR2: "RUNNING"})
    _tick(brief, mind, home, sp, 1, health=h)
    assert sp.closeouts == []
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["closeouts"][PR1]["why"] == "CI FAILED — never merged unattended"
    assert PR2 not in c["closeouts"]                          # waiting, not refused
    _tick(brief, mind, home, sp, 2, health=_health({PR1: "HEALTHY"}))
    assert sp.closeouts == [("picked", PR2)]                  # PR1's refusal is final


def test_merge_cap_counts_merges_and_in_flight_closeouts(tmp_path):
    mind, brief, home, sp = _shift(tmp_path, cap=1)
    r = _tick(brief, mind, home, sp, 1)
    assert len(r["closeouts"]["started"]) == 1 and len(r["closeouts"]["refused"]) == 1
    c = orch.read_counters(orch.slot_dir(brief, home))
    refused = [co for co in c["closeouts"].values() if co["state"] == "refused"]
    assert refused[0]["why"] == "merge-cap 1 reached this shift"


def test_merge_cap_zero_starts_nothing(tmp_path):
    mind, brief, home, sp = _shift(tmp_path, cap=0)
    _tick(brief, mind, home, sp, 1)
    assert sp.closeouts == []


def test_a_shadow_shift_never_closes_out(tmp_path):
    mind, brief, home, sp = _shift(tmp_path, cap=2)
    slot = orch.slot_dir(brief, home)
    counters = orch.read_counters(slot)
    events = orch._closeouts(slot, {"shadow": {"value": "yes", "children": []},
                                    "merge-cap": {"value": "2", "children": []}},
                             counters, sp, t.NOW, Agents(), _health({}))
    assert events["started"] == [] and sp.closeouts == []


# --- refusals are final and digested ------------------------------------------

def test_a_refused_closeout_is_digested_and_never_retried(tmp_path):
    mind, brief, home, sp = _shift(tmp_path)
    _tick(brief, mind, home, sp, 1)
    _verdict(home, brief, "named", result="refused", pr=PR1,
             why="decision-taken label", gate="", model="claude-opus-5-5")
    _tick(brief, mind, home, sp, 2)
    _tick(brief, mind, home, sp, 3)
    assert [c for c in sp.closeouts if c[1] == PR1] == [("named", PR1)]
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    assert c["glance_auto_merges"] == 0 and c["outcomes"]["named"]["merged"] == []
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot, c, health=t._health)
    assert f"{PR1} — awaiting /prm — close-out refused: decision-taken label" in d


def test_a_closeout_that_ends_without_a_verdict_is_refused_not_retried(tmp_path):
    mind, brief, home, sp = _shift(tmp_path)
    _tick(brief, mind, home, sp, 1)
    _tick(brief, mind, home, sp, 2, agents=Agents({"co000001": "done"}))
    _tick(brief, mind, home, sp, 3)
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["closeouts"][PR1]["why"] == "the close-out session ended without a verdict"
    assert len(sp.closeouts) == 1


# --- the session and the Mind writer -------------------------------------------

def test_closeout_command_is_named_moded_and_on_the_closeout_model(tmp_path):
    argv = orch.closeout_command("t1", PR1, "draft/x/t1.md", tmp_path / "b.md",
                                 tmp_path / "leases", "auto")
    assert argv[:8] == ["claude", "--bg", "--name", "shift-close:t1", "--model", "opus",
                        "--permission-mode", "auto"]
    prompt = argv[-1]
    assert PR1 in prompt and "run it yourself" in prompt
    assert str(tmp_path / "leases" / "t1.closeout") in prompt
    with pytest.raises(orch.OrchestratorError):
        orch.closeout_command("t1", PR1, "x", tmp_path, tmp_path, "bypassPermissions")


def test_the_worker_template_hands_glance_merges_to_the_closeout():
    tpl = (t.BATCH / "worker_template.md").read_text()
    assert "end at PR-open" in tpl and "independent close-out" in tpl


def test_table_append_keeps_what_follows_the_section():
    text = ("## A\n| x |\n|---|\n| 1 |\n\n" + orch.STAGE2_HEADING + " — opened\n\n"
            "| d |\n|---|\n\n## After\ntail\n")
    out = mw.table_append(text, orch.STAGE2_HEADING, "| 2 |")
    assert out.index("| 2 |") < out.index("## After") and out.count("| 2 |") == 1
    assert out.index("| 2 |") > out.index(orch.STAGE2_HEADING)
    with pytest.raises(mw.MindWriteError):
        mw.table_append("## Other\n", orch.STAGE2_HEADING, "| 2 |")


@pytest.mark.skipif(not t.LEDGER_MERGE.is_file() or shutil.which("git") is None,
                    reason="needs git and PyAutoMind's scripts/ledger_merge.py")
def test_a_merged_closeout_lands_one_stage2_row_on_mind_main(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    bare = tmp_path / "remote.git"
    t.git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    canon = tmp_path / "canon"
    t.git(tmp_path, "clone", "-q", str(bare), str(canon))
    t.git(canon, "config", "user.name", "Test")
    t.git(canon, "config", "user.email", "test@example.invalid")
    t._mind(canon)
    (canon / "scripts").mkdir()
    shutil.copy(t.LEDGER_MERGE, canon / "scripts" / "ledger_merge.py")
    (canon / "autonomy_log.md").write_text(
        "# Log\n\n## Shadow window\n\n| a |\n|---|\n\n" + orch.STAGE2_HEADING
        + " — opened 2026-11-04\n\n| date | task | brief | gate | human action |\n"
        "|---|---|---|---|---|\n\n## Later section\nkept\n")
    t.git(canon, "add", "-A")
    t.git(canon, "commit", "-q", "-m", "seed")
    t.git(canon, "push", "-q", "origin", "HEAD:main")

    brief = tmp_path / "shift.md"
    brief.write_text(t.BRIEF.format(issue=t.ISSUE, packet=""))
    home, sp = tmp_path / "home", Spawner()
    orch.tick(brief, canon, home=home, now=t.NOW, spawner=sp, agents=Agents(),
              health=_health({}))
    _tick(brief, canon, home, sp, 1)
    _verdict(home, brief, "named", result="merged", pr=PR1, gate="tests PASS",
             model="claude-opus-5-5")
    r = _tick(brief, canon, home, sp, 2)
    assert r["ledger"]["committed"], r
    log = t.git(bare, "show", "main:autonomy_log.md").stdout
    section = log[log.index(orch.STAGE2_HEADING):log.index("## Later section")]
    rows = [ln for ln in section.splitlines() if ln.startswith("| 2026-11-04 ")]
    assert len(rows) == 1 and "named (" + PR1 + ")" in rows[0]
    assert log.rstrip().endswith("kept")
