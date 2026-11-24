"""PyAutoBrain#720: a park on a question releases its library after 15 minutes.

Human ruling 2026-11-24 (in chat, "Release after 15 min"), amending ruling (d)
of 2026-11-19 (AUTONOMY.md, M3.6j): a park on a question holds its library's
start for `PARK_HOLD_GRACE` from the park, then releases it. Inside the grace a
task waiting on that library is refused but `startable`, so the shift does not
close early. An answer after the grace restarts the parked task only when its
library is free. Shift 2026-11-24-am closed early with two tasks never started
behind one park (PyAutoMind `active/shift_closes_early_with_held_tasks_unstarted.md`).

One test per Witness clause; each fails on main 76b5316. Fictional fixtures only.
"""

from __future__ import annotations

import datetime as _dt

import pytest
import test_batch_named_tasks as nt  # the one-library shift fixtures
import test_orchestrator_dispatch as d  # the real-spawner fixtures
from test_orchestrator_dispatch import orch

NOW = d.NOW                        # 09:00Z; the brief's review-at is 11:30Z
MIN = _dt.timedelta(minutes=1)
GRACE = 15 * MIN                  # the ruling's figure: `PARK_HOLD_GRACE`
Q1 = "https://github.com/example-org/autogalaxy/issues/70"
PR2 = "https://github.com/example-org/autogalaxy/pull/8"
B_PATH = "draft/feature/x/ag_bug_two.md"


def _spawned(r) -> list[str]:
    return [s["task"] for s in r["spawned"]]


def _named(brief, home) -> dict:
    return orch.read_counters(orch.slot_dir(brief, home))["backlog_gates"]["named"]


def _lease_park(tmp_path):
    """ag_bug_one starts at 09:00Z, shows `blocked` and is parked once
    `STALL_GRACE_S` has passed (09:16Z): a lease park on a person."""
    mind, brief, home = nt._galaxy_shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    blocked = lambda: d._agents({"ag_bug_one": "blocked"}, slot)
    d._tick(brief, mind, home, NOW + MIN, d.FakeClaude(), agents=blocked())
    park = NOW + MIN + _dt.timedelta(seconds=orch.STALL_GRACE_S)
    r = d._tick(brief, mind, home, park, d.FakeClaude(), agents=blocked())
    assert {"task": "ag_bug_one", "event": "parked"}.items() <= r["reaped"][0].items(), r
    return mind, brief, home, slot, park, blocked


def _outcome_park(tmp_path):
    """ag_bug_one ends at 09:02Z with an open question in its `.done`: the
    digest's PARKED-ON-ISSUE."""
    mind, brief, home = nt._galaxy_shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    (slot / "leases" / "ag_bug_one.done").write_text(f"question: {Q1}\n")
    park = NOW + 2 * MIN
    r = d._tick(brief, mind, home, park, d.FakeClaude(),
                agents=d._agents({"ag_bug_one": "done"}, slot))
    assert {"task": "ag_bug_one", "event": "done"} in r["reaped"], r
    assert orch.read_counters(slot)["outcomes"]["ag_bug_one"]["questions"] == [Q1]
    return mind, brief, home, slot, park, lambda: d._agents({}, slot)


@pytest.mark.parametrize("parked", [_lease_park, _outcome_park],
                         ids=["1-lease-park", "2-outcome-question"])
def test_720_1_2_the_held_task_waits_startable_then_starts_after_15_minutes(tmp_path,
                                                                         parked):
    mind, brief, home, slot, park, agents = parked(tmp_path)
    until = (park + GRACE).strftime("%H:%MZ")
    for at in (park + MIN, park + GRACE - MIN):
        r = d._tick(brief, mind, home, at, d.FakeClaude(), agents=agents())
        assert _spawned(r) == [], r
        # Refused, but it can start this shift: the shift stays open.
        assert "ag_bug_two" in r.get("startable", []), r
        assert not orch.early_close_ready(slot, orch.read_counters(slot), r)
        assert "closed_early" not in orch.read_counters(slot), r
        assert _named(brief, home)[B_PATH] == \
            f"autogalaxy held by ag_bug_one (parked) until {until}"
    # The first tick at the end of the grace starts the waiting task.
    r = d._tick(brief, mind, home, park + GRACE, d.FakeClaude(),
                agents=agents())
    assert _spawned(r) == ["ag_bug_two"], r


