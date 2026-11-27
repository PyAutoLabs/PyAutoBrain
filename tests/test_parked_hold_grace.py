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


def _stops(claude) -> list[str]:
    """The session ids a fake `claude` was asked to stop (`claude stop <id>`)."""
    return [argv[2] for argv, _ in claude.calls if argv[:2] == ["claude", "stop"]]


def _agent(slot, task) -> str:
    return orch.leases(slot)[task]["agent_id"]


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
    claude = d.FakeClaude()
    r = d._tick(brief, mind, home, park + GRACE, claude, agents=agents())
    c = orch.read_counters(slot)
    if parked is _lease_park:
        # Stop, then release (2026-11-27): at the end of the grace the parked
        # session is stopped, and the park becomes a question park an answer
        # restarts; its library is held until the session is seen to end.
        assert _stops(claude) == [_agent(slot, "ag_bug_one")], claude.calls
        assert _spawned(r) == [], r
        assert {"task": "ag_bug_one", "event": "park-stopped", "issue": nt.ISSUE} \
            in r["reaped"], r
        assert c["park_released"]["ag_bug_one"]["how"] == "stopped"
        assert "ag_bug_one" not in c["parked"] and "ag_bug_one" in c["done"]
        assert c["outcomes"]["ag_bug_one"]["questions"] == [nt.ISSUE]
        # Still ending: held, but it will start, so the shift stays open.
        assert "ag_bug_two" in r.get("startable", []), r
        assert not orch.early_close_ready(slot, c, r)
        assert _named(brief, home)[B_PATH] == \
            "autogalaxy held by ag_bug_one (parked: stopped, its session is still ending)"
        assert "ag_bug_one" not in orch.released_picks(c, now=park + GRACE)
        # The reap sees the session end: the waiting task starts.
        r = d._tick(brief, mind, home, park + GRACE + MIN, d.FakeClaude(),
                    agents=d._agents({"ag_bug_one": "stopped"}, slot))
        assert {"task": "ag_bug_one", "event": "parked-ended"} in r["reaped"], r
        assert _spawned(r) == ["ag_bug_two"], r
        assert orch.read_counters(slot)["park_released"]["ag_bug_one"]["ended"]
    else:
        # The first tick at the end of the grace starts the waiting task.
        assert _spawned(r) == ["ag_bug_two"], r
        assert _stops(claude) == [] and "park_released" not in c, claude.calls


def _answer(monkeypatch, slot, answered: str, issue: str = Q1) -> None:
    """The human answers ag_bug_one's question (Q7) in the inbox."""
    monkeypatch.setattr(orch._questions, "read_origin", lambda *a, **k: {"ag_bug_one": [
        {"id": "Q7", "shift": slot.name, "issue": issue, "state": "answered",
         "answered": answered, "answer": "(a) yes", "comment": f"{issue}#issuecomment-1"}]})


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
                               slot_name="2026-11-18-pm", parked={"ag_bug_one": " (parked) until 09:15Z"})
    assert kept == [] and out == {
        second: "repo autogalaxy held by ag_bug_one (parked) until 09:15Z"}
    lines = orch._digest.backlog_gate_lines({"backlog_gates": {"origin": out}})
    # Nit 5 (review round 2): a park hold is labelled as one, not as a claim.
    assert [ln for ln in lines if ln.startswith(
        "Repo held by this shift's park on a question: 1 draft(s)")], lines
    assert not [ln for ln in lines if "on Mind origin/main" in ln], lines



# --- review round 2 (2026-11-27): stop, then release -------------------------------

class _StopFails(d.FakeClaude):
    """`claude --bg` works; `claude stop` exits 1."""

    def __call__(self, argv, **kw):
        if argv[:2] == ["claude", "stop"]:
            self.calls.append((argv, kw))
            return d.SimpleNamespace(returncode=1, stdout="", stderr="no such session")
        return super().__call__(argv, **kw)


