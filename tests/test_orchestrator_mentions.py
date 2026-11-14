"""PyAutoBrain#611 (M1.6): a blocked shift worker reaches the human through a
GitHub @mention on the shift's digest issue (the human's channel ruling,
2026-11-12). The `gh` call sits behind a fake `run`, so nothing reaches
GitHub; the login comes from the environment or config, never the code.
"""

from __future__ import annotations

import datetime as _dt

import pytest
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
    (slot / "leases" / "t1.done").write_text("question: https://github.com/o/r/issues/77\n")
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=5), claude, gh,
          d._agents({"t1": "done"}, slot))
    assert len(gh.calls) == 1
    body = gh.calls[0][1]
    assert "needs you — awaiting-input." in body
    assert "parked on its issue with a question: https://github.com/o/r/issues/77" in body


def test_only_an_explicit_verdict_is_not_a_push(tmp_path, monkeypatch):
    """PyAutoBrain#632 (F2, review): a research worker's posted `verdict:` is
    its deliverable and waits for the digest — in any case, colon or not."""
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGh()
    _tick(brief, mind, home, NOW, claude, gh)
    (slot / "leases" / "t1.done").write_text("VERDICT:https://github.com/o/r/issues/77\n")
    for m in (5, 8):
        _tick(brief, mind, home, NOW + _dt.timedelta(minutes=m), claude, gh,
              d._agents({"t1": "done"}, slot))
    c = orch.read_counters(slot)
    assert gh.calls == [] and c["pushes"] == 0
    assert c["outcomes"]["t1"]["verdicts"] == ["https://github.com/o/r/issues/77"]
    assert c["outcomes"]["t1"]["prs"] == []


@pytest.mark.parametrize("done", ["https://github.com/o/r/issues/77\n",
                                  "Question:https://github.com/o/r/issues/77\n",
                                  "QUESTION https://github.com/o/r/issues/77\n",
                                  "verdikt: https://github.com/o/r/issues/77\n",
                                  "blocked: https://github.com/o/r/issues/77\n"])
def test_any_issue_not_marked_verdict_is_a_push(tmp_path, monkeypatch, done):
    """PyAutoBrain#632 review: the push test fails toward the human — a bare
    URL, a mis-cased or colon-less `question`, or an unknown marker mentions."""
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGh()
    _tick(brief, mind, home, NOW, claude, gh)
    (slot / "leases" / "t1.done").write_text(done)
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=5), claude, gh,
          d._agents({"t1": "done"}, slot))
    assert len(gh.calls) == 1 and "needs you — awaiting-input." in gh.calls[0][1]
    assert orch.read_counters(slot)["outcomes"]["t1"]["issues"] == [
        "https://github.com/o/r/issues/77"]


def test_the_login_comes_from_the_environment_or_config_never_the_code(tmp_path, monkeypatch):
    blank = tmp_path / "policy.yaml"
    blank.write_text("shift_watcher:\n  mention_login: \"\"\n", encoding="utf-8")
    monkeypatch.setattr(orch, "POLICY_PATH", blank)   # hermetic: never the shipped config
    monkeypatch.delenv(orch.MENTION_ENV, raising=False)
    assert orch.mention_login() == ""           # a blank config leaves it blank
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


# --- #611 review -------------------------------------------------------------------

def test_a_tick_that_died_after_parking_still_mentions_on_the_next(tmp_path, monkeypatch):
    """Review item 1: the trigger is durable state, not the parking tick's events."""
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGh()
    real = orch._mentions
    blocked = lambda: d._agents({"t1": "blocked"}, slot)  # noqa: E731
    _tick(brief, mind, home, NOW, claude, gh)
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=1), claude, gh, blocked())
    monkeypatch.setattr(orch, "_mentions", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("tick died")))
    try:
        _tick(brief, mind, home, PAST_GRACE, claude, gh, blocked())   # parks, then dies
    except RuntimeError:
        pass
    assert orch.read_counters(slot)["parked"] == ["t1"] and gh.calls == []
    orch._drop_lock(slot)
    monkeypatch.setattr(orch, "_mentions", real)
    _tick(brief, mind, home, PAST_GRACE + _dt.timedelta(minutes=3), claude, gh,
          d._agents({"t1": "blocked"}, slot))
    assert len(gh.calls) == 1 and "needs you — parked." in gh.calls[0][1]