def _answer(monkeypatch, slot, answered: str) -> None:
    """The human answers ag_bug_one's question (Q7) in the inbox."""
    monkeypatch.setattr(orch._questions, "read_origin", lambda *a, **k: {"ag_bug_one": [
        {"id": "Q7", "shift": slot.name, "issue": Q1, "state": "answered",
         "answered": answered, "answer": "(a) yes", "comment": f"{Q1}#issuecomment-1"}]})


def test_720_3_an_answer_after_the_grace_waits_for_the_library_to_be_free(tmp_path,
                                                                          monkeypatch):
    mind, brief, home, slot, park, _ = _outcome_park(tmp_path)
    r = d._tick(brief, mind, home, park + GRACE, d.FakeClaude())
    assert _spawned(r) == ["ag_bug_two"], r
    # The answer arrives while ag_bug_two runs on autogalaxy: no restart yet.
    _answer(monkeypatch, slot, "2026-11-04T09:25Z")
    working = lambda: d._agents({"ag_bug_two": "working"}, slot)
    for minutes in (25, 30):
        r = d._tick(brief, mind, home, NOW + minutes * MIN, d.FakeClaude(), agents=working())
        assert _spawned(r) == [], r
        assert set(orch.active_leases(slot)) == {"ag_bug_two"}      # never two on a library
        assert "ag_bug_one" in orch.read_counters(slot)["inshift_pending"]
    # Its worker ends: the library is free and the parked task restarts.
    (slot / "leases" / "ag_bug_two.done").write_text(f"{PR2}\n")
    r = d._tick(brief, mind, home, NOW + 35 * MIN, d.FakeClaude(),
                agents=d._agents({"ag_bug_two": "done"}, slot))
    assert _spawned(r) == ["ag_bug_one"], r
    assert set(orch.active_leases(slot)) == {"ag_bug_one"}


def test_720_4_an_answer_inside_the_grace_restarts_the_parked_task_as_before(tmp_path,
                                                                            monkeypatch):
    mind, brief, home, slot, park, _ = _outcome_park(tmp_path)
    r = d._tick(brief, mind, home, park + 5 * MIN, d.FakeClaude())
    assert _spawned(r) == [] and "ag_bug_two" in r.get("startable", []), r
    _answer(monkeypatch, slot, "2026-11-04T09:08Z")
    r = d._tick(brief, mind, home, park + 8 * MIN, d.FakeClaude())
    assert _spawned(r) == ["ag_bug_one"], r
    # Live again, it holds its library as any live worker does.
    r = d._tick(brief, mind, home, park + 20 * MIN, d.FakeClaude(),
                agents=d._agents({"ag_bug_one": "working"}, slot))
    assert _spawned(r) == [], r
    assert set(orch.active_leases(slot)) == {"ag_bug_one"}