def test_720_r2_a_failed_stop_keeps_the_lease_parks_hold(tmp_path):
    """Human ruling 2026-11-27 ("Stop, then release"): a lease park whose
    session cannot be stopped keeps its library (fail closed); the stop is
    tried again next tick, and the waiting task starts once it succeeds."""
    mind, brief, home, slot, park, blocked = _lease_park(tmp_path)
    failing = _StopFails()
    r = d._tick(brief, mind, home, park + GRACE, failing, agents=blocked())
    assert _stops(failing) == [_agent(slot, "ag_bug_one")] and _spawned(r) == [], r
    assert {"task": "ag_bug_one", "event": "park-stop-failed",
            "why": "no such session"} in r["reaped"], r
    # Held, and no longer "until" a time: not startable until the stop works.
    assert "ag_bug_two" not in r.get("startable", []), r
    # The plan's reason is the spawn loop's (re-review N4).
    assert _named(brief, home)[B_PATH] == \
        "autogalaxy held by ag_bug_one (parked: its session is not stopped yet)"
    c = orch.read_counters(slot)
    assert orch._held_reason(c, {}, "ag_bug_one", "autogalaxy", park + GRACE) == (
        "autogalaxy held by ag_bug_one (parked: its session is not stopped yet)", False)
    assert "ag_bug_one" in c["parked"] and "park_released" not in c
    assert c["park_stop_failed"]["ag_bug_one"]["why"] == "no such session"
    assert "ag_bug_one" not in orch.released_picks(c, now=park + 2 * GRACE)
    assert orch._library_holder(c, {}, "ag_bug_two", ["autogalaxy"], park + 2 * GRACE) \
        == ("autogalaxy", "ag_bug_one")
    # The next tick's stop works; once its session is seen to end, the
    # waiting task starts.
    claude = d.FakeClaude()
    r = d._tick(brief, mind, home, park + GRACE + MIN, claude, agents=blocked())
    assert _stops(claude) == [_agent(slot, "ag_bug_one")] and _spawned(r) == [], r
    assert "ag_bug_one" not in orch.read_counters(slot).get("park_stop_failed", {})
    r = d._tick(brief, mind, home, park + GRACE + 2 * MIN, d.FakeClaude(),
                agents=d._agents({"ag_bug_one": "stopped"}, slot))
    assert _spawned(r) == ["ag_bug_two"], r


def test_720_r2_an_answer_after_the_stop_restarts_it_only_when_the_library_is_free(
        tmp_path, monkeypatch):
    mind, brief, home, slot, park, blocked = _lease_park(tmp_path)
    r = d._tick(brief, mind, home, park + GRACE, d.FakeClaude(), agents=blocked())
    assert _spawned(r) == [], r
    r = d._tick(brief, mind, home, park + GRACE + MIN, d.FakeClaude(),
                agents=d._agents({"ag_bug_one": "stopped"}, slot))
    assert _spawned(r) == ["ag_bug_two"], r
    # The human answers the lease park's inbox question while ag_bug_two runs.
    _answer(monkeypatch, slot, "2026-11-04T09:35Z", issue=nt.ISSUE)
    both = lambda: d._agents({"ag_bug_one": "stopped", "ag_bug_two": "working"}, slot)
    for at in (park + GRACE + 5 * MIN, park + GRACE + 10 * MIN):
        r = d._tick(brief, mind, home, at, d.FakeClaude(), agents=both())
        assert _spawned(r) == [], r
        assert set(orch.active_leases(slot)) == {"ag_bug_two"}     # never two on a library
        assert "ag_bug_one" in orch.read_counters(slot)["inshift_pending"]
    assert "ag_bug_one" not in orch.leases(slot)      # the stopped lease was reaped
    (slot / "leases" / "ag_bug_two.done").write_text(f"{PR2}\n")
    claude = d.FakeClaude()
    r = d._tick(brief, mind, home, park + GRACE + 15 * MIN, claude,
                agents=d._agents({"ag_bug_two": "done"}, slot))
    assert _spawned(r) == ["ag_bug_one"], r
    assert set(orch.active_leases(slot)) == {"ag_bug_one"}
    assert "(a) yes" in claude.calls[-1][0][-1]       # restarted with the answer


