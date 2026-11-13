"""PyAutoBrain#622: a live shift view you can steer (human ruling 2026-11-13).

One status comment per shift on its digest issue, created once and then only
edited; `/pause`, `/resume`, `/drop <task>` and `/stop` read from the human's
comments each tick; the dashboard's `- live:` record line. Every `gh` call
goes to a fake GitHub (`FakeGitHub`), so nothing here reaches the network.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_dispatch as d  # noqa: E402 — the 3b fixtures
from test_orchestrator_dispatch import _brief, orch  # noqa: E402
import _mind_writer  # noqa: E402
import _status  # noqa: E402
import _watch  # noqa: E402

NOW = d.NOW                                   # 2026-11-04T09:00Z; dispatched 08:30Z
ISSUE = "https://github.com/example-org/example-mind/issues/4242"
LOGIN = "example-human"
BOT = "example-bot"


def _at(minutes: float) -> _dt.datetime:
    return NOW + _dt.timedelta(minutes=minutes)


class FakeGitHub:
    """The issue's comments, behind `gh issue comment`, `gh api PATCH` and
    `gh api …/comments`. Records each call's kind; fails the next `fail[kind]`."""

    def __init__(self):
        self.comments, self.calls = [], []
        self.fail = {"create": 0, "edit": 0, "read": 0}
        self._id = 100

    def add(self, login: str, body: str, minutes: float) -> str:
        self._id += 1
        stamp = orch._iso(_at(minutes))
        self.comments.append({"id": self._id, "user": {"login": login}, "body": body,
                              "created_at": stamp, "updated_at": stamp,
                              "html_url": f"{ISSUE}#issuecomment-{self._id}"})
        return self.comments[-1]["html_url"]

    def __call__(self, argv, **kw):
        if argv[:3] == ["gh", "issue", "comment"]:
            kind = "create"
        elif argv[:4] == ["gh", "api", "-X", "PATCH"]:
            kind = "edit"
        elif argv[:2] == ["gh", "api"] and "/comments" in argv[2]:
            kind = "read"
        else:
            raise AssertionError(f"unexpected gh call {argv}")
        self.calls.append(kind)
        if self.fail[kind]:
            self.fail[kind] -= 1
            return SimpleNamespace(returncode=1, stdout="", stderr="HTTP 502")
        if kind == "create":
            body = Path(argv[argv.index("--body-file") + 1]).read_text()
            return SimpleNamespace(returncode=0, stdout=self.add(BOT, body, 0) + "\n", stderr="")
        if kind == "edit":
            cid = int(argv[4].rsplit("/", 1)[1])
            body = json.loads(Path(argv[argv.index("--input") + 1]).read_text())["body"]
            next(c for c in self.comments if c["id"] == cid)["body"] = body
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps(self.comments), stderr="")

    def status(self) -> list[dict]:
        return [c for c in self.comments if c["body"].startswith(orch.STATUS_TAG_PREFIX)]


def _shift(tmp_path, monkeypatch, names=("t1",), extra=""):
    monkeypatch.setenv(orch.MENTION_ENV, LOGIN)
    mind, brief, home = d._shift(tmp_path, names=names, extra=extra)
    brief.write_text(brief.read_text().replace(
        "- review-at: 2026-11-04T11:30Z\n", f"- review-at: 2026-11-04T11:30Z\n- issue: {ISSUE}\n"))
    return mind, brief, home, orch.slot_dir(brief, home)


def _tick(brief, mind, home, minutes, claude, gh, states=None):
    slot = orch.slot_dir(brief, home)
    agents = d._agents(states, slot) if states else orch.AgentsView([])
    before = len(gh.calls)
    r = orch.tick(brief, mind, home=home, now=_at(minutes), grace_s=0,
                  spawner=orch.RealSpawner(brief, "auto", run=claude), agents=agents,
                  tokens=lambda s: 0, health=lambda u: "RUNNING", github=gh,
                  poster=lambda i, b: {"posted": False, "retry": False, "error": "digest"})
    this = gh.calls[before:]
    # The bound (#622): one comments read and one status write a tick, at most.
    assert this.count("read") <= 1 and len(this) - this.count("read") <= 1, this
    return r


def _spawned(claude) -> list[str]:
    return [argv[argv.index("--name") + 1] for argv, _ in claude.calls]


# --- the status comment ---------------------------------------------------------

