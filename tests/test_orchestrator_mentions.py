"""PyAutoBrain#611 (M1.6): a blocked shift worker reaches the human through a
GitHub @mention on the shift's digest issue (the human's channel ruling,
2026-11-12). The `gh` call sits behind a fake `run`, so nothing reaches
GitHub; the login comes from the environment or config, never the code.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path
from types import SimpleNamespace

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_dispatch as d  # noqa: E402 — the 3b fixtures
from test_orchestrator_dispatch import _brief, _digest, orch  # noqa: E402

NOW = d.NOW
ISSUE = "https://github.com/example-org/example-mind/issues/4242"
LOGIN = "example-human"
PAST_GRACE = NOW + _dt.timedelta(minutes=1, seconds=orch.STALL_GRACE_S)


class FakeGh:
    """`gh issue comment`: records argv and the body; fails the first `fail` calls."""

    def __init__(self, fail=0):
        self.calls, self.fail = [], fail

    def __call__(self, argv, **kw):
        body = Path(argv[argv.index("--body-file") + 1]).read_text()
        self.calls.append((argv, body))
        if len(self.calls) <= self.fail:
            return SimpleNamespace(returncode=1, stdout="", stderr="HTTP 502")
        return SimpleNamespace(returncode=0, stdout=f"{ISSUE}#issuecomment-{len(self.calls)}\n",
                               stderr="")


def _shift(tmp_path, monkeypatch, login=LOGIN):
    if login:
        monkeypatch.setenv(orch.MENTION_ENV, login)
    mind, brief, home = d._shift(tmp_path)
    brief.write_text(brief.read_text().replace(
        "- review-at: 2026-11-04T11:30Z\n", f"- review-at: 2026-11-04T11:30Z\n- issue: {ISSUE}\n"))
    return mind, brief, home, orch.slot_dir(brief, home)


def _tick(brief, mind, home, now, claude, gh, agents=None):
    return orch.tick(brief, mind, home=home, now=now, grace_s=0,
                     spawner=orch.RealSpawner(brief, "auto", run=claude),
                     agents=agents or orch.AgentsView([]), tokens=lambda s: 0,
                     poster=lambda issue, body: orch.gh_comment(issue, body, run=gh))


def _park(brief, mind, home, slot, claude, gh):
    blocked = lambda: d._agents({"t1": "blocked"}, slot)  # noqa: E731
    _tick(brief, mind, home, NOW, claude, gh)
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=1), claude, gh, blocked())
    return _tick(brief, mind, home, PAST_GRACE, claude, gh, blocked())


def test_a_parked_worker_makes_exactly_one_mention_and_a_second_tick_none(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGh()
    r = _park(brief, mind, home, slot, claude, gh)
    assert r["reaped"][0]["event"] == "parked"
    assert len(gh.calls) == 1
    argv, body = gh.calls[0]
    assert argv[:4] == ["gh", "issue", "comment", ISSUE]
    assert body.startswith(f"@{LOGIN} shift `shift`: the worker on `t1` needs you — parked.")
    assert "- reason: blocked on a person (blocked since 2026-11-04T09:01:00Z)" in body
    assert "session `00000001`" in body and "draft/feature/pyautobrain/t1.md" in body
    r = _tick(brief, mind, home, PAST_GRACE + _dt.timedelta(minutes=5), claude, gh,
              d._agents({"t1": "blocked"}, slot))
    assert len(gh.calls) == 1 and "mentions" not in r
    c = orch.read_counters(slot)
    assert c["pushes"] == 1
    text = _digest.build(_brief.parse(brief.read_text())["brief"], slot, c,
                         health=lambda u: "HEALTHY")
    assert "- pushes: 1" in text and "(00000001): spawned/parked" in text
    assert "mentioned (parked)" in text


def test_a_failed_mention_is_retried_on_the_next_tick(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGh(fail=1)
    r = _park(brief, mind, home, slot, claude, gh)
    assert r["mentions"] == [{"task": "t1", "state": "parked", "post": "failed", "retry": 1}]
    assert orch.read_counters(slot)["pushes"] == 0
    blocked = lambda: d._agents({"t1": "blocked"}, slot)  # noqa: E731
    r = _tick(brief, mind, home, PAST_GRACE + _dt.timedelta(minutes=3), claude, gh, blocked())
    assert r["mentions"] == [{"task": "t1", "state": "parked", "post": "posted", "retry": 2}]
    assert len(gh.calls) == 2 and gh.calls[0][1] == gh.calls[1][1]     # the same comment
    _tick(brief, mind, home, PAST_GRACE + _dt.timedelta(minutes=6), claude, gh, blocked())
    assert len(gh.calls) == 2 and orch.read_counters(slot)["pushes"] == 1


def test_a_worker_that_finishes_normally_makes_no_mention(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGh()
    _tick(brief, mind, home, NOW, claude, gh)
    (slot / "leases" / "t1.done").write_text("https://github.com/o/r/pull/9\n")
    r = _tick(brief, mind, home, NOW + _dt.timedelta(minutes=5), claude, gh,
              d._agents({"t1": "done"}, slot))
    assert r["reaped"] == [{"task": "t1", "event": "done"}]
    assert gh.calls == [] and orch.read_counters(slot)["pushes"] == 0


def test_a_crash_makes_no_mention(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGh()
    _tick(brief, mind, home, NOW, claude, gh)
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=3), claude, gh,
          d._agents({"t1": "failed"}, slot))
    assert gh.calls == []                       # the push test: the digest carries it


def test_a_worker_parked_on_its_issue_is_awaiting_input(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGh()
    _tick(brief, mind, home, NOW, claude, gh)
    (slot / "leases" / "t1.done").write_text("https://github.com/o/r/issues/77\n")
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=5), claude, gh,
          d._agents({"t1": "done"}, slot))
    assert len(gh.calls) == 1
    body = gh.calls[0][1]
    assert "needs you — awaiting-input." in body
    assert "parked on its issue with a question: https://github.com/o/r/issues/77" in body


def test_the_login_comes_from_the_environment_or_config_never_the_code(tmp_path, monkeypatch):
    monkeypatch.delenv(orch.MENTION_ENV, raising=False)
    assert orch.mention_login() == ""           # config/policy.yaml leaves it blank
    monkeypatch.setenv(orch.MENTION_ENV, "@" + LOGIN)
    assert orch.mention_login() == LOGIN
    monkeypatch.setenv(orch.MENTION_ENV, "not a login; rm -rf")
    assert orch.mention_login() == ""
    mind, brief, home, slot = _shift(tmp_path, monkeypatch, login="")
    monkeypatch.delenv(orch.MENTION_ENV, raising=False)
    claude, gh = d.FakeClaude(), FakeGh()
    _park(brief, mind, home, slot, claude, gh)
    body = gh.calls[0][1]
    assert "@" not in body.split("\n")[0] and orch.MENTION_ENV in body