def test_720_r2_an_answer_inside_the_grace_keeps_the_library_for_the_restart(
        tmp_path, monkeypatch):
    """Review minor 2: answered inside the grace but held back by
    `max-workers`, the parked task keeps its library past the grace, so a
    task waiting on that library cannot start ahead of it."""
    mind, brief, home = nt._shift(tmp_path)
    rels = []
    for name, target in (("ag_bug_one", "autogalaxy"), ("ag_bug_two", "autogalaxy"),
                         ("heart_one", "PyAutoHeart"), ("heart_two", "PyAutoHeart")):
        rel = nt._write(mind, name, target=target)
        f = mind / rel
        f.write_text(f.read_text().replace("Consequence: notify", "Consequence: glance"))
        rels.append(rel)
    brief.write_text(brief.read_text().replace("max-workers: 4", "max-workers: 2").replace(
        "    - draft/feature/x/none.md", "\n".join(f"    - {r}" for r in rels)))
    slot = orch.slot_dir(brief, home)
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert _spawned(r) == ["ag_bug_one", "heart_one"], r
    # 09:02Z: ag_bug_one ends on a question; heart_two takes the free slot.
    (slot / "leases" / "ag_bug_one.done").write_text(f"question: {Q1}\n")
    park = NOW + 2 * MIN
    r = d._tick(brief, mind, home, park, d.FakeClaude(),
                agents=d._agents({"ag_bug_one": "done", "heart_one": "working"}, slot))
    assert _spawned(r) == ["heart_two"], r
    hearts = lambda: d._agents({"heart_one": "working", "heart_two": "working"}, slot)
    # 09:08Z, inside the grace: answered, but both worker slots are full.
    _answer(monkeypatch, slot, "2026-11-04T09:08Z")
    r = d._tick(brief, mind, home, park + 6 * MIN, d.FakeClaude(), agents=hearts())
    assert _spawned(r) == [] and "ag_bug_one" in \
        orch.read_counters(slot)["inshift_pending"], r
    # Past the grace it still holds autogalaxy for its restart.
    r = d._tick(brief, mind, home, park + GRACE + MIN, d.FakeClaude(), agents=hearts())
    assert _spawned(r) == [], r
    c = orch.read_counters(slot)
    assert "ag_bug_one" in c["inshift_pending"]
    assert "ag_bug_one" not in orch.released_picks(c, now=park + 2 * GRACE)
    assert orch._library_holder(c, {}, "ag_bug_two", ["autogalaxy"], park + 2 * GRACE) \
        == ("autogalaxy", "ag_bug_one")
    assert orch._held_reason(c, {}, "ag_bug_one", "autogalaxy", park + 2 * GRACE) == (
        "autogalaxy held by ag_bug_one (answered: it restarts first)", False)
    # A worker slot frees: the answered task restarts, never the one behind it.
    (slot / "leases" / "heart_one.done").write_text(f"{PR2}\n")
    r = d._tick(brief, mind, home, park + GRACE + 3 * MIN, d.FakeClaude(),
                agents=d._agents({"heart_one": "done", "heart_two": "working"}, slot))
    assert _spawned(r) == ["ag_bug_one"], r


@nt.sf.needs_git
def test_720_r2_a_park_label_only_when_no_other_claim_holds_the_repo(tmp_path):
    """Review minor 4: a draft waits "(parked) until" only when, the parked
    task's own claim aside, nothing holds its repo; another claim is final."""
    mind, second, claim = nt._claimed_galaxy_mind(tmp_path)
    first = "draft/feature/x/ag_bug_one.md"
    (mind / "active.md").write_text(
        f"# Active\n\n## ag-bug-one\n- prompt: {first}\n"
        "- session: shift worker 2026-11-18-pm (abc123)\n"
        "- repos:\n  - autogalaxy: feature/ag-bug-one\n\n"
        "## human-other\n- prompt: active/other.md\n- session: desktop session, human\n"
        "- repos:\n  - autogalaxy: feature/human-other\n")
    nt.sf.push(mind, "two claims")
    records = [nt._batch.grade(mind / second, mind)]
    kept, out = orch.on_origin(records, mind, own={"ag_bug_one"}, released=set(),
                               slot_name="2026-11-18-pm", parked={"ag_bug_one": " (parked) until 09:15Z"})
    assert kept == [] and out == {second: "repo autogalaxy claimed by `human-other` in "
                                          "active.md on Mind origin/main"}
    lines = orch._digest.backlog_gate_lines({"backlog_gates": {"origin": out}})
    assert [ln for ln in lines if ln.startswith("Repo claimed on Mind origin/main: 1 ")], lines



