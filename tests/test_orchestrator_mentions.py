"""Nobody is @-mentioned mid-shift: a parked worker and a question land in the
questions inbox. Also the human's login (environment or config, never the
code) and the watcher's own posting token. The `gh` call sits behind a fake
`run`, so nothing reaches GitHub."""

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


@pytest.fixture(autouse=True)
def _issue_reads_answer(monkeypatch):
    """The shift issue's comments read answers "no comments" — these tests are
    about mentions, not steering, and never reach GitHub. A read that failed
    three ticks in a row would be its own needs-you event (#644)."""
    monkeypatch.setattr(orch, "gh_issue_comments", lambda issue, since, run=None: [])


@pytest.fixture(autouse=True)
def _scratch_mind_writes_nothing(monkeypatch):
    """The scratch Mind here is not a git Mind, so the questions a park now
    files (`question-add`, #645) could only fail to commit — itself a
    needs-you event (#644). These tests are about mentions: the ops stay
    pending, unread; `test_questions_inbox.py` lands them on a real Mind."""
    monkeypatch.setattr(orch._mind_writer, "commit_ledger",
                        lambda *a, **k: {"committed": None, "ops": 0})


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


def _question_ops(slot):
    import _mind_writer as mw
    import json
    return [json.loads(f.read_text())["entry"] for f in mw.pending_ops(slot)
            if json.loads(f.read_text()).get("op") == "question-add"]


@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
def test_a_worker_parked_on_its_issue_is_filed_in_the_inbox_not_mentioned(tmp_path,
                                                                          monkeypatch):
    """M3.5 (#645): the question lands in questions.md; nobody is @-mentioned."""
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGh()
    _tick(brief, mind, home, NOW, claude, gh)
    (slot / "leases" / "t1.done").write_text("question: https://github.com/o/r/issues/77\n")
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=5), claude, gh,
          d._agents({"t1": "done"}, slot))
    assert gh.calls == [] and orch.read_counters(slot)["pushes"] == 0
    [entry] = _question_ops(slot)
    assert (entry["issue"], entry["kind"]) == ("https://github.com/o/r/issues/77", "question")


@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
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
@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
def test_any_issue_not_marked_verdict_is_filed_in_the_inbox(tmp_path, monkeypatch, done):
    """PyAutoBrain#632 review: the test fails toward the human — a bare URL, a
    mis-cased or colon-less `question`, or an unknown marker is a question.
    Since M3.5 (#645) it lands in the inbox instead of a mention."""
    mind, brief, home, slot = _shift(tmp_path, monkeypatch)
    claude, gh = d.FakeClaude(), FakeGh()
    _tick(brief, mind, home, NOW, claude, gh)
    (slot / "leases" / "t1.done").write_text(done)
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=5), claude, gh,
          d._agents({"t1": "done"}, slot))
    assert gh.calls == []
    assert [e["issue"] for e in _question_ops(slot)] == ["https://github.com/o/r/issues/77"]
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


def test_the_watchers_gh_calls_carry_its_own_token(monkeypatch):
    """PYAUTO_SHIFT_GH_TOKEN is given to the watcher's `gh` as GH_TOKEN."""
    monkeypatch.setenv(orch.GH_TOKEN_ENV, "test-token-not-real")
    gh, envs = FakeGh(), []

    def run(argv, **kw):
        envs.append((kw.get("env") or {}).get("GH_TOKEN"))
        return gh(argv, **kw)
    body = Path(__file__)
    orch.gh_comment(ISSUE, body, run=run)
    assert envs == ["test-token-not-real"]
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
