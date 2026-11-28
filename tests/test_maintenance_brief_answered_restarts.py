"""PyAutoBrain#741: a maintenance brief takes no answered-question restarts.

Shadow maintenance shift 2026-11-27-pm (`backlog: none`, generated tasks
only) also proposed three tasks an answer had released, through the resume
path that bypasses the dip rules. Human ruling 2026-11-28: answered restarts
stay out of maintenance shifts and restart in the next ordinary shift.

Each tick-level test fails on the base commit. Fictional fixtures only.
"""

from __future__ import annotations

import datetime as _dt
import json

import pytest

import test_orchestrator_dispatch as d  # noqa: E402 — the real-spawner fixtures
from test_orchestrator_digest import _brief, orch  # noqa: E402
import _digest  # noqa: E402
import _questions  # noqa: E402

NOW = d.NOW
Q1 = "https://github.com/example-org/widgets/issues/70"
SHADOW = "  - maintenance:\n    - sources: census\n  - shadow: yes\n"
GATED = "  - maintenance:\n    - sources: census\n    - gate-open: PyAutoBrain#574\n"
GOAL = "1. maintenance: board findings"
ANSWER = {"t1": [{"id": "Q3", "shift": "2026-11-03-pm", "issue": Q1, "state": "answered",
                  "answered": "2026-11-03T22:00Z", "answer": "yes", "comment": ""}]}


def _answered_beside(tmp_path, monkeypatch, extra=""):
    """A brief naming t0 only (`backlog: none`), and t1 parked by the last
    shift on Q3, which the human has answered."""
    mind, brief, home = d._shift(tmp_path, names=("t0",), extra=extra)
    if extra:
        brief.write_text(brief.read_text().replace("1. sandbox shift", GOAL))
    (mind / "draft" / "feature" / "pyautobrain" / "t1.md").write_text(d.PROMPT.format(name="t1"))
    prev = home / "2026-11-03-pm"
    prev.mkdir(parents=True)
    (prev / orch.COUNTERS_FILE).write_text(json.dumps({
        "outcomes": {"t1": {"questions": [Q1], "prs": [], "merged": []}}, "parked": [],
        "picks": {"t1": {"prompt": "draft/feature/pyautobrain/t1.md"}}}))
    monkeypatch.setattr(_questions, "read_origin", lambda *a, **k: ANSWER)
    return mind, brief, home


def _brief_of(text: str) -> dict:
    return _brief.parse("- dispatched: 2026-11-28T00:00Z\n- review-at: 2026-11-28T12:00Z\n"
                        "- brief:\n  - goals:\n    - 1. maintenance: board findings\n"
                        + text + "  - backlog: none\n  - lanes: any\n")["brief"]


@pytest.mark.parametrize("block", [SHADOW, GATED, ""])
def test_scope_keeps_an_answered_restart_out_of_a_maintenance_brief_only(block):
    rec = {"path": "draft/x/t1.md", "lane": "any", "epic": "", "themes": [],
           "resume": {"ids": ["Q3"], "shift": "2026-11-03-pm"}}
    kept, rejected, _ = _brief.scope([rec], _brief_of(block))
    if block:
        assert kept == [] and rejected == [(rec["path"], _brief.ANSWERED_RESTART_REASON)]
    else:
        assert kept == [rec]                       # an ordinary brief resumes it
    # Named by the maintenance brief, it is the brief's own work.
    named = _brief_of("  - tasks:\n    - draft/x/t1.md\n" + block)
    assert _brief.scope([rec], named)[0] == [rec]


def test_a_shadow_maintenance_brief_proposes_only_its_own_tasks(tmp_path, monkeypatch):
    mind, brief, home = _answered_beside(tmp_path, monkeypatch, SHADOW)
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert r["action"] == "shadow" and r["proposed"] == ["t0"], r
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert set(c["picks"]) == {"t0"}
    assert c["backlog_gates"]["resumed"] == {}
    assert c["backlog_gates"]["answered_deferred"]["t1"]["ids"] == ["Q3"]
    lines = _digest.backlog_gate_lines(c)
    assert any(ln.startswith("Answered, left for the next ordinary shift: 1 task(s)")
               and "`t1` (Q3 answered)" in ln for ln in lines), lines


