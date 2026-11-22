"""Shift launch preflight in the watcher (M3.6a, PyAutoBrain#659).

- an expired CLI login is its own `login-expired` event and holds spawning —
  never "blocked on a person";
- the watcher finds the one open brief on Mind `origin/main` itself (no
  fetch), and idles when two are open;
- after `review-at:` + 45 min, with the digest posted, a tick does nothing:
  no lock, no reap, no lease write, no log line.

`claude` is a fake on PATH and workers are `FakeClaude` / fake-mode stubs;
nothing reaches GitHub or starts a session.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path

import test_orchestrator_dispatch as d  # noqa: E402 — the 3b fixtures
from test_orchestrator_dispatch import orch  # noqa: E402
from _shift_fixtures import git_as_t as _git  # noqa: E402

NOW = d.NOW                                   # 2026-11-04T09:00Z
MIN = _dt.timedelta(minutes=1)


def _fake_claude(tmp_path: Path, monkeypatch, out: str, rc: int = 0) -> Path:
    """A fake `claude` on PATH for `claude auth status --json` (the probe)."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    log, text, code = tmp_path / "claude.log", tmp_path / "claude.out", tmp_path / "claude.rc"
    text.write_text(out)
    code.write_text(str(rc))
    (bindir / "claude").write_text(f"#!/bin/sh\necho \"$@\" >> {log}\ncat {text}\n"
                                   f"exit $(cat {code})\n")
    (bindir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    return log


OK_JSON = '{"loggedIn": true, "loginExpiresAt": "2099-01-01T00:00:00.000Z"}\n'
EXPIRED_LINE = "CLI login expired: run `claude /login`. No worker starts until it passes."


# --- Witness 3 (watcher half): the first tick logs login-expired ------------------

def test_first_tick_logs_login_expired_not_blocked(tmp_path, monkeypatch):
    monkeypatch.delenv("PYAUTO_LOGIN_PROBE", raising=False)
    log = _fake_claude(tmp_path, monkeypatch,
                       "Login reached its time limit. Run /login to sign in again.\n", rc=1)
    mind, brief, home = d._shift(tmp_path)
    claude = d.FakeClaude()
    r = d._tick(brief, mind, home, NOW, claude)
    assert r["spawned"] == [] and claude.calls == [], "no worker starts on an expired login"
    assert r["login"]["state"] == "expired"
    slot = orch.slot_dir(brief, home)
    events = orch._events.read_events(slot)
    ours = [e for e in events if e["kind"] == "login-expired"]
    assert [e["line"] for e in ours] == [EXPIRED_LINE] and ours[0]["needs_you"]
    assert not any("blocked on a person" in e["line"] or e["kind"] == "parked"
                   for e in events)
    assert "blocked on a person" not in (slot / orch.LOG_FILE).read_text()
    assert log.read_text().splitlines() == ["auth status --json"]

    # Logged in again: the next tick starts the worker; the event is not repeated.
    (tmp_path / "claude.out").write_text(OK_JSON)
    (tmp_path / "claude.rc").write_text("0")
    r = d._tick(brief, mind, home, NOW + 3 * MIN, claude)
    assert [s["task"] for s in r["spawned"]] == ["t1"]
    assert [e["kind"] for e in orch._events.read_events(slot)].count("login-expired") == 1
    # Once it passed, it is not probed again while no worker shows blocked.
    d._tick(brief, mind, home, NOW + 6 * MIN, claude,
            agents=d._agents({"t1": "working"}, slot))
    assert len(log.read_text().splitlines()) == 2


def test_a_blocked_worker_reprobes_the_login(tmp_path, monkeypatch):
    monkeypatch.delenv("PYAUTO_LOGIN_PROBE", raising=False)
    log = _fake_claude(tmp_path, monkeypatch, OK_JSON)
    mind, brief, home = d._shift(tmp_path, names=("t1", "t2"),
                                 extra="  - max-workers: 1\n")
    claude = d.FakeClaude()
    assert [s["task"] for s in d._tick(brief, mind, home, NOW, claude)["spawned"]] == ["t1"]
    slot = orch.slot_dir(brief, home)
    (tmp_path / "claude.out").write_text('{"loggedIn": false}\n')
    r = d._tick(brief, mind, home, NOW + 3 * MIN, claude,
                agents=d._agents({"t1": "blocked"}, slot))
    assert r["login"]["state"] == "expired" and r["spawned"] == []
    assert len(log.read_text().splitlines()) == 2
    assert [e["line"] for e in orch._events.read_events(slot)
            if e["kind"] == "login-expired"] == [EXPIRED_LINE]


# --- Witness 4: the watcher finds the open brief on Mind origin/main ----------------

BRIEF = """\
# Batch {name}
- dispatched: {dispatched}
- review-at: {review_at}
- brief:
  - goals:
    - 1. sandbox shift
  - backlog: none
  - review-minutes: 45
  - lanes: any local-dev
  - merge-cap: 0
  - token-budget: 100000
  - sandbox: yes
"""


def _iso(t: _dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%MZ")


def _origin(tmp_path: Path, briefs: dict) -> tuple[Path, Path]:
    """(seed clone, Mind clone): `briefs` {name: (dispatched, review_at)} pushed
    to a bare origin, then cloned as the Mind checkout the watcher reads."""
    bare, seed, mind = tmp_path / "PyAutoMind.git", tmp_path / "seed", tmp_path / "mind"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    _git(tmp_path, "clone", "-q", str(bare), str(seed))
    (seed / "draft").mkdir()
    (seed / "draft" / "README.md").write_text("drafts\n")
    (seed / "batches").mkdir()
    (seed / "batches" / "AGENTS.md").write_text("# batches\n")
    _push(seed, briefs)
    _git(tmp_path, "clone", "-q", str(bare), str(mind))
    return seed, mind


def _push(seed: Path, briefs: dict) -> None:
    for name, (start, end) in briefs.items():
        (seed / "batches" / f"{name}.md").write_text(
            BRIEF.format(name=name, dispatched=_iso(start), review_at=_iso(end)))
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "briefs")
    _git(seed, "push", "-q", "origin", "HEAD:main")


def test_watch_ticks_the_one_open_brief_on_origin(tmp_path, monkeypatch):
    monkeypatch.setenv(orch.FAKE_ENV, "1")
    _, mind = _origin(tmp_path, {
        "2026-11-04-am": (NOW - 30 * MIN, NOW + 150 * MIN),     # open now
        "2026-11-04-pm": (NOW + 240 * MIN, NOW + 420 * MIN)})   # not yet open
    # Written but never pushed: only a pushed brief opens.
    (mind / "batches" / "2026-11-04-x.md").write_text(BRIEF.format(
        name="x", dispatched=_iso(NOW - 10 * MIN), review_at=_iso(NOW + 60 * MIN)))
    home = tmp_path / "home"
    r = orch.watch(mind, home=home, now=NOW)
    assert list(r["ticked"]) == ["2026-11-04-am"], r
    assert r["ticked"]["2026-11-04-am"]["action"] == "ticked"
    assert (home / "2026-11-04-am" / orch.LOG_FILE).is_file()
    assert not (home / "2026-11-04-pm").exists() and not (home / "2026-11-04-x").exists()
    # A `--brief` override outside its own window is not honoured.
    r = orch.watch(mind, home=home, now=NOW + 3 * MIN,
                   override=mind / "batches" / "2026-11-04-pm.md")
    assert list(r["ticked"]) == ["2026-11-04-am"]
    assert not (home / "2026-11-04-pm").exists()


def test_a_pushed_brief_the_checkout_lacks_idles(tmp_path, monkeypatch):
    monkeypatch.setenv(orch.FAKE_ENV, "1")
    seed, mind = _origin(tmp_path, {})
    _push(seed, {"2026-11-04-am": (NOW - 30 * MIN, NOW + 150 * MIN)})
    _git(mind, "fetch", "-q", "origin")          # the ref moves; the tree does not
    r = orch.watch(mind, home=tmp_path / "home", now=NOW)
    assert r["action"] == "idle"
    assert "pushed, but the Mind checkout is behind" in r["reason"]


def test_two_open_briefs_idle(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(orch.FAKE_ENV, "1")
    monkeypatch.delenv("PYAUTO_SHIFT_BRIEF", raising=False)
    now = _dt.datetime.now(_dt.timezone.utc)
    _, mind = _origin(tmp_path, {"2026-11-04-am": (now - 60 * MIN, now + 120 * MIN),
                                 "2026-11-04-pm": (now - 30 * MIN, now + 180 * MIN)})
    home = tmp_path / "home"
    assert orch.main(["--mind", str(mind), "--home", str(home)]) == 0
    assert capsys.readouterr().out.strip() == (
        "idle: two open briefs on origin/main (2026-11-04-am, 2026-11-04-pm)")
    assert not home.exists() or not any(home.iterdir()), "no slot was ticked"


# --- Witness 5: after review-at + 45 min a tick does nothing ------------------------

def test_after_late_window_no_tick_and_lease_mtime_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("PYAUTO_LOGIN_PROBE", "off")
    mind, brief, home = d._shift(tmp_path)               # review-at 11:30Z
    claude = d.FakeClaude()
    assert d._tick(brief, mind, home, NOW, claude)["spawned"]
    slot = orch.slot_dir(brief, home)
    review_at = _dt.datetime(2026, 11, 4, 11, 30, tzinfo=_dt.timezone.utc)
    r = d._tick(brief, mind, home, review_at + MIN, claude,
                agents=d._agents({"t1": "working"}, slot))
    assert r["action"] == "digest" and (slot / orch.DIGEST_MARKER).exists()
    lease_files = sorted((slot / "leases").glob("*.json"))
    assert lease_files, "the worker is still out after the digest"
    for f in lease_files:
        os.utime(f, (1_000_000_000, 1_000_000_000))
    before = {f: f.stat().st_mtime for f in lease_files}
    log_before = (slot / orch.LOG_FILE).read_text()

    r = d._tick(brief, mind, home, review_at + 46 * MIN, claude,
                agents=d._agents({"t1": "working"}, slot))
    assert r["action"] == "idle" and "late window closed" in r["reason"], r
    assert {f: f.stat().st_mtime for f in lease_files} == before
    assert (slot / orch.LOG_FILE).read_text() == log_before
    assert not (slot / orch.LOCK_FILE).exists()
    json.dumps(r)


# --- review findings (M3.6a, #659): the override and the end -------------------------

def _names(paths) -> list[str]:
    return [Path(p).stem for p in paths]


def test_a_stale_override_in_its_late_window_does_not_displace_the_open_brief(tmp_path):
    """The env file still names shift A, ended 10 min ago; shift B is open.
    B is ticked, and A alongside it as one more late brief."""
    _, mind = _origin(tmp_path, {
        "2026-11-04-am": (NOW - 180 * MIN, NOW - 10 * MIN),
        "2026-11-04-pm": (NOW - 5 * MIN, NOW + 180 * MIN)})
    paths, why = orch.find_briefs(mind, NOW, override=mind / "batches" / "2026-11-04-am.md",
                                  home=tmp_path / "home")
    assert _names(paths) == ["2026-11-04-pm", "2026-11-04-am"], (paths, why)
    # An override that is itself open still takes the open brief's place.
    paths, _ = orch.find_briefs(mind, NOW, override=mind / "batches" / "2026-11-04-pm.md",
                                home=tmp_path / "home")
    assert _names(paths) == ["2026-11-04-pm", "2026-11-04-am"]


def test_a_brief_past_its_late_window_is_caught_up_until_its_digest_is_out(tmp_path):
    """The laptop was off through the late window: the digest is still owed,
    so the brief is still ticked; once it is posted and nothing is owed, not."""
    _, mind = _origin(tmp_path, {"2026-11-04-am": (NOW - 300 * MIN, NOW - 120 * MIN)})
    home = tmp_path / "home"
    slot = home / "2026-11-04-am"
    (slot / "leases").mkdir(parents=True)
    assert _names(orch.find_briefs(mind, NOW, home=home)[0]) == ["2026-11-04-am"]
    (slot / orch.DIGEST_MARKER).write_text(json.dumps({"state": "failed", "tries": 1}))
    assert _names(orch.find_briefs(mind, NOW, home=home)[0]) == ["2026-11-04-am"]
    (slot / orch.DIGEST_MARKER).write_text(json.dumps({"state": "posted", "tries": 1}))
    assert orch.find_briefs(mind, NOW, home=home)[0] == []
    # A slot the watcher never touched is not caught up.
    assert orch.find_briefs(mind, NOW, home=tmp_path / "other")[0] == []


def _ended_shift(tmp_path, monkeypatch):
    """Witness 5's shift: digest out at review-at, the worker still out."""
    monkeypatch.setenv("PYAUTO_LOGIN_PROBE", "off")
    mind, brief, home = d._shift(tmp_path)
    claude = d.FakeClaude()
    d._tick(brief, mind, home, NOW, claude)
    slot = orch.slot_dir(brief, home)
    review_at = _dt.datetime(2026, 11, 4, 11, 30, tzinfo=_dt.timezone.utc)
    d._tick(brief, mind, home, review_at + MIN, claude, agents=d._agents({"t1": "working"}, slot))
    return mind, brief, home, slot, claude, review_at


def test_the_late_window_stop_waits_for_a_due_digest_retry(tmp_path, monkeypatch):
    mind, brief, home, slot, claude, review_at = _ended_shift(tmp_path, monkeypatch)
    (slot / orch.DIGEST_MARKER).write_text(json.dumps(
        {"state": "failed", "tries": 1, "issue": "", "at": "2026-11-04T11:31:00Z"}))
    r = d._tick(brief, mind, home, review_at + 46 * MIN, claude,
                agents=d._agents({"t1": "working"}, slot))
    assert "late window closed" not in str(r.get("reason")), r


def test_the_late_window_stop_waits_for_a_queued_mind_op(tmp_path, monkeypatch):
    mind, brief, home, slot, claude, review_at = _ended_shift(tmp_path, monkeypatch)
    orch._mind_writer.queue_op(slot / orch._mind_writer.LEDGER_DIR,
                               {"op": "append", "path": "batches/x.md", "text": "x"})
    r = d._tick(brief, mind, home, review_at + 46 * MIN, claude,
                agents=d._agents({"t1": "working"}, slot))
    assert "late window closed" not in str(r.get("reason")), r


def test_a_slot_past_the_catch_up_cap_is_named_abandoned_once(tmp_path):
    """Inside the 24 h catch-up a slot that owes its digest is ticked; past it
    the tick does not, and says once which slot was left and what it owes."""
    review_at = NOW - 60 * MIN
    _, mind = _origin(tmp_path, {"2026-11-04-am": (review_at - 180 * MIN, review_at)})
    home = tmp_path / "home"
    (home / "2026-11-04-am" / "leases").mkdir(parents=True)
    (home / "2026-11-04-am" / "leases" / "t1.json").write_text("{}")
    cap = review_at + _dt.timedelta(seconds=orch._brief.LATE_WINDOW_S + orch.CATCH_UP_S)
    assert _names(orch.find_briefs(mind, cap - MIN, home=home)[0]) == ["2026-11-04-am"]
    paths, why = orch.find_briefs(mind, cap + MIN, home=home)
    assert paths == []
    assert "abandoned: 2026-11-04-am past catch-up" in why, why
    assert "digest not posted" in why and "1 lease" in why
    # Named once, not every tick.
    assert "abandoned" not in orch.find_briefs(mind, cap + 4 * MIN, home=home)[1]