def test_720_5_an_unknown_park_time_keeps_the_hold(tmp_path):
    """A park the counters hold no time for (no `park_times`, no inbox entry)
    holds as before: fail closed, never startable on a guess."""
    picks = {"a": {"repos": ["autogalaxy"]}, "b": {"repos": ["autogalaxy"]}}
    c = {"done": ["a"], "picks": picks, "parked": [], "pending_redispatch": [],
         "outcomes": {"a": {"prs": [], "merged": [], "questions": [Q1]}}}
    late = NOW + 5 * 60 * MIN
    assert orch.PARK_HOLD_GRACE == GRACE
    assert orch.park_time(c, "a") is None and orch.park_hold_until(c, "a") is None
    assert "a" not in orch.released_picks(c, now=late)
    assert orch._library_holder(c, {}, "b", ["autogalaxy"], late) == ("autogalaxy", "a")
    assert orch.park_hold_end(c, "a", late) == ""          # held, but not until a time
    assert orch.park_holds_in_grace(c, late) == {}
    # A known time releases it; the inbox's `asked` serves for older counters.
    # It is read at the end of its minute, so the hold never ends early.
    c["inbox"] = [{"task": "a", "issue": Q1, "kind": "question", "asked": "2026-11-04T09:00Z"}]
    assert orch.park_time(c, "a") == NOW + MIN
    assert orch.park_hold_end(c, "a", NOW + 15 * MIN) == "09:16Z"
    assert "a" not in orch.released_picks(c, now=NOW + 15 * MIN)
    assert "a" in orch.released_picks(c, now=NOW + 16 * MIN)
    assert orch._library_holder(c, {}, "b", ["autogalaxy"], NOW + 16 * MIN) is None
    # Without `now` every park holds, as before the amendment.
    assert "a" not in orch.released_picks(c)


def test_720_5_an_unknown_park_time_keeps_the_hold_at_a_tick(tmp_path):
    mind, brief, home = nt._galaxy_shift(tmp_path)
    nt._end(brief, home, "ag_bug_one",
            {"prs": [], "merged": [], "issues": [Q1], "questions": [Q1]})
    for at in (NOW + 20 * MIN, NOW + 2 * 60 * MIN):
        r = d._tick(brief, mind, home, at, d.FakeClaude())
        assert _spawned(r) == [] and "ag_bug_two" not in r.get("startable", []), r
    assert orch.park_hold_until(orch.read_counters(orch.slot_dir(brief, home)),
                                "ag_bug_one") is None


@pytest.mark.parametrize("outcome", [
    pytest.param({"prs": [], "merged": [], "questions": [Q1], "obsolete": "fixed on main"},
                 id="obsolete"),
    pytest.param({"prs": [PR2], "merged": [PR2], "questions": [Q1]}, id="merged"),
])
def test_720_review_an_obsolete_or_merged_outcome_is_not_a_park(outcome):
    """Review finding 3: a park is what `_reap` stamps a park time on (the
    `_open_parks` test), so an obsolete or merged outcome holds nothing."""
    c = {"done": ["a"], "picks": {"a": {"repos": ["autogalaxy"]}}, "parked": [],
         "pending_redispatch": [], "outcomes": {"a": outcome}}
    assert orch._park_holds(c) == set() and orch._open_parks(c) == []
    assert "a" in orch.released_picks(c, now=NOW)
    assert orch._library_holder(c, {}, "b", ["autogalaxy"], NOW) is None


@nt.sf.needs_git
def test_720_review_a_parked_tasks_claim_is_a_repo_hold_in_the_digest(tmp_path):
    """Review finding 2: the claim a parked task's own shift worker left holds
    its repo until the grace ends, and the digest counts it as repo-held, not
    as a draft claimed on Mind origin/main."""
    mind, second, claim = nt._claimed_galaxy_mind(tmp_path)
    claim("shift worker 2026-11-18-pm (abc123)")
    records = [nt._batch.grade(mind / second, mind)]
    kept, out = orch.on_origin(records, mind, own={"ag_bug_one"}, released=set(),
                               slot_name="2026-11-18-pm", parked={"ag_bug_one": "09:15Z"})
    assert kept == [] and out == {
        second: "repo autogalaxy held by ag_bug_one (parked) until 09:15Z"}
    lines = orch._digest.backlog_gate_lines({"backlog_gates": {"origin": out}})
    assert [ln for ln in lines if ln.startswith("Repo claimed on Mind origin/main: 1 ")], lines
    assert not [ln for ln in lines if ln.startswith("Claimed on Mind origin/main")], lines