def test_a_live_gated_maintenance_brief_starts_only_its_own_tasks_and_keeps_the_answer(
        tmp_path, monkeypatch):
    mind, brief, home = _answered_beside(tmp_path, monkeypatch, GATED)
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert [s["task"] for s in r["spawned"]] == ["t0"], r
    # The answer is not used: the next ordinary shift resumes t1.
    nxt = tmp_path / "next.md"
    nxt.write_text(brief.read_text().replace("2026-11-04 am", "2026-11-04 pm")
                   .replace("2026-11-04T08:30Z", "2026-11-04T12:30Z")
                   .replace("2026-11-04T11:30Z", "2026-11-04T15:30Z").replace(GATED, "")
                   .replace(GOAL, "1. sandbox shift"))
    claude = d.FakeClaude()
    r = d._tick(nxt, mind, home, NOW + _dt.timedelta(hours=4), claude)
    assert "t1" in [s["task"] for s in r["spawned"]], r
    prompt = next(c[0][-1] for c in claude.calls if "shift:t1" in c[0])
    assert "parked on a question" in prompt and "Q3" in prompt


def test_a_shadow_proposal_does_not_use_up_a_release(tmp_path):
    """The 2026-11-27-pm proposals (pre-fix) must not hold Q39-41's tasks:
    a shadow shift started nothing. Its proposal comes after the answer, so
    a pick there would use the release up."""
    home = tmp_path / "home"
    for name, counters in (
            ("2026-11-03-pm", {"outcomes": {"t1": {"questions": [Q1], "prs": [],
                                                   "merged": []}}, "parked": []}),
            ("2026-11-04-aa", {"outcomes": {}, "parked": [], "picks": {
                "t1": {"prompt": "draft/x/t1.md", "proposed": True}}})):
        (home / name).mkdir(parents=True)
        (home / name / orch.COUNTERS_FILE).write_text(json.dumps(counters))
    resumes: dict = {}
    held = orch.parked_elsewhere(home / "2026-11-04-am", ANSWER, resumes)
    assert "t1" not in held and resumes["t1"]["ids"] == ["Q3"]


def _inshift_counters(why: str) -> dict:
    return {"outcomes": {"t1": {"questions": [Q1], "prs": [], "merged": []}},
            "picks": {"t1": {"prompt": "draft/x/t1.md", "why": why}}, "done": ["t1"]}


@pytest.mark.parametrize("why,restarts", [
    ("resumed after Q3 was answered · the answer's release", False),  # not its own
    ("backlog: scoped · scoped source maintenance", True),             # its own dip
])
def test_the_in_shift_restart_takes_only_a_maintenance_briefs_own_work(tmp_path, why,
                                                                        restarts):
    slot = tmp_path / "home" / "2026-11-04-am"
    slot.mkdir(parents=True)
    inbox = {"t1": [{"id": "Q7", "shift": slot.name, "issue": Q1, "state": "answered",
                     "answered": "x", "answer": "y", "comment": ""}]}
    review_at = NOW + _dt.timedelta(hours=2)
    counters, deferred = _inshift_counters(why), {}
    got = orch.released_here(slot, counters, inbox, NOW, review_at,
                             brief=_brief_of(GATED), deferred=deferred)
    assert ("t1" in got) is restarts and ("t1" in deferred) is not restarts
    assert ("t1" in counters["inshift_pending"]) is restarts
    assert counters["outcomes"]["t1"]["questions"]            # the park stays either way
    # An ordinary brief restarts it whatever the pick was.
    counters = _inshift_counters(why)
    assert "t1" in orch.released_here(slot, counters, inbox, NOW, review_at,
                                      brief=_brief_of(""))


def test_a_resumed_pick_names_the_answer_not_a_missing_rule():
    """`NOT RECORDED` on a resumed pick was `pick_reason`'s missing-rule
    marker: under `backlog: none` no dip rule admits it, the answer does."""
    member = {"path": "active/t1.md", "resume": {"ids": ["Q3"]}}
    rec = orch.pick_record(member, _brief_of(""))
    assert rec["why"] == f"resumed after Q3 was answered · {_brief.RESUME_RULE}"
    assert _brief.pick_reason({"path": "active/t2.md"}, _brief_of("")) == "NOT RECORDED"