def test_the_status_comment_is_created_once_and_then_only_edited(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    r = _tick(brief, mind, home, 0, claude, gh)
    assert r["status"]["status"] == "created" and gh.calls == ["read", "create"]
    assert len(gh.status()) == 1
    body = gh.status()[0]["body"]
    assert body == (slot / orch.STATUS_FILE).read_text()
    assert "**Shift `shift` — LIVE · 2h 30m left**" in body and "- tokens: 0 of 100000" in body
    assert "(`t1`; small · pyautobrain) — running? (agent 00000001" in body and "@" not in body

    r = _tick(brief, mind, home, 1, claude, gh, {"t1": "working"})       # now listed: a change
    assert r["status"]["status"] == "edited" and "running (agent 00000001, working" in \
        gh.status()[0]["body"]
    r = _tick(brief, mind, home, 2, claude, gh, {"t1": "working"})       # nothing changed
    assert r["status"]["status"] == "unchanged" and gh.calls[-1] == "read"
    (slot / "leases" / "t1.done").write_text("https://github.com/o/r/pull/9\n")
    r = _tick(brief, mind, home, 4, claude, gh, {"t1": "done"})          # a state change
    assert r["status"]["status"] == "edited"
    assert "https://github.com/o/r/pull/9 — RUNNING" in gh.status()[0]["body"]
    r = _tick(brief, mind, home, 20, claude, gh)                          # the 10-minute refresh
    assert r["status"]["status"] == "edited" and "2h 10m left" in gh.status()[0]["body"]

    assert gh.calls.count("create") == 1 and len(gh.status()) == 1
    rec = json.loads((slot / orch.STATUS_MARKER).read_text())
    assert rec["state"] == "posted" and rec["edits"] == 3


def test_a_tick_that_died_after_its_claim_never_makes_a_second_comment(tmp_path, monkeypatch):
    """Marker before post: a claim with no recorded result is never re-created;
    the comments read adopts the comment if the create did land."""
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    real = orch.gh_comment

    def create_then_die(issue, body, run=None):
        real(issue, body, run=run)
        raise RuntimeError("tick died after the create")
    monkeypatch.setattr(orch, "gh_comment", create_then_die)
    try:
        _tick(brief, mind, home, 0, claude, gh)
    except RuntimeError:
        pass
    orch._drop_lock(slot)
    monkeypatch.setattr(orch, "gh_comment", real)
    assert json.loads((slot / orch.STATUS_MARKER).read_text())["state"] == "claimed"
    _tick(brief, mind, home, 2, claude, gh, {"t1": "working"})   # adopted by the read, edited
    _tick(brief, mind, home, 5, claude, gh, {"t1": "working"})
    assert gh.calls.count("create") == 1 and len(gh.status()) == 1
    rec = json.loads((slot / orch.STATUS_MARKER).read_text())
    assert rec["state"] == "posted" and rec["url"] == gh.status()[0]["html_url"]
    assert gh.calls.count("edit") >= 1


def test_a_failed_status_edit_is_retried_next_tick(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    (slot / "leases" / "t1.done").write_text("https://github.com/o/r/pull/9\n")
    gh.fail.update(edit=1, read=1)                      # GitHub unreachable this tick
    r = _tick(brief, mind, home, 3, claude, gh, {"t1": "done"})
    assert r["action"] == "ticked" and r["reaped"] == [{"task": "t1", "event": "done"}]
    assert r["status"]["status"] == "edit failed — retried next tick"
    assert "pull/9" not in gh.status()[0]["body"]
    r = _tick(brief, mind, home, 4, claude, gh)         # nothing new changed: still due
    assert r["status"]["status"] == "edited" and "pull/9" in gh.status()[0]["body"]
    assert gh.calls.count("create") == 1


def test_a_failed_create_is_made_again_and_still_only_once(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    gh.fail["create"] = 1
    assert _tick(brief, mind, home, 0, claude, gh)["status"]["status"] == "create failed"
    assert _tick(brief, mind, home, 3, claude, gh, {"t1": "working"})["status"]["status"] == "created"
    _tick(brief, mind, home, 6, claude, gh, {"t1": "working"})
    assert len(gh.status()) == 1


# --- the commands ---------------------------------------------------------------

def test_pause_holds_new_spawns_until_resume(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch, names=("t1", "t2"),
                                     extra="  - max-workers: 1\n")
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    assert _spawned(claude) == ["shift:t1"]
    gh.add(LOGIN, "/pause", 1)
    (slot / "leases" / "t1.done").write_text("https://github.com/o/r/pull/9\n")
    r = _tick(brief, mind, home, 3, claude, gh, {"t1": "done"})
    assert r["paused"] and r["spawned"] == [] and r["reaped"][0]["event"] == "done"
    assert r["commands"][0]["command"] == "pause"
    assert "PAUSED by example-human" in gh.status()[0]["body"]
    _tick(brief, mind, home, 6, claude, gh)
    assert _spawned(claude) == ["shift:t1"]
    gh.add(LOGIN, "/resume", 7)
    r = _tick(brief, mind, home, 9, claude, gh)
    assert "paused" not in r and r["spawned"][0]["task"] == "t2"
    assert "PAUSED" not in gh.status()[0]["body"]


def test_drop_removes_a_pick_not_yet_spawned(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch, names=("t1", "t2"),
                                     extra="  - max-workers: 1\n")
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    gh.add(LOGIN, "/drop draft/feature/pyautobrain/t2.md\n\nnot this one today", 1)
    (slot / "leases" / "t1.done").write_text("https://github.com/o/r/pull/9\n")
    r = _tick(brief, mind, home, 3, claude, gh, {"t1": "done"})
    assert r["spawned"] == [] and r["commands"][0]["ack"].startswith("dropped `t2`: it will not")
    _tick(brief, mind, home, 6, claude, gh)
    assert _spawned(claude) == ["shift:t1"]
    body = gh.status()[0]["body"]
    assert "`t2`" in body and "dropped by /drop — not started" in body


def test_drop_of_a_running_worker_leaves_it_running_and_never_merges_it(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    gh.add(LOGIN, "/drop t1", 1)
    r = _tick(brief, mind, home, 3, claude, gh, {"t1": "working"})
    assert "`claude stop 00000001`" in r["commands"][0]["ack"]
    assert "dropped, still running — running (agent 00000001" in gh.status()[0]["body"]
    assert orch.leases(slot)["t1"]                      # never killed by the watcher
    (slot / "leases" / "t1.done").write_text("https://github.com/o/r/pull/9\n")
    _tick(brief, mind, home, 6, claude, gh, {"t1": "done"})
    co = orch.read_counters(slot)["closeouts"]["https://github.com/o/r/pull/9"]
    assert co["state"] == "refused" and "dropped by /drop" in co["why"]


def test_stop_behaves_like_the_kill_switch_file(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch, names=("t1", "t2"),
                                     extra="  - max-workers: 1\n")
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    gh.add(LOGIN, "/stop", 1)
    (slot / "leases" / "t1.done").write_text("https://github.com/o/r/pull/9\n")
    r = _tick(brief, mind, home, 3, claude, gh, {"t1": "done"})
    assert r["action"] == "stopped" and (slot / orch.STOP_FILE).exists()
    assert "STOP present — the watcher does nothing" in gh.status()[0]["body"]
    calls = len(gh.calls)
    r = _tick(brief, mind, home, 6, claude, gh)
    assert r == {"action": "stopped", "reason": "STOP present"}
    assert len(gh.calls) == calls and _spawned(claude) == ["shift:t1"]


def test_a_command_from_another_login_or_the_bot_or_before_the_shift_is_ignored(
        tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch, names=("t1", "t2"),
                                     extra="  - max-workers: 1\n")
    claude, gh = d.FakeClaude(), FakeGitHub()
    gh.add(LOGIN, "/pause", -40)                         # before dispatched: a past shift's
    _tick(brief, mind, home, 0, claude, gh)
    gh.add("someone-else", "/stop", 1)
    gh.add(BOT, "/pause", 1)                             # not the human's login
    gh.add(LOGIN, "please /pause after this one", 1)     # not a command line
    (slot / "leases" / "t1.done").write_text("https://github.com/o/r/pull/9\n")
    r = _tick(brief, mind, home, 3, claude, gh, {"t1": "done"})
    assert "commands" not in r and "paused" not in r and r["spawned"][0]["task"] == "t2"
    assert not (slot / orch.STOP_FILE).exists() and orch.read_counters(slot)["commands"] == []
    # The status comment itself names every command: it is never read as one,
    # even when it posts as the human's own login.
    monkeypatch.setenv(orch.MENTION_ENV, BOT)
    r = _tick(brief, mind, home, 6, claude, gh, {"t2": "working"})
    assert [c["command"] for c in r.get("commands", [])] == ["pause"]  # the bot's own /pause line
    assert "/pause" in gh.status()[0]["body"] and orch.read_counters(slot)["commands"][0]["by"] == BOT


def test_a_command_is_enacted_and_acknowledged_once(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    gh.add(LOGIN, "/pause", 1)
    for minutes in (3, 6, 9, 25):                        # the fake returns it every read
        _tick(brief, mind, home, minutes, claude, gh, {"t1": "working"})
    c = orch.read_counters(slot)
    assert len(c["commands"]) == 1 and c["paused"]["by"] == LOGIN
    body = gh.status()[0]["body"]
    assert body.count("`/pause` by example-human") == 1
    assert "paused: no new workers or close-outs until /resume" in body
    gh.add(LOGIN, "/pause", 26)                          # a second comment is a second command
    r = _tick(brief, mind, home, 28, claude, gh, {"t1": "working"})
    assert r["commands"][0]["ack"] == "already paused"


def test_steering_is_off_without_a_login_and_reads_nothing(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    monkeypatch.delenv(orch.MENTION_ENV)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    assert gh.calls == ["create"] and "Steering is off" in gh.status()[0]["body"]


# --- batch watch and the dashboard ----------------------------------------------

def test_batch_watch_shows_the_steering(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    gh.add(LOGIN, "/pause", 1)
    _tick(brief, mind, home, 3, claude, gh, {"t1": "working"})
    text = _watch.render(_watch.snapshot(brief, slot, _at(4), agents=d._agents({"t1": "working"}, slot),
                                         health=lambda u: "RUNNING"))
    assert "PAUSED by example-human — /resume to continue" in text
    assert "Commands\n- `/pause` by example-human" in text
    assert f"Status comment: {gh.status()[0]['html_url']}" in text


def test_record_key_upserts_the_live_line_and_the_box_shows_it():
    rec = "# Batch x\n- dispatched: a\n- review-at: b\n- issue: c\n- brief:\n  - tasks:\n\n## Digest\n- live: no\n"
    once = _mind_writer.record_key(rec, "live", "LIVE · 1 running")
    assert once.splitlines()[4] == "- live: LIVE · 1 running"
    twice = _mind_writer.record_key(once, "live", "LIVE · 1 finished")
    assert twice.count("- live:") == 2 and "- live: LIVE · 1 finished" in twice  # the digest's untouched
    assert twice.endswith("## Digest\n- live: no\n")
    assert _brief.parse(twice)["top"]["live"]["value"] == "LIVE · 1 finished"
    lm = SimpleNamespace(is_ledger_path=lambda p: True)   # Mind's own rule is tested there
    assert _mind_writer.validate_op({"op": "record-key", "path": "batches/x.md", "key": "live",
                                     "value": "v"}, lm) == []
    assert _mind_writer.validate_op({"op": "record-key", "path": "active.md", "key": "live",
                                     "value": "v"}, lm)
    assert _mind_writer.validate_op({"op": "record-key", "path": "batches/x.md", "key": "live",
                                     "value": "two\nlines"}, lm)
    keys = _status.read_record(twice)["keys"]
    st = _status.dev_status("x", keys, [], False, "")
    assert st["live"] == "LIVE · 1 finished"
    assert "> Live: LIVE · 1 finished" in _status.render_md(st)
    url = "https://github.com/o/r/issues/1#issuecomment-2"
    html = _status.render_html({**st, "live": f"LIVE — status: {url}"})
    assert f'<a href="{url}">' in html


def test_the_live_line_is_rewritten_only_when_the_shift_changes(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    queued = []
    monkeypatch.setattr(orch, "_record_rel", lambda b, m: "batches/shift.md")

    def commit(slot, mind, msg):
        for f in _mind_writer.pending_ops(slot):
            queued.append(json.loads(f.read_text()))
            f.unlink()
        return {"committed": "abc", "ops": 1}
    monkeypatch.setattr(_mind_writer, "commit_ledger", commit)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    _tick(brief, mind, home, 3, claude, gh, {"t1": "working"})
    _tick(brief, mind, home, 20, claude, gh, {"t1": "working"})   # tokens / clock only
    lines = [op["value"] for op in queued if op["op"] == "record-key"]
    assert len(lines) == 1 and queued[0]["path"] == "batches/shift.md"
    assert lines[0].startswith("LIVE · 1 running · tokens 0 of 100000")
    assert lines[0].endswith("— status: " + gh.status()[0]["html_url"])
    (slot / "leases" / "t1.done").write_text("https://github.com/o/r/pull/9\n")
    _tick(brief, mind, home, 23, claude, gh, {"t1": "done"})
    lines = [op["value"] for op in queued if op["op"] == "record-key"]
    assert len(lines) == 2 and lines[-1].startswith("LIVE · 1 finished")
