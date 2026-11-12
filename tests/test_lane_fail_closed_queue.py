"""M2.3 (PyAutoBrain#614; AUTONOMY.md "M2 rulings — 2026-11-12").

(a) An absent `Lane:` fails closed in an unattended pick and reads as `any` in
an attended one; intake always writes a Lane. (b) `queue.md` is the ranked
list: an empty one stops a shift's backlog dip (named tasks still run), and the
planner sorts priority before review-minutes. Fictional fixtures only.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BRAIN / "agents" / "conductors" / "intake"))
sys.path.insert(0, str(BRAIN / "agents" / "conductors" / "batch"))
import _intake  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "_batch_m23", BRAIN / "agents" / "conductors" / "batch" / "_batch.py")
_batch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_batch)
_brief = _batch._brief
import _digest  # noqa: E402

DRAFT = """\
# {title}

Type: feature
Target: PyAutoBrain
Repos:
- PyAutoBrain
Difficulty: small
Autonomy: safe
Priority: normal
Status: formalised
Consequence: notify
Witness: tests pass
Review-minutes: 2
Unattended: ready
{lane}

Tidy one docstring.
"""


def _mind(tmp_path: Path, drafts: dict[str, str]) -> Path:
    mind = tmp_path / "mind"
    folder = mind / "draft" / "feature" / "pyautobrain"
    folder.mkdir(parents=True)
    for name, lane in drafts.items():
        (folder / f"{name}.md").write_text(
            DRAFT.format(title=name, lane=lane), encoding="utf-8")
    return mind


def _paths(d):
    return [m["path"] for m in d["members"]]


def _rec(path, lane="any", **kw):
    r = {"path": path, "repos": [], "work_type": "feature", "difficulty": "small",
         "score": 1, "consequence": "notify", "witness": "w", "review_minutes": 2,
         "unattended": "ready", "why": "", "ready_why": "", "epic": None,
         "lane": lane, "priority": "normal", "blocked": False,
         "autonomy": "safe", "autonomy_cap": "safe", "declared_autonomy": None,
         "done": False, "themes": []}
    r.update(kw)
    return r


# --- (a) an absent Lane fails closed unattended ----------------------------------

def test_unattended_plan_excludes_an_absent_lane_attended_includes_it(tmp_path):
    """The witness: graded from real files, the lane-less draft is refused by
    the unattended plan with a stated reason and taken by the attended one."""
    mind = _mind(tmp_path, {"declared": "Lane: any", "absent": ""})
    records = _batch.survey(mind)
    absent = "draft/feature/pyautobrain/absent.md"
    declared = "draft/feature/pyautobrain/declared.md"
    assert {r["path"]: r["lane"] for r in records} == {absent: None, declared: "any"}

    for lane in ("web-github", "local-dev"):
        d = _batch.plan(records, session_lane=lane, budget=45)
        assert _paths(d) == [declared]
        assert dict(d["rejected"])[absent].startswith("lane absent")
        assert d["lane_absent"] == [absent]

    d = _batch.plan(records, session_lane="web-github", budget=45, attended=True)
    assert sorted(_paths(d)) == [absent, declared]
    assert d["lane_absent"] == []


def test_an_invalid_lane_is_absent_to_an_unattended_pick():
    d = _batch.plan([_rec("draft/x.md", lane=None, lane_invalid="any | local-dev")])
    assert _paths(d) == []
    assert "lane invalid" in dict(d["rejected"])["draft/x.md"]


def test_a_brief_named_task_is_not_a_backlog_dip():
    """The lane gate guards the backlog. A task the human NAMED in the brief is
    their own pick; the brief's `lanes:` still applies to it."""
    brief = _brief.parse(BRIEF)["brief"]
    d = _batch.plan([_rec("draft/named.md", lane=None),
                     _rec("draft/dip.md", lane=None)],
                    session_lane="local-dev", brief=brief, queue=["draft/q.md"])
    assert _paths(d) == ["draft/named.md"]
    assert dict(d["rejected"])["draft/dip.md"].startswith("lane absent")


def test_the_plan_output_says_so(capsys):
    d = _batch.plan([_rec("draft/a.md", lane=None)], queue=[])
    _batch.emit(d)
    out = capsys.readouterr().out
    assert "Lane absent:       1 draft(s) excluded" in out
    assert "Backlog dip:       STOPPED" in out


