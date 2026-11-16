"""PyAutoBrain#644 (M3.4, Build A): `batch watch --stream`, the reader of the
shift's `events.jsonl`.

It refuses outside the watch window (`dispatched:` − 30 min to `review-at:` +
45 min), with `STOP` present or after `shift-end`; `--check` stops there. It
prints `attached <slot>: <summary>` (local reads only), the catch-up, then
each new event, and exits 0 at `shift-end`, a hand-written `STOP` or the
window's end, or 3 after `--for` minutes with `segment-end next=--from N`.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_dispatch as d  # noqa: E402 — puts the batch conductor on sys.path
from test_orchestrator_dispatch import orch  # noqa: E402
import _events  # noqa: E402
import _watch  # noqa: E402

UTC = _dt.timezone.utc
DISPATCHED = _dt.datetime(2026, 11, 16, 17, 0, tzinfo=UTC)
REVIEW_AT = _dt.datetime(2026, 11, 16, 19, 0, tzinfo=UTC)

RECORD = """\
# Batch 2026-11-16 pm
- dispatched: {d}
- review-at: {r}
- issue: https://github.com/example-org/example-mind/issues/1
- brief:
  - goals:
    - 1. a shift
  - tasks:
    - draft/feature/pyautobrain/t1.md
  - backlog: none
  - review-minutes: 45
  - lanes: any
  - merge-cap: 2
  - token-budget: 400000
