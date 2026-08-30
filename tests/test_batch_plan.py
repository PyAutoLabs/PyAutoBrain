"""tests/test_batch_plan.py — the Batch Agent's composition rules.

The planner's whole job is refusing things for stated reasons, so every test
here is a refusal (or the one case that must never be refused: the floor).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
_spec = importlib.util.spec_from_file_location(
    "_batch_under_test", BRAIN / "agents" / "conductors" / "batch" / "_batch.py")
_batch = importlib.util.module_from_spec(_spec)
sys.modules["_batch_under_test"] = _batch
_spec.loader.exec_module(_batch)


def rec(path, *, minutes=20, tier="judge", ready="ready", repos=(), epic="",
        lane="any", blocked=False, priority="normal", autonomy="safe",
        done=False, phase=float("inf")):
    return {"path": path, "repos": list(repos), "work_type": "feature",
            "difficulty": "medium", "score": 4, "consequence": tier,
            "witness": None, "review_minutes": minutes, "unattended": ready,
            "why": "", "ready_why": [], "epic": epic, "lane": lane,
            "priority": priority, "blocked": blocked, "autonomy": autonomy,
            "autonomy_cap": "safe", "declared_autonomy": autonomy,
            "done": done, "phase": phase}


def paths(d):
    return [m["path"] for m in d["members"]]


def why(d, path):
    return next(w for p, w in d["rejected"] if p == path)


def test_the_budget_is_review_minutes_not_a_task_count():
    """Three 20-minute tasks do not fit a 45-minute slot, however small they
    look by any other measure."""
    d = _batch.plan([rec(f"{i}.md") for i in "abc"], budget=45)
    assert len(d["members"]) == 2
    assert d["review_minutes_planned"] == 40
    assert "exceed the budget" in why(d, "c.md")


def test_notify_tier_work_costs_the_human_nothing():
    """The fill. It is capped by the token allowance, not by the human's hour,
    which is what lets the allowance be spent without growing the queue."""
    d = _batch.plan([rec(f"{i}.md", tier="notify", minutes=0) for i in range(9)],
                    budget=45)
    assert len(d["members"]) == 9
    assert d["review_minutes_planned"] == 0


def test_one_member_per_library_repo_per_shift():
    """They do not collide at dispatch — separate worktrees — they collide at
    merge, when the first /prm moves main and invalidates the rest."""
    d = _batch.plan([rec("a.md", repos=["autoarray"]),
                     rec("b.md", repos=["autoarray"])], budget=100)
    assert paths(d) == ["a.md"]
    assert "autoarray already claimed" in why(d, "b.md")


def test_non_library_repos_do_not_claim_a_shift():
    """Two docs changes to the same organ repo cost nothing to merge together."""
    d = _batch.plan([rec("a.md", repos=["pyautomind"]),
                     rec("b.md", repos=["pyautomind"])], budget=100)
    assert paths(d) == ["a.md", "b.md"]


def test_one_slice_per_epic():
    d = _batch.plan([rec("a.md", epic="euclid"), rec("b.md", epic="euclid")],
                    budget=100)
    assert paths(d) == ["a.md"]
    assert "epic euclid already" in why(d, "b.md")


def test_a_session_never_plans_the_other_lane_but_reports_it():
    """Silently dropping it would leave the human unable to tell 'nothing ready'
    from 'nothing I can run from here'."""
    d = _batch.plan([rec("a.md", lane="local-dev")], session_lane="web-github")
    assert d["members"] == []
    assert d["other_lane_ready"] == 1
    d2 = _batch.plan([rec("a.md", lane="local-dev")], session_lane="local-dev")
    assert paths(d2) == ["a.md"]


def test_only_unattended_ready_work_is_selected():
    d = _batch.plan([rec("a.md", ready="needs-slicing"),
                     rec("b.md", ready="never"),
                     rec("c.md", blocked=True)], budget=100)
    assert d["members"] == []
    assert "needs-slicing" in why(d, "a.md")
    assert "Blocked-by" in why(d, "c.md")


def test_backpressure_ramps_rather_than_cliffs():
    pool = [rec(f"{i}.md") for i in range(6)]
    assert _batch.plan(pool, budget=60, awaiting_review=0)["effective_budget"] == 60
    assert _batch.plan(pool, budget=60, awaiting_review=6)["effective_budget"] == 30
    assert _batch.plan(pool, budget=60, awaiting_review=8)["effective_budget"] == 0


def test_at_the_cap_the_floor_is_fill_only_and_still_runs():
    """A conference week must not stop the thing whose whole purpose is working
    while nobody watches. At the cap the review-bearing half is zero — but
    zero-cost work still dispatches."""
    d = _batch.plan([rec("a.md"), rec("b.md", tier="notify", minutes=0)],
                    budget=60, awaiting_review=99)
    assert paths(d) == ["b.md"]


def test_cheapest_first_because_the_question_is_what_fits():
    d = _batch.plan([rec("slow.md", minutes=20, priority="high"),
                     rec("fast.md", minutes=2, priority="low")], budget=45)
    assert paths(d)[0] == "fast.md"


def test_every_rejection_states_a_reason():
    d = _batch.plan([rec("a.md"), rec("b.md"), rec("c.md")], budget=20)
    assert d["rejected"]
    assert all(isinstance(w, str) and w for _, w in d["rejected"])


def test_lane_detection_reads_the_environment_not_a_flag():
    """A session that could be told where it is could plan local-dev work it
    cannot run. Probed from `gh`, the same signal the organism already uses."""
    assert _batch.detect_lane() in ("local-dev", "web-github")


def test_only_safe_work_is_dispatched():
    """Readiness says the work FITS one run; autonomy says the run may FINISH
    it. A batch that reads only the first fills a shift with tasks that all
    stop at the ship checkpoint and come back as questions — which is the
    failure the epic exists to remove. Found by running the planner against the
    live backlog and reading what it picked."""
    d = _batch.plan([rec("a.md", autonomy="safe"),
                     rec("b.md", autonomy="supervised"),
                     rec("c.md", autonomy="human-required")], budget=100)
    assert paths(d) == ["a.md"]
    assert "would park at ship" in why(d, "b.md")


def test_a_prompt_that_says_it_is_done_is_never_dispatched():
    """A session that ships the work and writes the outcome into `Status:` but
    leaves the file in draft/ is a recorded failure mode; the file keeps
    rendering as pickable backlog. Dispatching one wastes a whole shift
    re-doing finished work."""
    d = _batch.plan([rec("a.md", done=True), rec("b.md")], budget=100)
    assert paths(d) == ["b.md"]
    assert "already done" in why(d, "a.md")


def test_an_epic_offers_only_its_next_phase():
    """Members are worked in order. One-slice-per-epic caps how many run; this
    decides WHICH — without it the planner can propose phase 6 while phase 3 is
    still open."""
    d = _batch.plan([rec("late.md", epic="euclid", phase=6),
                     rec("next.md", epic="euclid", phase=3)], budget=100)
    assert paths(d) == ["next.md"]
    assert "is not next" in why(d, "late.md")


def test_a_shipped_phase_does_not_block_the_one_after_it():
    d = _batch.plan([rec("done.md", epic="e", phase=1, done=True),
                     rec("next.md", epic="e", phase=2)], budget=100)
    assert paths(d) == ["next.md"]


def test_dispatch_payloads_carry_no_decisions():
    """The launch is the human's act, so what they perform should carry nothing
    still to be decided — everything was decided when they approved the batch."""
    d = _batch.plan([rec("draft/x/y/z.md")], budget=100)
    assert d["dispatch"] == ["/start_dev draft/x/y/z.md --auto"]