# --- review round 3 (2026-11-27) -----------------------------------------------------

def _stop_and_end(brief, mind, home, slot, at, task="ag_bug_one", others=None):
    """`at` is `task`'s grace end: its session is stopped that tick, nothing
    else on its library starts; the next tick the reap sees it end."""
    claude = d.FakeClaude()
    r = d._tick(brief, mind, home, at, claude,
                agents=d._agents({task: "blocked", **(others or {})}, slot))
    assert _stops(claude) == [_agent(slot, task)], claude.calls
    assert _spawned(r) == [], r
    return d._tick(brief, mind, home, at + MIN, d.FakeClaude(),
                   agents=d._agents({task: "stopped", **(others or {})}, slot))


def test_720_r3_a_second_lease_park_of_the_task_is_stopped_at_its_own_grace_end(
        tmp_path, monkeypatch):
    """Re-review N1: the stop records of a first park never exempt a second
    park of the same task from the stop."""
    mind, brief, home = nt._galaxy_shift(tmp_path, names=(*nt.GALAXY, "ag_bug_three"))
    slot = orch.slot_dir(brief, home)
    blocked = lambda: d._agents({"ag_bug_one": "blocked"}, slot)
    d._tick(brief, mind, home, NOW + MIN, d.FakeClaude(), agents=blocked())
    park = NOW + MIN + _dt.timedelta(seconds=orch.STALL_GRACE_S)
    d._tick(brief, mind, home, park, d.FakeClaude(), agents=blocked())
    r = _stop_and_end(brief, mind, home, slot, park + GRACE)
    assert _spawned(r) == ["ag_bug_two"], r
    # Answered; ag_bug_two ends and the answered task restarts before ag_bug_three.
    _answer(monkeypatch, slot, "2026-11-04T09:33Z", issue=nt.ISSUE)
    (slot / "leases" / "ag_bug_two.done").write_text(f"{PR2}\n")
    t = park + GRACE + 3 * MIN
    r = d._tick(brief, mind, home, t, d.FakeClaude(),
                agents=d._agents({"ag_bug_two": "done"}, slot))
    assert _spawned(r) == ["ag_bug_one"], r
    c = orch.read_counters(slot)
    assert "ag_bug_one" not in c.get("park_released", {})
    # It blocks again and is parked a second time.
    d._tick(brief, mind, home, t + MIN, d.FakeClaude(), agents=blocked())
    park2 = t + MIN + _dt.timedelta(seconds=orch.STALL_GRACE_S)
    r = d._tick(brief, mind, home, park2, d.FakeClaude(), agents=blocked())
    assert {"task": "ag_bug_one", "event": "parked"}.items() <= r["reaped"][0].items(), r
    for at in (park2 + MIN, park2 + GRACE - MIN):
        r = d._tick(brief, mind, home, at, d.FakeClaude(), agents=blocked())
        assert _spawned(r) == [] and "ag_bug_three" in r.get("startable", []), r
    # Its own grace end: stopped first; ag_bug_three only after it has ended.
    r = _stop_and_end(brief, mind, home, slot, park2 + GRACE)
    assert _spawned(r) == ["ag_bug_three"], r


