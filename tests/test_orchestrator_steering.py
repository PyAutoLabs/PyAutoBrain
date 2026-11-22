"""PyAutoBrain#622: a live shift view you can steer (human ruling 2026-11-13).

One status comment per shift on its digest issue, created once and then only
edited; `/pause`, `/resume`, `/drop <task>` and `/stop` read from the human's
comments each tick; the dashboard's `- live:` record line. Every `gh` call
goes to a fake GitHub (`FakeGitHub`), so nothing here reaches the network.
"""

from __future__ import annotations

import json
import os
import subprocess
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_orchestrator_dispatch as d  # noqa: E402 — the 3b fixtures
from test_orchestrator_dispatch import _brief, orch  # noqa: E402
import _mind_writer  # noqa: E402
import _status  # noqa: E402
import _watch  # noqa: E402
from _shift_fixtures import at as _at  # noqa: E402

NOW = d.NOW                                   # 2026-11-04T09:00Z; dispatched 08:30Z
ISSUE = "https://github.com/example-org/example-mind/issues/4242"
LOGIN = "example-human"
BOT = "example-bot"


class FakeGitHub:
    """The issue's comments, behind `gh issue comment`, `gh api PATCH` and
    `gh api …/comments` — whose `since` it honours, by `updated_at`, as GitHub
    does. Records each call's kind; fails the next `fail[kind]`; a create
    with `timeout` set times out (after landing, if `timeout == "landed"`)."""

    def __init__(self):
        self.comments, self.calls = [], []
        self.fail = {"create": 0, "edit": 0, "read": 0}
        self.timeout = None
        self.now = NOW
        self._id = 100

    def add(self, login: str, body: str, minutes: float | None = None) -> str:
        self._id += 1
        stamp = orch._iso(_at(minutes) if minutes is not None else self.now)
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
            if self.timeout:
                if self.timeout == "landed":
                    self.add(BOT, body)
                raise subprocess.TimeoutExpired(argv, 120)
            return SimpleNamespace(returncode=0, stdout=self.add(BOT, body) + "\n", stderr="")
        if kind == "edit":
            cid = int(argv[4].rsplit("/", 1)[1])
            body = json.loads(Path(argv[argv.index("--input") + 1]).read_text())["body"]
            self.edit(cid, body)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        since = (parse_qs(urlparse(argv[2]).query).get("since") or [""])[0]
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            [c for c in self.comments if c["updated_at"] >= since]), stderr="")

    def edit(self, cid: int, body: str) -> None:
        c = next(c for c in self.comments if c["id"] == cid)
        c.update(body=body, updated_at=orch._iso(self.now))

    def status(self) -> list[dict]:
        return [c for c in self.comments if c["body"].startswith(orch.STATUS_TAG_PREFIX)]


def _shift(tmp_path, monkeypatch, names=("t1",), extra=""):
    monkeypatch.setenv(orch.MENTION_ENV, LOGIN)
    mind, brief, home = d._shift(tmp_path, names=names, extra=extra)
    brief.write_text(brief.read_text().replace(
        "- review-at: 2026-11-04T11:30Z\n", f"- review-at: 2026-11-04T11:30Z\n- issue: {ISSUE}\n"))
    return mind, brief, home, orch.slot_dir(brief, home)


def _unlabelled(url):
    """`gh pr view` offline: OPEN, no labels. The label read (S7, M3.7c) waits
    on a PR GitHub cannot say about, so a close-out needs a readable PR."""
    return {"state": "OPEN", "mergedAt": "", "mergedBy": "", "labels": []}


def _tick(brief, mind, home, minutes, claude, gh, states=None, *, agents=None,
          health="RUNNING", pr_state=_unlabelled):
    slot = orch.slot_dir(brief, home)
    if agents is None:
        agents = d._agents(states, slot) if states else orch.AgentsView([])
    before = len(gh.calls)
    gh.now = _at(minutes)
    r = orch.tick(brief, mind, home=home, now=_at(minutes), grace_s=0,
                  spawner=orch.RealSpawner(brief, "auto", run=claude), agents=agents,
                  tokens=lambda s: 0, health=lambda u: health, github=gh,
                  pr_state=pr_state, whoami=lambda: BOT,
                  poster=lambda i, b: {"posted": False, "retry": False, "error": "digest"})
    this = gh.calls[before:]
    # The bound (#622): one comments read and one status write a tick, at most.
    assert this.count("read") <= 1 and len(this) - this.count("read") <= 1, this
    return r