def test_intake_writes_lane_any_when_inference_finds_nothing():
    assert "\nLane: any" in _intake.analyse("Tidy a docstring in @PyAutoBrain.",
                                            "test")["header"]


# --- (b) queue.md is the ranked list --------------------------------------------

BRIEF = """\
# Batch 2026-11-12 am
- dispatched: 2026-11-12T08:30Z
- review-at: 2026-11-12T11:30Z
- brief:
  - tasks:
    - draft/named.md
  - backlog: fill-idle
  - review-minutes: 45
  - lanes: any local-dev
"""


def test_an_empty_queue_stops_the_backlog_dip_named_tasks_still_run():
    brief = _brief.parse(BRIEF)["brief"]
    recs = [_rec("draft/named.md"), _rec("draft/dip.md")]
    d = _batch.plan(recs, session_lane="local-dev", brief=brief, queue=[])
    assert _paths(d) == ["draft/named.md"]
    assert d["queue_stop"] is True
    assert dict(d["rejected"])["draft/dip.md"].startswith("queue.md empty")
    # A non-empty queue lets the dip run, and so does an attended plan.
    d = _batch.plan(recs, session_lane="local-dev", brief=brief, queue=["draft/q.md"])
    assert sorted(_paths(d)) == ["draft/dip.md", "draft/named.md"]
    d = _batch.plan(recs, session_lane="local-dev", brief=brief, queue=[], attended=True)
    assert sorted(_paths(d)) == ["draft/dip.md", "draft/named.md"]


def test_an_absent_queue_md_stops_the_dip_without_a_brief(tmp_path):
    mind = _mind(tmp_path, {"a": "Lane: any"})
    assert _batch.read_queue(mind) == []
    d = _batch.plan(_batch.survey(mind), queue=_batch.read_queue(mind))
    assert _paths(d) == [] and d["queue_stop"] is True


def test_priority_sorts_before_review_minutes():
    d = _batch.plan([_rec("a.md", review_minutes=1, priority="low"),
                     _rec("b.md", review_minutes=20, priority="high"),
                     _rec("c.md", review_minutes=5)],
                    queue=["queued.md"], budget=100)
    assert _paths(d) == ["b.md", "c.md", "a.md"]


def test_retired_footer_refs_are_not_read_as_the_last_entry(tmp_path):
    """Until 2026-11-12 a `- ref:` in the `## Retired` footer overwrote the
    last live entry's ref: the planner read Mind's one-entry queue as the
    epic slug in the footer."""
    (tmp_path / "queue.md").write_text(
        "# Queue\n\n## 1. Live\n- kind: prompt\n- ref: draft/a/b/live.md\n\n"
        "## Retired\n\n### Old\n- ref: some-epic-slug\n- note: gone\n",
        encoding="utf-8")
    assert _batch.read_queue(tmp_path) == ["draft/a/b/live.md"]


# --- the digest says so ------------------------------------------------------------

def test_digest_names_both_gates():
    counters = {"backlog_gates": {"queue_stop": True,
                                  "lane_absent": ["draft/x/y/no_lane.md"]}}
    lines = _digest.backlog_gate_lines(counters)
    assert any("Backlog dip stopped" in l for l in lines)
    assert any("`no_lane`" in l for l in lines)
    assert not any(l.startswith("- ") for l in lines)   # never read as a pick
    assert _digest.backlog_gate_lines({}) == []


# --- the doctrine record ------------------------------------------------------------

def test_autonomy_records_the_six_m2_rulings_once():
    text = (BRAIN / "AUTONOMY.md").read_text(encoding="utf-8")
    assert text.count("\n## M2 rulings — 2026-11-12\n") == 1
    sec = text.split("\n## M2 rulings — 2026-11-12\n", 1)[1].split("\n## ", 1)[0]
    for lead in ("**M2.1 ", "**M2.2 ", "**M2.3 ", "**M2.4 ", "**M2.5 ",
                 "**Quarantine "):
        assert sec.count(lead) == 1, lead
    assert sec.count("*Revert condition:*") == 6
    for build in ("PyAutoHeart#340", "PyAutoBrain#614", "PyAutoHands#337",
                  "Build: to build", "Awaits a human act"):
        assert build in sec, build