def test_720_r3_the_stop_files_the_newest_blocked_question_into_the_outcome(tmp_path):
    """Re-review N3: the stopped task's open question is its newest `blocked`
    inbox entry, added to an outcome it already has."""
    mind, brief, home, slot, park, blocked = _lease_park(tmp_path)
    c = orch.read_counters(slot)
    old, new = "https://github.com/example-org/autogalaxy/issues/1", nt.ISSUE
    other = "https://github.com/example-org/autogalaxy/issues/2"
    for q in c["inbox"]:
        if q["task"] == "ag_bug_one":
            q["asked"] = "2026-11-04T09:16Z"
    c["inbox"] = [{"task": "ag_bug_one", "issue": other, "kind": "question",
                   "asked": "2026-11-04T09:20Z"},
                  *c["inbox"],
                  {"task": "ag_bug_one", "issue": old, "kind": "blocked",
                   "asked": "2026-11-04T08:40Z"}]
    c["outcomes"]["ag_bug_one"] = {"prs": [PR2], "merged": [], "issues": []}
    orch._write_counters(slot, c)
    r = d._tick(brief, mind, home, park + GRACE, d.FakeClaude(), agents=blocked())
    assert {"task": "ag_bug_one", "event": "park-stopped", "issue": new} in r["reaped"], r
    o = orch.read_counters(slot)["outcomes"]["ag_bug_one"]
    assert o["questions"] == [new] and o["prs"] == [PR2], o
    assert orch._open_question(o)


def test_720_r3_a_stopped_session_that_never_ends_stops_holding_the_shift_open(tmp_path):
    """Re-review N5: a stopped session not seen to end within
    `PARK_STOP_END_S` is said once (needs you); the library stays held, and
    the waiting task is no longer startable, so the shift may close early."""
    mind, brief, home, slot, park, blocked = _lease_park(tmp_path)
    r = d._tick(brief, mind, home, park + GRACE, d.FakeClaude(), agents=blocked())
    wait = _dt.timedelta(seconds=orch.PARK_STOP_END_S)
    assert wait == 10 * MIN
    r = d._tick(brief, mind, home, park + GRACE + wait - MIN, d.FakeClaude(),
                agents=blocked())
    assert _spawned(r) == [] and "ag_bug_two" in r.get("startable", []), r
    r = d._tick(brief, mind, home, park + GRACE + wait, d.FakeClaude(), agents=blocked())
    assert [e for e in r["reaped"] if e.get("event") == "park-stop-overdue"] == [
        {"task": "ag_bug_one", "event": "park-stop-overdue",
         "why": "its session has not ended 10 minutes after the stop"}], r
    assert _spawned(r) == [] and "ag_bug_two" not in r.get("startable", []), r
    assert _named(brief, home)[B_PATH] == \
        "autogalaxy held by ag_bug_one (parked: stopped, but its session has not ended)"
    c = orch.read_counters(slot)
    assert orch._library_holder(c, {}, "ag_bug_two", ["autogalaxy"],
                                park + GRACE + 2 * wait) == ("autogalaxy", "ag_bug_one")
    # Said once.
    r = d._tick(brief, mind, home, park + GRACE + wait + MIN, d.FakeClaude(),
                agents=blocked())
    assert not [e for e in r["reaped"] if e.get("event") == "park-stop-overdue"], r
    # Seen to end at last: released.
    r = d._tick(brief, mind, home, park + GRACE + wait + 2 * MIN, d.FakeClaude(),
                agents=d._agents({"ag_bug_one": "stopped"}, slot))
    assert _spawned(r) == ["ag_bug_two"], r


def test_720_r3_the_plan_and_the_spawn_loop_give_one_wording():
    """Re-review N4: the planner's held reason is the spawn loop's."""
    c = {"done": ["a"], "picks": {"a": {"repos": ["autogalaxy"]}}, "parked": [],
         "pending_redispatch": [], "inshift_pending": {"a": {"ids": ["Q7"]}},
         "outcomes": {"a": {"prs": [], "merged": [], "questions": [Q1]}},
         "park_times": {"a": "2026-11-04T09:00:00Z"}}
    holds = orch.park_hold_reasons(c, set(), NOW + 30 * MIN)
    assert holds == {"a": (" (answered: it restarts first)", False)}
    assert orch._held_reason(c, {}, "a", "autogalaxy", NOW + 30 * MIN)[0] == \
        "autogalaxy held by a" + holds["a"][0]