"""


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%MZ")


def _setup(tmp_path, dispatched=DISPATCHED, review_at=REVIEW_AT, counters=True):
    record = tmp_path / "2026-11-16-pm.md"
    record.write_text(RECORD.format(d=_iso(dispatched), r=_iso(review_at)))
    slot = tmp_path / "home" / "2026-11-16-pm"
    slot.mkdir(parents=True)
    if counters:
        c = orch.read_counters(slot)
        pr = "https://github.com/o/r/pull/1"
        c.update(sessions=1, glance_auto_merges=1, outcomes={"t0": {"prs": [pr], "merged": [pr]}})
        orch._write_counters(slot, c)
        (slot / "leases").mkdir()
        (slot / "leases" / "t1.json").write_text(json.dumps({"task": "t1", "agent_id": "abcd1234"}))
    return record, slot


def _emit(slot, minutes, result, **kw):
    return _events.record_tick(slot, DISPATCHED + _dt.timedelta(minutes=minutes), result,
                               {"picks": {}, "outcomes": {}, "closeouts": {}, "dropped": {}},
                               info={"review_at": _iso(REVIEW_AT), "merge_cap": 2}, **kw)


class Clock:
    """A clock that moves `step` minutes each time it is read."""

    def __init__(self, start, step=1.0):
        self.t, self.step = start, _dt.timedelta(minutes=step)

    def __call__(self):
        now = self.t
        self.t += self.step
        return now


def _run(record, slot, clock, *, on_sleep=None, **kw):
    out, err = io.StringIO(), io.StringIO()
    polls = []

    def sleep(s):
        polls.append(s)
        if on_sleep:
            on_sleep(len(polls))
        if len(polls) > 500:
            raise AssertionError("the stream never ended")
    rc = _watch.stream(record, slot, out=out, err=err, clock=clock, sleep=sleep, **kw)
    return rc, out.getvalue(), err.getvalue(), polls


# --- refusals and --check -----------------------------------------------------------

@pytest.mark.parametrize("now,why", [
    (DISPATCHED - _dt.timedelta(minutes=31), "not open yet: attach from 16:30Z"),
    (REVIEW_AT + _dt.timedelta(minutes=46), "watch window is over"),
])
def test_it_refuses_outside_the_window(tmp_path, now, why):
    record, slot = _setup(tmp_path)
    for check in (False, True):
        rc, out, err, _ = _run(record, slot, Clock(now), check=check)
        assert rc == 2 and out == "" and why in err


def test_check_says_attachable_inside_the_window_at_both_edges(tmp_path):
    record, slot = _setup(tmp_path)
    for now in (DISPATCHED - _dt.timedelta(minutes=29), DISPATCHED + _dt.timedelta(minutes=50),
                REVIEW_AT + _dt.timedelta(minutes=44)):
        rc, out, err, polls = _run(record, slot, Clock(now), check=True)
        assert (rc, err, polls) == (0, "", []) and out == f"attachable: {slot.name} ({slot})\n"


def test_it_refuses_with_stop_present_or_after_shift_end(tmp_path):
    record, slot = _setup(tmp_path)
    (slot / orch.STOP_FILE).write_text("by hand\n")
    rc, _, err, _ = _run(record, slot, Clock(DISPATCHED), check=True)
    assert rc == 2 and "STOP present" in err
    (slot / orch.STOP_FILE).unlink()
    _emit(slot, 120, {"action": "digest", "post": {"posted": True, "url": "u"}}, quiet=True)
    rc, _, err, _ = _run(record, slot, Clock(REVIEW_AT + _dt.timedelta(minutes=5)))
    assert rc == 2 and "is over (shift-end written)" in err


# --- attach, catch-up, follow, every exit ---------------------------------------------

def test_attach_summary_makes_no_network_read(tmp_path, monkeypatch):
    record, slot = _setup(tmp_path)

    def boom(*a, **k):
        raise AssertionError("the attach summary made a network read")
    monkeypatch.setattr(orch, "AgentsView", boom)
    monkeypatch.setattr(_watch._digest, "pr_health", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    line = _watch.attach_summary(record, slot)
    assert line == "1 worker live of 2, 1 merged of merge-cap 2, tokens 0 of 400000"
    rc, out, _, _ = _run(record, slot, Clock(DISPATCHED), check=False, for_min=0)
    assert rc == 3 and out.startswith(f"attached {slot.name}: 1 worker live of 2")


def test_it_catches_up_follows_and_exits_at_shift_end(tmp_path):
    record, slot = _setup(tmp_path)
    for m in range(7):
        _emit(slot, m, {"action": "ticked", "spawned": [{"task": f"t{m}"}]})

    def watcher(poll):
        if poll == 1:
            _emit(slot, 30, {"action": "ticked", "commands": [
                {"command": "cap", "arg": "merges x", "ack": "ignored: /cap needs a whole number",
                 "id": "5", "by": "example-human"}]})
        if poll == 3:
            _emit(slot, 120, {"action": "digest", "post": {"posted": True, "url": "https://x/1"}},
                  quiet=True)
    rc, out, _, polls = _run(record, slot, Clock(DISPATCHED + _dt.timedelta(minutes=10)),
                             on_sleep=watcher)
    lines = out.splitlines()
    assert rc == 0 and len(polls) == 3
    assert lines[0].startswith(f"attached {slot.name}: ")
    # The catch-up: the last 5 of 8 events (shift-open + 7 spawns).
    assert lines[1:6] == ["17:02Z Started t2 (?; named in the brief).",
                          "17:03Z Started t3 (?; named in the brief).",
                          "17:04Z Started t4 (?; named in the brief).",
                          "17:05Z Started t5 (?; named in the brief).",
                          "17:06Z Started t6 (?; named in the brief)."]
    assert lines[6] == ("17:30Z NEEDS YOU: /cap merges x from example-human: "
                        "ignored: /cap needs a whole number")
    assert lines[7:] == ["19:00Z Shift closed. Digest: https://x/1.",
                         "19:00Z Shift 2026-11-16-pm over. Nothing is still running."]


def test_from_prints_every_event_after_it_and_json_prints_the_raw_object(tmp_path):
    record, slot = _setup(tmp_path)
    for m in range(7):
        _emit(slot, m, {"action": "ticked", "spawned": [{"task": f"t{m}"}]})
    rc, out, _, _ = _run(record, slot, Clock(DISPATCHED), from_seq=1, for_min=0, as_json=True)
    lines = out.splitlines()
    assert rc == 3 and [json.loads(x)["seq"] for x in lines[1:-1]] == list(range(2, 9))
    assert lines[-1] == "segment-end next=--from 8"


def test_a_segment_ends_after_for_minutes_with_its_next_from(tmp_path):
    record, slot = _setup(tmp_path)
    _emit(slot, 0, {"action": "ticked", "spawned": [{"task": "t1"}]})
    rc, out, _, polls = _run(record, slot, Clock(DISPATCHED, step=1.0), for_min=28)
    assert rc == 3 and out.splitlines()[-1] == "segment-end next=--from 2"
    assert len(polls) == 27 and set(polls) == {_watch.STREAM_POLL_S}


def test_a_hand_written_stop_ends_the_watch(tmp_path):
    record, slot = _setup(tmp_path)
    rc, out, _, _ = _run(record, slot, Clock(DISPATCHED),
                         on_sleep=lambda n: n == 2 and (slot / orch.STOP_FILE).write_text("x"))
    assert rc == 0
    assert out.splitlines()[-1] == "17:03Z STOP file present: the watcher does nothing. Watch ended."


def test_a_slash_stop_ends_the_watch_on_its_stopped_event(tmp_path):
    record, slot = _setup(tmp_path)

    def watcher(n):
        if n == 1:
            _emit(slot, 5, {"action": "stopped", "reason": "STOP written by /stop"})
            (slot / orch.STOP_FILE).write_text("/stop by example-human\n")
    rc, out, _, _ = _run(record, slot, Clock(DISPATCHED), on_sleep=watcher)
    assert rc == 0 and out.splitlines()[-1].startswith("17:05Z Stopped by /stop.")


def test_the_window_end_ends_the_watch(tmp_path):
    record, slot = _setup(tmp_path)
    rc, out, _, _ = _run(record, slot, Clock(REVIEW_AT + _dt.timedelta(minutes=40)))
    assert rc == 0 and out.splitlines()[-1] == (
        "19:46Z Watch window over (review-at + 45 min). Run /prm or read the digest.")


def test_a_torn_last_line_is_printed_only_once_it_is_complete(tmp_path):
    record, slot = _setup(tmp_path)
    _emit(slot, 0, {"action": "ticked", "spawned": [{"task": "t1"}]})
    events = slot / _events.EVENTS_FILE
    whole = json.dumps({"v": 1, "seq": 3, "at": "2026-11-16T17:09:00Z", "slot": slot.name,
                        "kind": "shift-end", "key": "shift-end", "line": "Shift over.",
                        "needs_you": False}).encode() + b"\n"

    def watcher(n):
        with open(events, "ab") as fh:
            fh.write(whole[:20] if n == 1 else whole[20:])
    rc, out, _, polls = _run(record, slot, Clock(DISPATCHED), on_sleep=watcher)
    assert rc == 0 and len(polls) == 2 and out.splitlines()[-1] == "17:09Z Shift over."


def test_no_tick_yet_is_said_on_attach(tmp_path):
    record, slot = _setup(tmp_path, counters=False)
    rc, out, _, _ = _run(record, slot, Clock(DISPATCHED), for_min=0)
    assert rc == 3 and out.splitlines()[0] == (
        f"attached {slot.name}: no tick yet — the watcher has not run for this brief")


# --- the CLI ----------------------------------------------------------------------------

def _cli(*args, env=None):
    return subprocess.run([str(BRAIN / "bin" / "pyauto-brain"), "batch", "watch",
                           *args], capture_output=True, text=True, timeout=120,
                          env={**os.environ, **(env or {})})


def test_the_cli_streams_checks_and_refuses(tmp_path):
    now = _dt.datetime.now(UTC).replace(second=0, microsecond=0)
    record, slot = _setup(tmp_path, dispatched=now - _dt.timedelta(minutes=10),
                          review_at=now + _dt.timedelta(minutes=60))
    home = str(slot.parent)
    res = _cli("--stream", "--check", "--record", str(record), "--home", home)
    assert res.returncode == 0 and res.stdout == f"attachable: {slot.name} ({slot})\n", res.stderr
    _events.record_tick(slot, now, {"action": "digest", "post": {"posted": True, "url": "u"}},
                        {}, quiet=True)
    res = _cli("--stream", "--record", str(record), "--home", home)
    assert res.returncode == 2 and "is over (shift-end written)" in res.stderr
    res = _cli("--stream", "--check", "x.md", "--record", str(record), "--home", home)
    assert res.returncode == 2 and "--check takes no file" in res.stderr


def test_the_record_and_home_default_from_the_env_file(tmp_path, monkeypatch):
    record, slot = _setup(tmp_path)
    env = tmp_path / "orchestrator.env"
    env.write_text(f"PYAUTO_SHIFT_BRIEF={record}\nPYAUTO_ORCHESTRATOR_HOME={slot.parent}\n"
                   "# a comment\nPYAUTO_SHIFT_APP_KEY=/not/read\n")
    monkeypatch.setattr(_watch, "ENV_FILE", env)
    assert _watch.env_file()["PYAUTO_SHIFT_BRIEF"] == str(record)
    import _batch
    seen = {}
    monkeypatch.setattr(_watch, "stream", lambda record, slot, **kw: seen.update(
        record=record, slot=slot, **kw) or 0)
    assert _batch.main(["watch", "--stream", "--from", "4", "--for", "28"]) == 0
    assert seen["record"] == record and seen["slot"] == slot
    assert seen["from_seq"] == 4 and seen["for_min"] == 28 and seen["check"] is False