def _spawned(claude) -> list[str]:
    return [argv[argv.index("--name") + 1] for argv, _ in claude.calls]


# --- the status comment ---------------------------------------------------------

@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
def test_the_status_comment_is_created_once_and_then_only_edited(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    r = _tick(brief, mind, home, 0, claude, gh)
    assert r["status"]["status"] == "created" and gh.calls == ["read", "create"]
    assert len(gh.status()) == 1
    body = gh.status()[0]["body"]
    assert body == (slot / orch.STATUS_FILE).read_text()
    assert "**Shift `shift` — LIVE · 2h 30m left**" in body and "- tokens: 0 of 100000" in body
    assert "- **Still running** — t1\n  <sub>`t1` · glance · small · pyautobrain · running? (agent 00000001" \
        in body and "@" not in body

    r = _tick(brief, mind, home, 1, claude, gh, {"t1": "working"})       # now listed: a change
    assert r["status"]["status"] == "edited" and "running (agent 00000001, working" in \
        gh.status()[0]["body"]
    r = _tick(brief, mind, home, 2, claude, gh, {"t1": "working"})       # nothing changed
    assert r["status"]["status"] == "unchanged" and gh.calls[-1] == "read"
    (slot / "leases" / "t1.done").write_text("https://github.com/o/r/pull/9\n")
    r = _tick(brief, mind, home, 4, claude, gh, {"t1": "done"})          # a state change
    assert r["status"]["status"] == "edited"
    # M3.7b (S5): a PR with CI running is judged for its close-out at once;
    # this shift's merge-cap 0 refuses it (before S5 it showed "CI running").
    assert ("- **Needs you — not merged unattended** — [t1](https://github.com/o/r/pull/9)"
            in gh.status()[0]["body"])
    assert "merge-cap 0 reached this shift" in gh.status()[0]["body"]
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


@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
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


@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
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


@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
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
    assert orch.PAUSE_ACK in body and "reaps and mentions continue" in body
    gh.add(LOGIN, "/pause", 26)                          # a second comment is a second command
    r = _tick(brief, mind, home, 28, claude, gh, {"t1": "working"})
    assert r["commands"][0]["ack"] == "already paused"


def test_steering_is_off_without_a_login_and_reads_nothing(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    monkeypatch.delenv(orch.MENTION_ENV)
    blank = tmp_path / "policy.yaml"
    blank.write_text("shift_watcher:\n  mention_login: \"\"\n", encoding="utf-8")
    monkeypatch.setattr(orch, "POLICY_PATH", blank)   # hermetic: never the shipped config
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
    assert "Live: LIVE · 1 finished" in _status.render_md(st)
    url = "https://github.com/o/r/issues/1#issuecomment-2"
    html = _status.render_html({**st, "live": f"LIVE — status: {url}"})
    assert f'<a href="{url}">' in html


@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
def test_the_live_line_is_rewritten_only_when_the_shift_changes(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    queued = []
    monkeypatch.setattr(orch, "_record_rel", lambda b, m: "batches/shift.md")

    def commit(slot, mind, msg, **kw):
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


# --- the #622 review --------------------------------------------------------------

def test_editing_an_enacted_command_never_re_triggers_it(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    gh.add(LOGIN, "/pause", 1)
    _tick(brief, mind, home, 3, claude, gh, {"t1": "working"})
    pause = next(c for c in gh.comments if c["body"] == "/pause")
    gh.now = _at(4)
    gh.edit(pause["id"], "/stop")                  # bumps updated_at: read again
    r = _tick(brief, mind, home, 6, claude, gh, {"t1": "working"})
    assert "commands" not in r and not (slot / orch.STOP_FILE).exists()
    assert [c["command"] for c in orch.read_counters(slot)["commands"]] == ["/pause"]


def test_drop_of_a_task_not_in_the_shift_is_refused(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    gh.add(LOGIN, "/drop t11", 1)
    r = _tick(brief, mind, home, 3, claude, gh, {"t1": "working"})
    assert r["commands"][0]["ack"] == "ignored: no such task in this shift (`t11`)"
    assert orch.read_counters(slot)["dropped"] == {}
    assert not (slot / "leases" / "t11.dropped").exists()


@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
def test_drop_tells_a_running_closeout_to_refuse_and_a_merge_anyway_is_outside(
        tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    brief.write_text(brief.read_text().replace("merge-cap: 0", "merge-cap: 2"))
    claude, gh = d.FakeClaude(), FakeGitHub()
    pr = "https://github.com/o/r/pull/9"
    _tick(brief, mind, home, 0, claude, gh)
    (slot / "leases" / "t1.done").write_text(pr + "\n")
    _tick(brief, mind, home, 3, claude, gh, {"t1": "done"}, health="HEALTHY")
    co = orch.read_counters(slot)["closeouts"][pr]
    assert co["state"] == "running"
    working = orch.AgentsView([{"id": co["agent_id"], "state": "working"}])
    gh.add(LOGIN, "/drop t1", 4)
    r = _tick(brief, mind, home, 6, claude, gh, agents=working, health="HEALTHY")
    ack = r["commands"][0]["ack"]
    assert f"a close-out already running may still merge PR {pr}" in ack
    assert (slot / "leases" / "t1.dropped").exists()       # what the close-out checks
    template = orch.closeout_prompt("t1", pr, "x.md", brief, slot / "leases")
    assert f"{slot / 'leases'}/t1.dropped" in template and "dropped by /drop" in template
    # It merged anyway (it was past its check): never an unattended merge.
    (slot / "leases" / "t1.closeout").write_text(json.dumps(
        {"result": "merged", "pr": pr, "gate": "g", "model": "m"}))
    r = _tick(brief, mind, home, 9, claude, gh, agents=working, health="HEALTHY",
              pr_state=lambda u: {"state": "MERGED", "mergedAt": "", "mergedBy": BOT})
    c = orch.read_counters(slot)
    assert c["closeouts"][pr]["state"] == "refused"
    assert c["closeouts"][pr]["why"].startswith("merged outside the close-out after /drop")
    assert c["glance_auto_merges"] == 0
    assert not any(json.loads(f.read_text())["op"] == "table-append"
                   for f in _mind_writer.pending_ops(slot))      # no stage-2 row


def test_stop_commits_nothing_to_mind_on_its_tick(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    commits = []
    monkeypatch.setattr(orch, "_record_rel", lambda b, m: "batches/shift.md")
    monkeypatch.setattr(_mind_writer, "commit_ledger",
                        lambda slot, mind, msg, **kw: commits.append(msg) or {"committed": None})
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR,
                          {"op": "append", "path": "active.md", "text": "x"})  # a worker's
    gh.add(LOGIN, "/stop", 1)
    before = list(commits)
    r = _tick(brief, mind, home, 3, claude, gh, {"t1": "working"})
    assert r["action"] == "stopped" and commits == before
    assert gh.calls[-1] == "edit" and "STOP present" in gh.status()[0]["body"]
    assert _mind_writer.pending_ops(slot)                  # left exactly as STOP leaves it


def test_a_timed_out_create_is_adopted_without_a_login_and_only_from_the_poster(
        tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    monkeypatch.delenv(orch.MENTION_ENV)
    claude, gh = d.FakeClaude(), FakeGitHub()
    gh.timeout = True                                      # timed out, did not land
    _tick(brief, mind, home, 0, claude, gh)
    nonce = json.loads((slot / orch.STATUS_MARKER).read_text())["nonce"]
    gh.timeout = None
    forged = orch.STATUS_TAG.format(slot=slot.name, nonce=nonce) + "\nnot ours"
    gh.add("someone-else", forged, 1)
    _tick(brief, mind, home, 3, claude, gh, {"t1": "working"})
    rec = json.loads((slot / orch.STATUS_MARKER).read_text())
    assert rec["state"] == "unknown" and gh.calls.count("create") == 1
    assert gh.calls[-1] == "read"                          # read for adoption, no login set
    url = gh.add(BOT, orch.STATUS_TAG.format(slot=slot.name, nonce=nonce) + "\nours", 4)
    r = _tick(brief, mind, home, 6, claude, gh, {"t1": "working"})
    rec = json.loads((slot / orch.STATUS_MARKER).read_text())
    assert rec["state"] == "posted" and rec["url"] == url and r["status"]["status"] == "edited"
    assert gh.calls.count("create") == 1
    assert next(c for c in gh.comments if c["html_url"] == url)["body"] != "ours"


def test_a_create_that_timed_out_after_landing_is_adopted_not_reposted(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    gh.timeout = "landed"
    _tick(brief, mind, home, 0, claude, gh)
    gh.timeout = None
    assert json.loads((slot / orch.STATUS_MARKER).read_text())["state"] == "unknown"
    _tick(brief, mind, home, 3, claude, gh, {"t1": "working"})
    _tick(brief, mind, home, 6, claude, gh, {"t1": "working"})
    assert gh.calls.count("create") == 1 and len(gh.status()) == 1
    assert json.loads((slot / orch.STATUS_MARKER).read_text())["state"] == "posted"


# --- `/cap`, `/add`, `/kill` (PyAutoBrain#644; human rulings H5, H6, H8) ------------------
#
# Each test below fails on the code before #644: there the comment is not a
# command at all (`_COMMAND_RE` knew four verbs), so no ack is recorded.

def _acks(slot) -> dict[str, str]:
    return {c["command"]: c["ack"] for c in orch.read_counters(slot)["commands"]}


def test_the_new_verbs_parse_and_the_old_ones_take_one_argument_as_before():
    assert orch._parse_command("/cap merges 1\n(said in the cockpit)") == ("cap", "merges 1")
    assert orch._parse_command("/add draft/feature/x/y.md") == ("add", "draft/feature/x/y.md")
    assert orch._parse_command("/kill `t1`") == ("kill", "t1")
    assert orch._parse_command("/drop a b") is None and orch._parse_command("/caps 1") is None
    assert orch._parse_command("/cap merges 1 2") is None


def _merge_cap(n: int):
    return lambda text: text.replace("  - merge-cap: 0\n", f"  - merge-cap: {n}\n")


#: The /cap tests read their acks against the brief's own caps, so the brief
#: names them rather than leaning on the code defaults (PyAutoBrain#656).
CAP_LINES = "  - max-workers: 2\n  - max-sessions: 6\n"


def _cap_shift(tmp_path, monkeypatch, names=("t1",), merge_cap=2):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch, names=names, extra=CAP_LINES)
    brief.write_text(_merge_cap(merge_cap)(brief.read_text()))
    return mind, brief, home, slot


@pytest.mark.parametrize("comment,ack", [
    ("/cap", "ignored: /cap takes merges, workers, sessions or tokens"),
    ("/cap budget 3", "ignored: /cap takes merges, workers, sessions or tokens"),
    ("/cap merges many", "ignored: /cap needs a whole number"),
    ("/cap workers 1.5k", "ignored: /cap needs a whole number"),
    ("/cap merges 3", "refused: /cap merges 3 is above this brief's merge-cap 2. "
                      "A higher cap needs a new brief."),
    ("/cap tokens 1.2M", "refused: /cap tokens 1.2M is above this brief's token-budget 100000. "
                         "A higher cap needs a new brief."),
    ("/cap sessions 7", "refused: /cap sessions 7 is above this brief's max-sessions 6. "
                        "A higher cap needs a new brief."),
])
def test_cap_ignored_and_refused_acks_change_nothing(tmp_path, monkeypatch, comment, ack):
    mind, brief, home, slot = _cap_shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    gh.add(LOGIN, comment, -5)
    r = _tick(brief, mind, home, 0, claude, gh)
    assert r["commands"][0]["ack"] == ack
    assert "caps" not in orch.read_counters(slot) and _spawned(claude) == ["shift:t1"]


@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
def test_cap_merges_binds_the_close_out_gate_on_the_tick_that_reads_it(tmp_path, monkeypatch):
    mind, brief, home, slot = _cap_shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    pr = "https://github.com/example-org/example-repo/pull/7"
    (slot / "leases" / "t1.done").write_text(pr + "\n")
    gh.add(LOGIN, "/cap merges 0", 2)
    r = _tick(brief, mind, home, 3, claude, gh, {"t1": "done"}, health="HEALTHY")
    assert r["commands"][0]["ack"] == ("merge-cap now 0 of this brief's 2 (0 merge slot(s) "
                                       "taken so far): no new merge starts.")
    c = orch.read_counters(slot)
    assert c["closeouts"][pr] == {"task": "t1", "state": "refused",
                                  "why": "merge-cap 0 reached this shift — left for your /prm"}
    assert c["caps"]["merge-cap"] | {"at": "x"} == {"value": 0, "by": LOGIN, "at": "x",
                                                    "was": 2, "brief": 2}
    assert "- merges: 0 of 0 (0 unattended)" in gh.status()[0]["body"]
    digest = orch._digest.build(orch._brief.effective(
        orch._brief.parse(brief.read_text())["brief"], c), slot, c, health=lambda u: "HEALTHY")
    assert "- cap override: merge-cap 2 → 0 (/cap by example-human at 09:02Z)" in digest


def test_cap_workers_holds_new_spawns_and_never_stops_a_running_worker(tmp_path, monkeypatch):
    mind, brief, home, slot = _cap_shift(tmp_path, monkeypatch, names=("t1", "t2", "t3"))
    claude, gh = d.FakeClaude(), FakeGitHub()
    gh.add(LOGIN, "/cap workers 1", -5)
    r = _tick(brief, mind, home, 0, claude, gh)
    assert r["commands"][0]["ack"] == "max-workers now 1 of 2."
    assert _spawned(claude) == ["shift:t1"]
    assert {x["why"] for x in r["refused"]} == {"max-workers 1 reached"}
    gh.add(LOGIN, "/cap workers 0", 1)
    r = _tick(brief, mind, home, 2, claude, gh, {"t1": "working"})
    assert r["commands"][0]["ack"] == ("max-workers now 0 of 2. 1 still running are not "
                                       "stopped; no new spawn until fewer than 0.")
    assert r["live"] == ["t1"]                                  # never killed
    gh.add(LOGIN, "/cap workers 2", 3)                          # raised back to the brief's
    r = _tick(brief, mind, home, 4, claude, gh, {"t1": "working"})
    assert r["commands"][0]["ack"] == "max-workers now 2 of 2."
    assert _spawned(claude) == ["shift:t1", "shift:t2"]


def test_cap_sessions_holds_new_spawns(tmp_path, monkeypatch):
    mind, brief, home, slot = _cap_shift(tmp_path, monkeypatch, names=("t1", "t2"))
    claude, gh = d.FakeClaude(), FakeGitHub()
    gh.add(LOGIN, "/cap sessions 1", -5)
    r = _tick(brief, mind, home, 0, claude, gh)
    assert r["commands"][0]["ack"] == "max-sessions now 1 of 6 (0 started)."
    assert _spawned(claude) == ["shift:t1"] and r["refused"] == [
        {"task": "t2", "why": "max-sessions 1 reached"}]


def test_cap_tokens_takes_k_and_m_and_lowers_the_spawn_budget(tmp_path, monkeypatch):
    mind, brief, home, slot = _cap_shift(tmp_path, monkeypatch, names=("t1", "t2"))
    claude, gh = d.FakeClaude(), FakeGitHub()
    gh.add(LOGIN, "/cap tokens 0.01k", -5)
    gh.now = _at(0)
    r = orch.tick(brief, mind, home=home, now=_at(0), grace_s=0, token_reserve=50,
                  spawner=orch.RealSpawner(brief, "auto", run=claude),
                  agents=orch.AgentsView([]), tokens=lambda s: 0, github=gh,
                  whoami=lambda: BOT, poster=lambda i, b: {"posted": False, "retry": False})
    assert r["commands"][0]["ack"] == "token-budget now 10 of 100000 (0 committed)."
    assert _spawned(claude) == [] and all(x["why"].startswith("token-budget 10:")
                                          for x in r["refused"])
    assert orch.read_counters(slot)["token_budget"] == 100000    # the brief's own, for estimates
    assert "- tokens: 0 of 10" in gh.status()[0]["body"]


# /add: a draft filed mid-shift, on Mind origin/main only.

ADD_PROMPT = """\
# {name}

Type: feature
Target: {target}
Repos:
- {target}
Difficulty: small
Autonomy: supervised
Priority: normal
Status: formalised
Consequence: glance
Witness: a unit test
Review-minutes: 3
Unattended: ready
{lane}
Body.
"""


def _two_workers(text):
    """Name `max-workers: 2` in the brief, so an /add ack reads the brief's cap."""
    return text.replace("  - backlog: none\n", "  - backlog: none\n  - max-workers: 2\n")


def _add_shift(tmp_path, monkeypatch, drafts=(), active="", brief_edit=None):
    """A git-backed shift (`t1` named) whose Mind origin/main gains `drafts`
    — (path, target, lane) — from another clone after the first tick, so only
    `/add`'s own fetch can see them."""
    monkeypatch.setenv(orch.MENTION_ENV, LOGIN)
    t, bare, canon, brief, home = d._git_shift(tmp_path, monkeypatch)
    text = brief.read_text().replace(
        "- review-at: 2026-11-04T11:30Z\n", f"- review-at: 2026-11-04T11:30Z\n- issue: {ISSUE}\n")
    brief.write_text(brief_edit(text) if brief_edit else text)

    def publish():
        other = t.clone(bare, tmp_path / "other")
        for rel, target, lane in drafts:
            f = other / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(ADD_PROMPT.format(name=Path(rel).stem, target=target,
                                           lane=f"Lane: {lane}\n" if lane else ""))
        if active:
            (other / "active.md").write_text((other / "active.md").read_text() + active)
        t.push(other, "filed mid-shift")
    return canon, brief, home, orch.slot_dir(brief, home), publish


#: A library repo from the body map (never typed: the tenant firewall).
import _batch  # noqa: E402
LIB = max(r for r in _batch.LIBRARY_REPOS if not _batch.self_organ_why({"target": r}))
X = f"draft/feature/{LIB}/x.md"


def test_add_makes_a_draft_filed_mid_shift_a_named_task_and_starts_it(tmp_path, monkeypatch):
    mind, brief, home, slot, publish = _add_shift(
        tmp_path, monkeypatch, drafts=[(X, LIB, "local-dev")], brief_edit=_two_workers)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    publish()
    assert not (mind / X).exists()                       # never pulled into the checkout
    gh.add(LOGIN, "/add x\n(said in the cockpit: \"also do x\")", 1)
    r = _tick(brief, mind, home, 2, claude, gh, {"t1": "working"})
    assert r["commands"][0]["ack"] == ("added x (glance): starts this tick; "
                                       "max-workers 2, 1 running.")
    assert _spawned(claude) == ["shift:t1", "shift:x"]
    c = orch.read_counters(slot)
    assert c["added"]["x"]["prompt"] == X and c["picks"]["x"]["prompt"] == X
    assert (slot / "added" / "x.md").read_text().startswith("# x")
    assert "- **Still running** — x" in gh.status()[0]["body"]
    snap = _watch.snapshot(brief, slot, _at(3), agents=orch.AgentsView([]),
                           health=lambda u: "RUNNING")
    assert {r["task"]: r["why"] for r in snap["tasks"]}["x"] == "added by /add"


@pytest.mark.parametrize("case,drafts,arg,ack", [
    ("not on origin", [], "nothere",
     "ignored: no prompt nothere.md on Mind origin/main (filed? pushed?)"),
    ("not on origin by path", [], f"draft/feature/{LIB}/nothere.md",
     f"ignored: no prompt draft/feature/{LIB}/nothere.md on Mind origin/main (filed? pushed?)"),
    ("two drafts", [(X, LIB, "local-dev"),
                    (f"draft/bug/{LIB}/x.md", LIB, "local-dev")], "x",
     "ignored: x.md names 2 drafts: give the path"),
    ("already named", [], "t1", "ignored: t1 is already in this shift (running)"),
    ("no lane", [(X, LIB, None)], "x",
     "refused: x: no Lane: line (lane absent — unattended picks fail closed; declare a Lane)"),
    ("organ", [("draft/feature/pyautomind/x.md", "PyAutoMind", "local-dev")], "x",
     "refused: x targets PyAutoMind — a shift never changes its own watcher, writer or release "
     "path (the organ rule: /add never overrides it)"),
    ("lane outside the brief", [(X, LIB, "ral")], X,
     "refused: x: lane ral not in the brief's lanes"),
])
def test_add_ignored_and_refused_acks(tmp_path, monkeypatch, case, drafts, arg, ack):
    mind, brief, home, slot, publish = _add_shift(tmp_path, monkeypatch, drafts=drafts)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    if drafts:
        publish()
    gh.add(LOGIN, f"/add {arg}", 1)
    r = _tick(brief, mind, home, 2, claude, gh, {"t1": "working"})
    assert r["commands"][0]["ack"] == ack, case
    assert _spawned(claude) == ["shift:t1"] and "added" not in orch.read_counters(slot)


def test_add_is_refused_on_a_claim_on_mind_origin(tmp_path, monkeypatch):
    mind, brief, home, slot, publish = _add_shift(
        tmp_path, monkeypatch, drafts=[(X, LIB, "local-dev")],
        active="\n## x\n- prompt: active/x.md\n")
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    publish()
    gh.add(LOGIN, "/add x", 1)
    r = _tick(brief, mind, home, 2, claude, gh, {"t1": "working"})
    assert r["commands"][0]["ack"] == "refused: x: claimed in active.md on Mind origin/main"


def test_add_overrides_the_briefs_exclude_list(tmp_path, monkeypatch):
    mind, brief, home, slot, publish = _add_shift(
        tmp_path, monkeypatch, drafts=[(X, LIB, "local-dev")],
        brief_edit=lambda s: _two_workers(s).replace(
            "  - backlog: none\n", f"  - backlog: none\n  - exclude:\n    - {X}\n"))
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    publish()
    gh.add(LOGIN, "/add x", 1)
    r = _tick(brief, mind, home, 2, claude, gh, {"t1": "working"})
    assert r["commands"][0]["ack"] == ("added x (glance) (was excluded in the brief): starts "
                                       "this tick; max-workers 2, 1 running.")
    assert _spawned(claude) == ["shift:t1", "shift:x"]


def test_add_is_refused_within_thirty_minutes_of_review_at(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    gh.add(LOGIN, "/add x", 1)
    r = _tick(brief, mind, home, 121, claude, gh)              # 11:01Z, review-at 11:30Z
    assert r["commands"][0]["ack"] == ("refused: /add within 30 min of review-at. "
                                       "A worker needs longer.")


def test_add_is_refused_in_a_shadow_shift(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch, extra="  - shadow: yes\n")
    claude, gh = d.FakeClaude(), FakeGitHub()
    gh.add(LOGIN, "/add x", 1)
    r = _tick(brief, mind, home, 2, claude, gh)
    assert r["commands"][0]["ack"] == "refused: shadow shift: nothing is dispatched."


# /kill: `claude stop` is a fake on PATH; no session is ever started or stopped.

def _fake_claude_bin(tmp_path, monkeypatch, rc=0):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "claude_calls.log"
    (bindir / "claude").write_text(
        "#!/bin/sh\n"
        f"echo \"$@\" >> {log}\n"
        + ("echo 'Error: no such session' >&2\n" if rc else "echo 'stopped'\n")
        + f"exit {rc}\n")
    (bindir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    return log


def test_kill_stops_the_worker_and_it_is_restarted_once_as_killed(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    log = _fake_claude_bin(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    gh.add(LOGIN, "/kill t1", 1)
    r = _tick(brief, mind, home, 2, claude, gh, {"t1": "working"})
    assert r["commands"][0]["ack"] == ("stopping t1's worker 00000001 (claude stop). "
                                       "It is restarted once, unless you /drop t1.")
    assert log.read_text() == "stop 00000001\n"
    r = _tick(brief, mind, home, 4, claude, gh, {"t1": "stopped"})
    assert r["reaped"] == [{"task": "t1", "event": "dead", "redispatch": "allowed",
                            "killed": True}]
    assert _spawned(claude) == ["shift:t1", "shift:t1"]          # re-dispatched once
    c = orch.read_counters(slot)
    assert c["workers"][0]["exits"] == ["spawned", "killed"] and c["crashes"] == 0
    assert c["killed"]["t1"]["by"] == LOGIN and c["redispatched"] == {"t1": 1}
    assert orch._digest.workers_crashed(c) == 0
    lines = [e["line"] for e in orch._events.read_events(slot) if e["kind"] in
             ("steer", "crashed", "redispatched")]
    assert lines == ["/kill t1 from example-human: stopping t1's worker 00000001 (claude stop). "
                     "It is restarted once, unless you /drop t1.",
                     "Worker on t1 stopped by /kill. It restarts once.",
                     "Restarted t1 (its one retry)."]


def test_drop_then_kill_is_final(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    _fake_claude_bin(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    gh.add(LOGIN, "/drop t1", 1)
    gh.add(LOGIN, "/kill t1", 1.5)
    r = _tick(brief, mind, home, 2, claude, gh, {"t1": "working"})
    assert r["commands"][1]["ack"] == ("stopping t1's worker 00000001 (claude stop). "
                                       "It is not restarted: t1 was dropped.")
    _tick(brief, mind, home, 4, claude, gh, {"t1": "stopped"})
    assert _spawned(claude) == ["shift:t1"]


@pytest.mark.parametrize("comment,rc,ack", [
    ("/kill", 0, "ignored: /kill needs a task name"),
    ("/kill t9", 0, "ignored: no running worker for t9"),
    ("/kill t1", 1, "refused: claude stop failed: Error: no such session. Stop it by hand: "
                    "claude stop 00000001"),
])
def test_kill_ignored_and_refused_acks_stop_nothing(tmp_path, monkeypatch, comment, rc, ack):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    _fake_claude_bin(tmp_path, monkeypatch, rc=rc)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    gh.add(LOGIN, comment, 1)
    r = _tick(brief, mind, home, 2, claude, gh, {"t1": "working"})
    assert r["commands"][0]["ack"] == ack
    assert "killed" not in orch.read_counters(slot)
    (e,) = [e for e in orch._events.read_events(slot) if e["kind"] == "steer"]
    assert e["needs_you"]                                       # an ignored/refused ack


def test_kill_a_second_time_is_ignored(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    log = _fake_claude_bin(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    gh.add(LOGIN, "/kill t1", 1)
    gh.add(LOGIN, "/kill t1", 1.5)
    r = _tick(brief, mind, home, 2, claude, gh, {"t1": "working"})
    assert r["commands"][1]["ack"].startswith("ignored: t1's worker 00000001 is already stopping")
    assert log.read_text() == "stop 00000001\n"


@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
def test_cap_tokens_zero_stops_close_outs_as_its_ack_says(tmp_path, monkeypatch):
    """Review of #644: the close-out gates read `budget is not None`, so a
    `/cap tokens 0` means zero, never "no budget"."""
    mind, brief, home, slot = _cap_shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGitHub()
    _tick(brief, mind, home, 0, claude, gh)
    pr = "https://github.com/example-org/example-repo/pull/8"
    (slot / "leases" / "t1.done").write_text(pr + "\n")
    gh.add(LOGIN, "/cap tokens 0", 2)
    r = _tick(brief, mind, home, 3, claude, gh, {"t1": "done"}, health="HEALTHY")
    assert r["commands"][0]["ack"] == ("token-budget now 0 of 100000 (0 committed): "
                                       "no new spawn or close-out.")
    co = orch.read_counters(slot)["closeouts"][pr]
    assert co["state"] == "refused" and co["why"].startswith("token spend 0 (committed) reached")
    assert r["closeouts"]["started"] == []


def test_command_help_lists_every_verb():
    assert {"add", "cap", "kill"} <= set(orch.COMMANDS)
    for verb in orch.COMMANDS:
        assert f"`/{verb}" in _watch.COMMAND_HELP
