"""PyAutoBrain#644 (M3.4, Build A): the shift's event stream, `events.jsonl`.

The watcher appends one JSON line per new event from what each tick already
did (`_events.record_tick`, inside the tick lock): no new reads, no
subprocess, no LLM. These tests hold the schema, the dedup (one `cap` line
for 20 identical refusal ticks; no repeat after a crash between the append
and the state write), every kind, the needs-you comments (human ruling H4b)
and a replay of the real shift B tick log (2026-11-14-pm3).
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_dispatch as d  # noqa: E402 — the 3b fixtures
from test_orchestrator_dispatch import orch  # noqa: E402
import _events  # noqa: E402

NOW = d.NOW
FIXTURE = BRAIN / "tests" / "fixtures" / "shift_2026-11-14-pm3"
PR = "https://github.com/example-org/example-lib/pull/901"
PR2 = "https://github.com/example-org/other-lib/pull/904"
ISSUE = "https://github.com/example-org/example-workspace/issues/670"
INFO = {"review_at": "2026-11-04T11:30Z", "named": 2, "merge_cap": 2, "token_budget": "400000"}


def _at(minutes: float) -> _dt.datetime:
    return NOW + _dt.timedelta(minutes=minutes)


def _slot(tmp_path) -> Path:
    slot = tmp_path / "2026-11-04-am"
    slot.mkdir()
    return slot


def _counters(**kw) -> dict:
    c = {"picks": {"t1": {"tier": "glance", "why": "named task", "title": "Fix the fixture"},
                   "t2": {"tier": "notify", "why": "queue.md #2"}},
         "outcomes": {}, "closeouts": {}, "dropped": {}, "commands": [], "parked": []}
    c.update(kw)
    return c


def _record(slot, minutes, result, counters=None, **kw):
    return orch._events.record_tick(slot, _at(minutes), result,
                                    counters if counters is not None else _counters(),
                                    info=INFO, **kw)


# --- the schema --------------------------------------------------------------------

def test_every_line_has_the_v1_schema_and_seq_has_no_gaps(tmp_path):
    slot = _slot(tmp_path)
    _record(slot, 0, {"action": "ticked", "spawned": [{"task": "t1"}, {"task": "t2"}],
                      "refused": [{"task": "t3", "why": "max-workers 2 reached"}]})
    _record(slot, 3, {"action": "ticked", "reaped": [{"task": "t2", "event": "dead",
                                                     "redispatch": "allowed"}],
                      "spawned": [{"task": "t2"}]})
    events = _events.read_events(slot)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert [e["kind"] for e in events] == ["shift-open", "spawned", "spawned", "cap",
                                           "crashed", "redispatched"]
    for e in events:
        assert set(e) >= {"v", "seq", "at", "slot", "kind", "key", "line", "needs_you"}
        assert e["v"] == 1 and e["slot"] == "2026-11-04-am" and e["kind"] in _events.KINDS
        assert isinstance(e["needs_you"], bool) and len(e["line"]) <= _events.LINE_MAX
    raw = (slot / _events.EVENTS_FILE).read_bytes().split(b"\n")
    assert raw[-1] == b"" and all(len(x) < _events.RECORD_MAX for x in raw)
    assert events[0]["line"] == ("Shift 2026-11-04-am open until 11:30Z: 2 named tasks, "
                                 "merge-cap 2, 400000 token budget.")
    assert events[1]["line"] == "Started Fix the fixture (t1) (glance; named task)."
    assert events[4]["key"] == "crashed:t2:1" and events[5]["key"] == "redispatched:t2"


def test_a_line_never_carries_an_at_sign_and_is_truncated(tmp_path):
    slot = _slot(tmp_path)
    ack = "ignored: " + "@someone " * 80
    _record(slot, 0, {"action": "ticked", "commands": [
        {"command": "drop", "arg": "x", "ack": ack, "id": "9", "by": "example-human"}]})
    (e,) = [e for e in _events.read_events(slot) if e["kind"] == "steer"]
    assert "@s" not in e["line"] and "@​s" in e["line"]
    assert len(e["line"]) == _events.LINE_MAX and e["needs_you"]


def test_twenty_identical_refusal_ticks_give_one_cap_line(tmp_path):
    slot = _slot(tmp_path)
    refused = [{"task": f"t{i}", "why": "max-sessions 4 reached"} for i in range(3)]
    for m in range(20):
        _record(slot, m * 3, {"action": "ticked", "refused": refused})
    caps = [e for e in _events.read_events(slot) if e["kind"] == "cap"]
    assert [e["line"] for e in caps] == ["max-sessions 4 reached: 3 tasks wait."]


def test_a_task_refusal_is_one_line_per_task_and_class(tmp_path):
    slot = _slot(tmp_path)
    for m in range(5):
        _record(slot, m, {"action": "ticked", "refused": [
            {"task": "t1", "why": "spawn failed: claude --bg failed: boom"}]})
    refusals = [e for e in _events.read_events(slot) if e["kind"] == "refused"]
    assert [e["line"] for e in refusals] == ["t1 not started: spawn failed."]


def test_a_crash_between_the_append_and_the_state_write_repeats_nothing(tmp_path):
    slot = _slot(tmp_path)
    first = _record(slot, 0, {"action": "ticked", "spawned": [{"task": "t1"}],
                              "health": {PR: "HEALTHY"},
                              "closeouts": {"started": [PR], "merged": [], "refused": []}})
    # The tick dies after its append, before the state write: the state is lost.
    (slot / _events.STATE_FILE).unlink()
    # The next tick reads the same CI verdict again: the file's keys dedup it.
    again = _record(slot, 3, {"action": "ticked", "health": {PR: "HEALTHY"}})
    assert again == [] and len(_events.read_events(slot)) == len(first)
    nxt = _record(slot, 6, {"action": "ticked", "spawned": [{"task": "t2"}]})
    assert [e["seq"] for e in nxt] == [len(first) + 1]              # no seq reused


def test_a_torn_last_line_is_skipped_and_never_joined(tmp_path):
    slot = _slot(tmp_path)
    _record(slot, 0, {"action": "ticked", "spawned": [{"task": "t1"}]})
    with open(slot / _events.EVENTS_FILE, "ab") as fh:
        fh.write(b'{"v": 1, "seq": 99, "kind": "spaw')          # a write cut short
    assert [e["seq"] for e in _events.read_events(slot)] == [1, 2]
    _record(slot, 1, {"action": "ticked", "spawned": [{"task": "t2"}]})
    assert [e["seq"] for e in _events.read_events(slot)] == [1, 2, 3]


def test_record_tick_makes_no_subprocess_or_network_call(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("record_tick made a subprocess or network call")
    for name in ("run", "Popen", "check_output", "call"):
        monkeypatch.setattr(subprocess, name, boom)
    import socket
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(orch, "AgentsView", boom)
    monkeypatch.setattr(orch._digest, "pr_health", boom)
    slot = _slot(tmp_path)
    _record(slot, 0, _every_kind_results()[0][1])


# --- every kind ---------------------------------------------------------------------

def _every_kind_results():
    """(minutes, result, counters) producing every kind once."""
    c = _counters(
        outcomes={"t1": {"prs": [PR], "merged": []},
                  "t2": {"prs": [], "merged": [], "issues": [ISSUE], "questions": [ISSUE]},
                  "t4": {"prs": [], "merged": [], "issues": [], "obsolete": "already on main"}},
        closeouts={PR: {"task": "t1", "state": "merged"},
                   PR2: {"task": "t5", "state": "refused", "why": "merged outside the close-out",
                         "github": {"mergedBy": "someone"}},
                   "https://github.com/o/r/pull/3": {"task": "t6", "state": "refused",
                                                     "why": "CI FAILED — never merged unattended"},
                   "https://github.com/o/r/pull/4": {"task": "t7", "state": "refused",
                                                     "why": "merge-cap 2 reached this shift"}},
        dropped={"t5": {"by": "h", "at": "x"}}, commands_unread="2026-11-04T09:00:00Z")
    return [
        (0, {"action": "ticked", "spawned": [{"task": "t1"}, {"task": "t2"}, {"task": "t3"}],
             "refused": [{"task": "t7", "why": "max-workers 2 reached"},
                         {"task": "t9", "why": "spawn failed: no"}],
             "commands": [{"command": "cap", "arg": "merges x", "ack": "ignored: /cap needs a "
                           "whole number", "id": "1", "by": "example-human"}]}, c),
        (3, {"action": "ticked",
             "reaped": [{"task": "t1", "event": "done"}, {"task": "t2", "event": "done"},
                        {"task": "t4", "event": "done"},
                        {"task": "t3", "event": "dead", "redispatch": "allowed"},
                        {"task": "t8", "event": "parked", "why": "blocked since 2026-11-04T09:01:00Z"}],
             "spawned": [{"task": "t3"}], "health": {PR: "HEALTHY", "https://github.com/o/r/pull/3": "FAILED"},
             "closeouts": {"started": [PR], "merged": [], "refused": ["https://github.com/o/r/pull/3"]},
             "github_auth": {"error": "no installation token", "writes": "held"},
             "ledger": {"committed": None, "set_aside": [{"op": "remove", "file": "1.json",
                                                         "why": "missing"}]}}, c),
        (6, {"action": "ticked",
             "closeouts": {"started": [], "merged": [PR], "refused": [PR2, "https://github.com/o/r/pull/4"],
                           "merged_outside": [PR2]}}, c),
        (9, {"action": "ticked"}, c),
        (12, {"action": "stopped", "reason": "STOP written by /stop"}, c),
        (180, {"action": "digest", "post": {"posted": True, "url": "https://github.com/o/m/issues/1#issuecomment-5"}}, c),
        (183, {"action": "late", "late": ["- late: t8 — https://github.com/o/r/pull/7 (after review-at, 2026-11-04T12:33:00Z)"]}, c),
    ]


def test_every_kind_is_written(tmp_path):
    slot = _slot(tmp_path)
    runs = _every_kind_results()
    for i, (minutes, result, counters) in enumerate(runs):
        _record(slot, minutes, result, counters, quiet=i == len(runs) - 1)
    events = _events.read_events(slot)
    assert {e["kind"] for e in events} == set(_events.KINDS)
    by: dict = {}
    for e in events:
        by.setdefault(e["kind"], e)                   # the first of each kind
    assert by["pr-opened"]["line"] == "t1 opened example-lib#901 (glance: close-out when CI is green)."
    assert by["question"]["line"] == "t2 parked with a question on example-workspace#670."
    assert by["finished"]["line"] == "t4 finished: Obsolete — nothing to do."
    assert by["parked"]["line"] == "t8 is stuck at a prompt (since 09:01Z)."
    assert by["merged"]["line"] == "Merged example-lib#901 unattended (1 of merge-cap 2)."
    assert by["merged-outside"]["needs_you"]          # its task was /dropped
    assert [e["line"] for e in events if e["kind"] == "ci"] == [
        "CI green on example-lib#901.", "CI red on r#3: never merged unattended."]
    assert by["cap"]["line"] == "max-workers 2 reached: 1 task wait."
    assert any(e["line"] == "merge-cap 2 reached: later green PRs wait for /prm." for e in events)
    assert by["refused"]["line"] == "t9 not started: spawn failed."
    assert by["steer-unread"]["needs_you"] and by["impaired"]["needs_you"]
    assert by["steer"]["needs_you"]                   # an `ignored:` ack
    assert by["late"]["line"] == "Late arrival: t8 — https://github.com/o/r/pull/7 after review-at."
    assert by["digest"]["url"].endswith("#issuecomment-5")
    assert events[-1]["kind"] == "shift-end"
    assert not {k for k in ("shift-open", "spawned", "ci", "merged") if by[k]["needs_you"]}


def test_shift_end_waits_until_nothing_is_left(tmp_path):
    slot = _slot(tmp_path)
    _record(slot, 0, {"action": "digest", "post": {"posted": True, "url": "u"}}, quiet=False)
    assert [e["kind"] for e in _events.read_events(slot)] == ["digest"]
    _record(slot, 5, {"action": "late", "late": []}, quiet=False)
    _record(slot, 8, {"action": "late", "late": []}, quiet=True)
    assert [e["kind"] for e in _events.read_events(slot)] == ["digest", "shift-end"]


def test_steer_unread_needs_three_ticks_in_a_row(tmp_path):
    slot = _slot(tmp_path)
    unread = _counters(commands_unread="2026-11-04T09:00:00Z")
    for m in (0, 3):
        _record(slot, m, {"action": "ticked"}, unread)
    _record(slot, 6, {"action": "ticked"}, _counters())          # a read worked: the run resets
    for m in (9, 12):
        _record(slot, m, {"action": "ticked"}, unread)
    assert not [e for e in _events.read_events(slot) if e["kind"] == "steer-unread"]
    _record(slot, 15, {"action": "ticked"}, unread)
    (e,) = [e for e in _events.read_events(slot) if e["kind"] == "steer-unread"]
    assert e["needs_you"] and "since 09:00Z" in e["line"]


def test_a_kill_is_named_and_a_spent_retry_is_said(tmp_path):
    slot = _slot(tmp_path)
    _record(slot, 0, {"action": "ticked", "spawned": [{"task": "t1"}]})
    _record(slot, 3, {"action": "ticked", "reaped": [
        {"task": "t1", "event": "dead", "redispatch": "allowed", "killed": True}],
        "spawned": [{"task": "t1"}]})
    _record(slot, 6, {"action": "ticked", "reaped": [
        {"task": "t1", "event": "dead", "redispatch": "spent — abandoned"}]})
    lines = [e["line"] for e in _events.read_events(slot) if e["kind"] == "crashed"]
    assert lines == ["Worker on t1 stopped by /kill. It restarts once.",
                     "Worker on t1 died. Retry spent: left for your /prm."]


# --- the replay: shift B, 2026-11-14-pm3 ---------------------------------------------

def test_replay_of_shift_b_gives_the_designed_events_and_a_final_digest(tmp_path):
    """The real `tick.log` of shift B (read-only copy; `counters.json` trimmed
    to what the lines need) replays to the events of DESIGN §1.3, in order,
    then the digest and `shift-end`. Old `done` reaps carry no outcome fields:
    the deriver reads the outcome from the counters."""
    counters = json.loads((FIXTURE / "counters.json").read_text())
    log = [json.loads(x) for x in (FIXTURE / "tick.log").read_text().splitlines()]
    slot = tmp_path / "2026-11-14-pm3"
    slot.mkdir()
    for r in log:
        now = _dt.datetime.fromisoformat(r["at"].replace("Z", "+00:00"))
        _events.record_tick(slot, now, r, counters, quiet=True,
                            info={"review_at": "2026-11-14T21:20Z", "merge_cap": 2})
    events = _events.read_events(slot)
    got = [(e["kind"], e.get("task") or e.get("pr") or "") for e in events]
    # Names come from the fixture itself (the tenant firewall: none typed here).
    first, second = sorted(counters["closeouts"])            # the two PRs, as the log opened them
    (model,) = counters["redispatched"]                       # killed by hand, re-dispatched
    (md,) = counters["dropped"]                               # dropped by /drop
    (plot,) = [t for t, o in counters["outcomes"].items() if o["prs"]]
    login = counters["commands"][0]["by"]
    assert got == [
        ("shift-open", ""), ("spawned", plot), ("spawned", model), ("cap", ""),
        ("crashed", model), ("redispatched", model),
        ("question", model), ("spawned", md),
        ("question", md), ("steer", ""), ("cap", ""),
        ("pr-opened", plot), ("pr-opened", plot), ("closeout-started", plot),
        ("refused", plot), ("closeout-started", plot), ("refused", plot),
        ("digest", ""), ("shift-end", "")]
    by_key = {e["key"]: e for e in events}
    crashed = by_key[f"crashed:{model}:1"]
    assert crashed["at"] == "2026-11-14T20:17:21Z" and not crashed["needs_you"]
    assert crashed["line"] == f"Worker on {model} died. It restarts once."
    assert by_key[f"redispatched:{model}"]["line"] == f"Restarted {model} (its one retry)."
    refused = by_key[f"refused:{first}"]
    assert refused["at"] == "2026-11-14T20:32:54Z" and refused["cls"] == "decision-taken label"
    assert refused["line"] == (f"Not merging {_events.ref(first)}: decision-taken label. "
                               "Left for your /prm.")
    assert by_key[f"refused:{second}"]["cls"] == "decision-taken label"
    assert by_key["cap:max-workers 2 reached"]["line"] == "max-workers 2 reached: 13 tasks wait."
    assert by_key["cap:max-sessions 4 reached"]["line"] == "max-sessions 4 reached: 12 tasks wait."
    steer = next(e for e in events if e["kind"] == "steer")
    assert steer["line"].startswith(f"/drop {md} from {login}: dropped") and not steer["needs_you"]
    assert by_key["digest"]["line"] == (f"Shift closed. Digest: {log[-1]['post']['url']}. "
                                        "2 tasks parked on a question.")
    # 20 ticks refused the same tasks: one cap line per class, nothing more.
    assert sum(e["kind"] == "cap" for e in events) == 2


# --- the watcher writes it, inside the lock -----------------------------------------------

def test_a_tick_writes_its_events_and_a_quiet_tick_writes_none(tmp_path):
    mind, brief, home = d._shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    claude = d.FakeClaude()
    d._tick(brief, mind, home, NOW, claude)
    kinds = [e["kind"] for e in _events.read_events(slot)]
    assert kinds == ["shift-open", "spawned"]
    d._tick(brief, mind, home, _at(3), claude, agents=d._agents({"t1": "working"}, slot))
    assert [e["kind"] for e in _events.read_events(slot)] == kinds   # nothing new happened
    assert (slot / _events.STATE_FILE).is_file()


def test_the_stop_kill_switch_tick_writes_nothing(tmp_path):
    mind, brief, home = d._shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    slot.mkdir(parents=True)
    (slot / orch.STOP_FILE).write_text("by hand\n")
    assert d._tick(brief, mind, home, NOW, d.FakeClaude())["action"] == "stopped"
    assert not (slot / _events.EVENTS_FILE).exists()


def test_a_failing_deriver_never_fails_the_tick(tmp_path, monkeypatch, capsys):
    mind, brief, home = d._shift(tmp_path)
    monkeypatch.setattr(orch._events, "record_tick",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")))
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert r["action"] == "ticked" and [s["task"] for s in r["spawned"]] == ["t1"]
    assert "events not recorded this tick (bad)" in capsys.readouterr().err


# --- needs-you comments (human ruling H4b) --------------------------------------------------

class Poster:
    def __init__(self):
        self.calls = []

    def __call__(self, issue, body_file):
        self.calls.append((issue, Path(body_file).read_text()))
        return {"posted": True, "url": f"{issue}#issuecomment-{len(self.calls)}"}


def test_needs_you_events_post_at_most_five_comments_and_one_overflow(tmp_path):
    slot = _slot(tmp_path)
    (slot / "counters.json").write_text(json.dumps({}))
    poster = Poster()
    issue = "https://github.com/o/m/issues/1"
    events = [{"seq": i, "kind": "steer", "line": f"/cap from x: ignored: {i} @you",
               "needs_you": True} for i in range(1, 8)]
    events.insert(2, {"seq": 50, "kind": "spawned", "line": "Started t1.", "needs_you": False})
    out = orch._event_comments(slot, events, issue, poster, NOW)
    assert len(poster.calls) == 6 and len(out) == 6
    assert all("@you" not in body for _, body in poster.calls)
    assert "further needs-you events are in the status comment" in poster.calls[-1][1]
    assert "needs you: /cap from x: ignored: 1" in poster.calls[0][1]
    c = orch.read_counters(slot)
    assert c["event_comments"] == 6 and c["pushes"] == 0     # not pushes (review #644)
    # Later ticks post nothing more: the overflow comment was the last.
    more = [{"seq": 90, "kind": "impaired", "line": "x", "needs_you": True}]
    assert orch._event_comments(slot, more, issue, poster, NOW) == [] and len(poster.calls) == 6


def test_no_needs_you_comment_without_an_issue_or_under_stop(tmp_path):
    slot = _slot(tmp_path)
    poster = Poster()
    e = [{"seq": 1, "kind": "impaired", "line": "x", "needs_you": True}]
    assert orch._event_comments(slot, e, "", poster, NOW) == []
    (slot / orch.STOP_FILE).write_text("x")
    assert orch._event_comments(slot, e, "https://github.com/o/m/issues/1", poster, NOW) == []
    assert poster.calls == []


def test_a_failed_needs_you_comment_is_retried_with_the_mentions(tmp_path):
    slot = _slot(tmp_path)
    (slot / "counters.json").write_text(json.dumps({}))
    fails = {"n": 1}

    def poster(issue, body_file):
        if fails["n"]:
            fails["n"] -= 1
            return {"posted": False, "retry": True, "error": "HTTP 502"}
        return {"posted": True, "url": issue + "#issuecomment-2"}
    e = [{"seq": 4, "kind": "impaired", "line": "x", "needs_you": True}]
    orch._event_comments(slot, e, "https://github.com/o/m/issues/1", poster, NOW)
    assert orch.mentions_due(slot)
    c = orch.read_counters(slot)
    orch._retry_mentions(slot, c, poster, NOW)
    assert not orch.mentions_due(slot) and c["event_comments"] == 1 and c["pushes"] == 0


def test_needs_you_comments_never_raise_the_push_finding():
    c = {"pushes": 1, "event_comments": 6, "workers": [], "picks": {}}
    lines = orch._digest.worker_lines(c)
    assert not any("pushes this shift" in x for x in lines)
    assert "- needs-you event comments: 6 (at most 5 + 1 a shift)" in lines
    assert any("2 pushes this shift" in x for x in orch._digest.worker_lines({**c, "pushes": 2}))


def test_a_ci_line_comes_again_after_a_change_and_never_repeats_otherwise(tmp_path):
    slot = _slot(tmp_path)
    for m, v in enumerate(("RUNNING", "HEALTHY", "HEALTHY", "RUNNING", "FAILED", "FAILED",
                           "UNKNOWN", "HEALTHY")):
        _record(slot, m, {"action": "ticked", "health": {PR: v}})
    assert [e["line"] for e in _events.read_events(slot) if e["kind"] == "ci"] == [
        "CI green on example-lib#901.", "CI red on example-lib#901: never merged unattended.",
        "CI green on example-lib#901."]
    (slot / _events.STATE_FILE).unlink()                       # lost: the file knows the last
    _record(slot, 9, {"action": "ticked", "health": {PR: "HEALTHY"}})
    assert sum(e["kind"] == "ci" for e in _events.read_events(slot)) == 3


def test_a_long_key_is_compared_as_stored_and_never_repeats(tmp_path):
    slot = _slot(tmp_path)
    long_task = "t" * 400
    for m in range(4):
        _record(slot, m, {"action": "ticked", "refused": [{"task": long_task, "why": "spawn failed"}]})
    (e,) = [e for e in _events.read_events(slot) if e["kind"] == "refused"]
    assert len(e["key"]) == _events.KEY_MAX


def test_fixture_is_the_real_shift_b_log():
    lines = (FIXTURE / "tick.log").read_text().splitlines()
    assert len(lines) == 23 and json.loads(lines[-1])["action"] == "digest"
    assert shutil.which("python3")