def test_a_failed_mention_is_retried_in_the_late_sweep(tmp_path, monkeypatch):
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGh(fail=1)
    _park(brief, mind, home, slot, claude, gh)
    assert len(gh.calls) == 1                                  # failed
    after = NOW + _dt.timedelta(hours=3)
    poster = lambda issue, body: orch.gh_comment(issue, body, run=gh)  # noqa: E731
    orch.tick(brief, mind, home=home, now=after, grace_s=0, poster=poster,
              agents=d._agents({"t1": "blocked"}, slot), tokens=lambda s: 0,
              pr_state=lambda u: None, health=lambda u: "HEALTHY")   # digest + finish
    r = orch.tick(brief, mind, home=home, now=after + _dt.timedelta(minutes=5), grace_s=0,
                  poster=poster, agents=d._agents({"t1": "blocked"}, slot),
                  tokens=lambda s: 0)
    assert r["action"] == "late"
    assert r["posts"]["mentions"] == [{"task": "t1", "state": "parked", "post": "posted",
                                       "retry": 2}]
    mention_calls = [b for _, b in gh.calls if "needs you" in b]
    assert len(mention_calls) == 2 and orch.read_counters(slot)["pushes"] == 1


def test_a_separate_token_posts_and_a_self_mention_is_warned(tmp_path, monkeypatch):
    """Review item 4: PYAUTO_SHIFT_GH_TOKEN is given to the watcher's `gh` as
    GH_TOKEN; mentioning the posting account itself is a digest warning."""
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    monkeypatch.setenv(orch.GH_TOKEN_ENV, "test-token-not-real")
    claude, gh = d.FakeClaude(), FakeGh()
    envs = []

    def run(argv, **kw):
        envs.append((kw.get("env") or {}).get("GH_TOKEN"))
        return gh(argv, **kw)
    blocked = lambda: d._agents({"t1": "blocked"}, slot)  # noqa: E731
    asked = []
    for now, agents in ((NOW, None), (NOW + _dt.timedelta(minutes=1), blocked),
                        (PAST_GRACE, blocked), (PAST_GRACE + _dt.timedelta(minutes=3), blocked)):
        orch.tick(brief, mind, home=home, now=now, grace_s=0,
                  spawner=orch.RealSpawner(brief, "auto", run=claude),
                  agents=agents() if agents else orch.AgentsView([]), tokens=lambda s: 0,
                  poster=lambda i, b: orch.gh_comment(i, b, run=run),
                  whoami=lambda: asked.append(1) or LOGIN)
    assert envs == ["test-token-not-real"] and asked == [1]     # checked once per shift
    c = orch.read_counters(slot)
    text = _digest.build(_brief.parse(brief.read_text())["brief"], slot, c,
                         health=lambda u: "HEALTHY")
    assert "mention will not notify: posted as the mentioned account" in text
    c.update(poster_login="example-bot")
    assert "will not notify" not in _digest.build(
        _brief.parse(brief.read_text())["brief"], slot, c, health=lambda u: "HEALTHY")
    login_calls = []
    assert orch.gh_login(run=lambda argv, **kw: login_calls.append((argv, kw["env"]["GH_TOKEN"]))
                         or SimpleNamespace(returncode=0, stdout="example-bot\n")) == "example-bot"
    assert login_calls == [(["gh", "api", "user", "--jq", ".login"], "test-token-not-real")]


def test_the_watchers_posting_token_never_reaches_a_worker_or_closeout(tmp_path, monkeypatch):
    """#611 re-review: the bot token is the watcher's alone."""
    monkeypatch.setenv(orch.GH_TOKEN_ENV, "bot-token-not-real")
    monkeypatch.setenv("GITHUB_TOKEN", "bot-token-not-real")     # derived from it
    monkeypatch.setenv("GH_TOKEN", "human-token-not-real")       # the human's own: kept
    mind, brief, home = d._shift(tmp_path)
    claude = d.FakeClaude()
    sp = orch.RealSpawner(brief, "auto", run=claude)
    sp.spawn("t1", "draft/feature/pyautobrain/t1.md", tmp_path / "leases")
    sp.spawn_closeout("t1", "https://github.com/o/r/pull/1", "x.md", tmp_path / "leases")
    for _argv, kw in claude.calls:
        env = kw["env"]
        assert orch.GH_TOKEN_ENV not in env and "GITHUB_TOKEN" not in env
        assert "bot-token-not-real" not in env.values()
        assert env["GH_TOKEN"] == "human-token-not-real"
    assert len(claude.calls) == 2