# --- the 2026-11-24-am replay ----------------------------------------------------
#
# The facts of shift 2026-11-24-am that bear on the hold (slot counters,
# events and brief): window 08:00Z-09:30Z, max-workers 2, merge-cap 0.
# `substructure_util_zero_padded_halo_slots_make` (autogalaxy + autolens)
# started 08:28:39Z and ended with an open question in its outcome, read at
# the 08:32:52Z tick (PARKED-ON-ISSUE). That tick also started
# `smoke_cache_stats_warnings_nameerror` (pyautoheart, not a library), which
# parked on its own question at 08:34:47Z. Two earlier picks had finished
# with PRs open on the same libraries, left for the human's /prm:
# `colab_links_pinned_to_blob_main_in` (autogalaxy + autolens; glance) and
# `zero_contour_grad_fails_on_jax_0_12` (autogalaxy; judge). Behind the park
# waited `mge_deflections_reverse_mode_nan_at_grid_centre` (autogalaxy) and
# `jit_cache_not_hit_modeling_visualization` (autolens); with no worker left
# live the shift closed early at 08:34:47Z, neither started.
# Simplified: smoke_cache's start is modelled as a plain named task (it was
# resumed after an earlier shift's answer, which holds no library), and every
# finished pick's PR is recorded as refused for the human's /prm (some were
# waiting in merge order behind one; neither holds a start). Placeholder org,
# issues and PRs; the task slugs and repos are the shift's.

PARK_TASK = "substructure_util_zero_padded_halo_slots_make"
HEART_TASK = "smoke_cache_stats_warnings_nameerror"
HELD = {"mge_deflections_reverse_mode_nan_at_grid_centre": "autogalaxy",
        "jit_cache_not_hit_modeling_visualization": "autolens"}
AM24_Q = "https://github.com/example-org/autolens/issues/871"
AM24_HEART_Q = "https://github.com/example-org/pyautoheart/issues/365"
_PR = "https://github.com/example-org/{}/pull/{}"
#: The finished picks: {task: (repos, tier, {PR: why it waits for the human})}.
FINISHED = {
    "colab_links_pinned_to_blob_main_in": (
        ["autogalaxy", "autolens", "howtogalaxy", "howtolens"], "glance",
        {_PR.format("autogalaxy", 751): "merge-cap 0 reached this shift — left for your /prm",
         _PR.format("autolens", 880): "merge-cap 0 reached this shift — left for your /prm",
         _PR.format("howtogalaxy", 108): "merge-cap 0 reached this shift — left for your /prm",
         _PR.format("howtolens", 138): "merge-cap 0 reached this shift — left for your /prm"}),
    "zero_contour_grad_fails_on_jax_0_12": (
        ["autogalaxy"], "judge",     # its workspace-test repos hold no library
        {_PR.format("autogalaxy", 750): "tier judge — never merged unattended → your /prm"}),
}
AM24_START = _dt.datetime(2026, 11, 24, 8, 28, 39, tzinfo=_dt.UTC)
AM24_PARK = _dt.datetime(2026, 11, 24, 8, 32, 52, tzinfo=_dt.UTC)
AM24_CLOSED_EARLY = _dt.datetime(2026, 11, 24, 8, 34, 47, tzinfo=_dt.UTC)


def _glance(mind, task, repos) -> str:
    rel = nt._write(mind, task, target=repos[0])
    f = mind / rel
    text = f.read_text().replace("Consequence: notify", "Consequence: glance")
    f.write_text(text.replace(f"Repos:\n- {repos[0]}\n",
                              "Repos:\n" + "".join(f"- {r}\n" for r in repos)))
    return rel


def _am24_shift(tmp_path):
    """The 11-24-am brief cut to the tasks that bear on the hold, first tick
    run: the parking task is live on autogalaxy and autolens, both held
    tasks wait, and the two finished picks' PRs are open for the /prm."""
    mind, brief, home = nt._shift(tmp_path)
    rels = [_glance(mind, task, repos)
            for task, repos in ((PARK_TASK, ("autogalaxy", "autolens")),
                                *((t, (r,)) for t, r in HELD.items()))]
    # smoke_cache's draft appears at 08:32:52Z, when it started.
    rels.append(f"draft/feature/x/{HEART_TASK}.md")
    text = brief.read_text().replace("Batch 2026-11-04 am", "Batch 2026-11-24 am")
    for old, new in (("2026-11-04T08:30Z", "2026-11-24T08:00Z"),
                     ("2026-11-04T11:30Z", "2026-11-24T09:30Z"),
                     ("max-workers: 4", "max-workers: 2"),
                     ("    - draft/feature/x/none.md", "\n".join(f"    - {r}" for r in rels))):
        assert old in text, old
        text = text.replace(old, new)
    assert "merge-cap: 0" in text
    brief.write_text(text)
    slot = orch.slot_dir(brief, home)
    slot.mkdir(parents=True, exist_ok=True)
    r = d._tick(brief, mind, home, AM24_START, d.FakeClaude())
    assert _spawned(r) == [PARK_TASK], r
    c = orch.read_counters(slot)
    for task, (repos, tier, prs) in FINISHED.items():
        c["picks"][task] = {"prompt": f"draft/feature/x/{task}.md", "repos": repos,
                            "size": "small", "tier": tier, "title": task, "why": "named task"}
        c["done"].append(task)
        c["outcomes"][task] = {"prs": list(prs), "merged": [], "issues": []}
        for pr, why in prs.items():
            c["closeouts"][pr] = {"task": task, "state": "refused", "why": why}
    orch._write_counters(slot, c)
    return mind, brief, home, slot


def test_720_replay_2026_11_24_am_the_held_tasks_start_15_minutes_after_the_park(tmp_path):
    mind, brief, home, slot = _am24_shift(tmp_path)
    assert orch.read_counters(slot)["picks"][PARK_TASK]["repos"] == ["autogalaxy", "autolens"]
    # The finished picks with open PRs hold no library for a start.
    assert set(FINISHED) <= orch.released_picks(orch.read_counters(slot), now=AM24_START)
    # 08:32:52Z: the worker has ended with an open question (PARKED-ON-ISSUE),
    # and smoke_cache starts on pyautoheart.
    _glance(mind, HEART_TASK, ("PyAutoHeart",))
    (slot / "leases" / f"{PARK_TASK}.done").write_text(f"question: {AM24_Q}\n")
    r = d._tick(brief, mind, home, AM24_PARK, d.FakeClaude(),
                agents=d._agents({PARK_TASK: "done"}, slot))
    assert {"task": PARK_TASK, "event": "done"} in r["reaped"], r
    assert _spawned(r) == [HEART_TASK], r
    assert orch.park_time(orch.read_counters(slot), PARK_TASK) == AM24_PARK
    # 08:34:47Z, when the shift closed early: smoke_cache parks on its own
    # question, and no worker is left live.
    (slot / "leases" / f"{HEART_TASK}.done").write_text(f"question: {AM24_HEART_Q}\n")
    agents = {HEART_TASK: "done"}
    # Then and at park + 14 min: held but startable, so the shift stays open;
    # the reason says when the hold ends.
    for at in (AM24_CLOSED_EARLY, AM24_PARK + GRACE - MIN):
        r = d._tick(brief, mind, home, at, d.FakeClaude(), agents=d._agents(agents, slot))
        agents = {}
        assert _spawned(r) == [] and orch.active_leases(slot) == {}, r
        assert set(HELD) <= set(r.get("startable", [])), r
        c = orch.read_counters(slot)
        assert c["outcomes"][HEART_TASK]["questions"] == [AM24_HEART_Q]
        assert not orch.early_close_ready(slot, c, r), r
        assert "closed_early" not in c, c
        for task, repo in HELD.items():
            assert _named(brief, home)[f"draft/feature/x/{task}.md"] == \
                f"{repo} held by {PARK_TASK} (parked) until 08:48Z"
    # Park + 15 min (08:47:52Z): both held tasks start, one per library.
    r = d._tick(brief, mind, home, AM24_PARK + GRACE, d.FakeClaude(),
                agents=d._agents({}, slot))
    assert sorted(_spawned(r)) == sorted(HELD), r
    assert set(orch.active_leases(slot)) == set(HELD)
