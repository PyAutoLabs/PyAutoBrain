"""The questions inbox, watcher side (M3.5, PyAutoBrain#645).

A parked worker's question no longer @-mentions the human. It lands in
PyAutoMind `questions.md` through the one Mind writer (`question-add`, which
runs Mind's own `questions_edit.add_text` from the tree it writes), the digest
says once how many landed, an answer on Mind origin/main releases the parked
hold, and the next shift resumes the task, reusing a shift worker's claim, with
`RESUME_NOTE` and the answer in its prompt. The `claude` and `gh` binaries are
fakes; the Mind-writer legs use real git against a bare remote.
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
BATCH = BRAIN / "agents" / "conductors" / "batch"
MIND_SRC = BRAIN.parent / "PyAutoMind"
if not (MIND_SRC / "scripts" / "questions_edit.py").is_file():
    MIND_SRC = Path(os.environ.get("PYAUTO_MIND", "/nonexistent"))
HAVE_MIND = (MIND_SRC / "scripts" / "questions_edit.py").is_file() and shutil.which("git")
needs_mind = pytest.mark.skipif(not HAVE_MIND, reason="needs git and a PyAutoMind checkout "
                                                      "with scripts/questions_edit.py")
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BATCH))
sys.path.insert(0, str(BRAIN / "tests"))
import _brief  # noqa: E402
import _digest  # noqa: E402
import _mind_writer as mw  # noqa: E402
import _orchestrator as orch  # noqa: E402
import _questions  # noqa: E402
import _watch  # noqa: E402
import test_orchestrator_dispatch as d  # noqa: E402

NOW = d.NOW
ISSUE = "https://github.com/example-org/example-mind/issues/4242"
Q1 = "https://github.com/example-org/widgets/issues/70"
Q2 = "https://github.com/example-org/widgets/issues/71"


class FakeGh:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0, stdout=f"{ISSUE}#issuecomment-1\n", stderr="")


def _shift(tmp_path, names=("t1", "t2")):
    mind, brief, home = d._shift(tmp_path, names=names)
    brief.write_text(brief.read_text().replace(
        "- review-at: 2026-11-04T11:30Z\n", f"- review-at: 2026-11-04T11:30Z\n- issue: {ISSUE}\n"))
    return mind, brief, home, orch.slot_dir(brief, home)


def _tick(brief, mind, home, now, claude, gh, agents=None):
    return orch.tick(brief, mind, home=home, now=now, grace_s=0,
                     spawner=orch.RealSpawner(brief, "auto", run=claude),
                     agents=agents or orch.AgentsView([]), tokens=lambda s: 0,
                     poster=lambda issue, body: orch.gh_comment(issue, body, run=gh))


def _mentions(gh):
    """Comment bodies that @-mention or name a worker as needing the human
    (#611's mention form). Build A's needs-you event comments (`Shift … needs
    you: <event>`, no `@`) are not mentions; a scratch Mind triggers them."""
    bodies = [Path(a[a.index("--body-file") + 1]).read_text() for a in gh.calls
              if "--body-file" in a]
    return [b for b in bodies if "@" in b or "the worker on" in b]


def _ops(slot):
    return [json.loads(f.read_text()) for f in mw.pending_ops(slot)]


# --- landing: two parked workers, two ops, no mention, one digest line ------------

def test_two_parked_workers_give_two_ops_no_mention_and_one_digest_line(tmp_path,
                                                                        monkeypatch):
    monkeypatch.setenv(orch.MENTION_ENV, "example-human")
    mind, brief, home, slot = _shift(tmp_path)
    claude, gh = d.FakeClaude(), FakeGh()
    _tick(brief, mind, home, NOW, claude, gh)
    leases = slot / "leases"
    (leases / "t1.done").write_text(f"question: {Q1}\n")
    (leases / "t1.question.json").write_text(json.dumps({
        "issue": Q1, "ask": "Brass or steel?\n@example-human please",
        "options": ["brass", "steel", "#heading", "- dash", "five"]}))
    (leases / "t2.done").write_text(f"question: {Q2}\n")       # an old worker: no sidecar
    r = _tick(brief, mind, home, NOW + _dt.timedelta(minutes=5), claude, gh,
              d._agents({"t1": "done", "t2": "done"}, slot))
    assert sorted(e["task"] for e in r["reaped"]) == ["t1", "t2"]
    ops = sorted(_ops(slot), key=lambda o: o["entry"]["task"])
    assert [o["op"] for o in ops] == ["question-add", "question-add"]
    e1, e2 = (o["entry"] for o in ops)
    assert e1 == {"task": "draft/feature/pyautobrain/t1.md", "issue": Q1, "kind": "question",
                  "ask": "Brass or steel? example-human please",
                  "options": ["brass", "steel", "\\#heading", "\\- dash"],
                  "shift": slot.name, "asked": "2026-11-04T09:05Z", "worker": "00000001"}
    assert e2["ask"] == _questions.NO_SIDECAR_ASK and e2["options"] == []
    assert all(mw.validate_op(o, type("lm", (), {"is_ledger_path": staticmethod(
        lambda p: p == "questions.md")})) == [] for o in ops)
    # Zero @mentions: no mention comment mid-shift.
    assert _mentions(gh) == []
    c = orch.read_counters(slot)
    assert c["pushes"] == 0 and len(c["inbox"]) == 2
    # A re-tick queues nothing more.
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=8), claude, gh)
    assert len(_ops(slot)) == 2
    text = _digest.build(_brief.parse(brief.read_text())["brief"], slot, c,
                         health=lambda u: "HEALTHY", mind=mind)
    inbox = [ln for ln in text.splitlines() if ln.startswith("Inbox:")]
    assert inbox == ["Inbox: 2 questions added to your inbox this shift."]
    assert text.index("Inbox:") < text.index("### Brief work")
    assert not _digest.validate(text.replace("- none", "- none"))[:0]


def test_a_worker_blocked_past_the_grace_lands_a_blocked_entry_on_the_shift_issue(tmp_path):
    mind, brief, home, slot = _shift(tmp_path, names=("t1",))
    claude, gh = d.FakeClaude(), FakeGh()
    blocked = lambda: d._agents({"t1": "blocked"}, slot)  # noqa: E731
    _tick(brief, mind, home, NOW, claude, gh)
    assert orch.leases(slot)["t1"]["shift_issue"] == ISSUE
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=1), claude, gh, blocked())
    past = NOW + _dt.timedelta(minutes=1, seconds=orch.STALL_GRACE_S)
    r = _tick(brief, mind, home, past, claude, gh, blocked())
    assert r["reaped"][0]["event"] == "parked" and _mentions(gh) == []
    [op] = _ops(slot)
    assert op["entry"]["kind"] == "blocked" and op["entry"]["issue"] == ISSUE
    assert op["entry"]["ask"].startswith("the worker stopped at a prompt nobody answered "
                                         "(session 00000001, since 2026-11-04T09:01")


def test_the_status_comment_counts_the_inbox(tmp_path):
    mind, brief, home, slot = _shift(tmp_path, names=("t1",))
    claude, gh = d.FakeClaude(), FakeGh()
    _tick(brief, mind, home, NOW, claude, gh)
    (slot / "leases" / "t1.done").write_text(f"question: {Q1}\n")
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=5), claude, gh,
          d._agents({"t1": "done"}, slot))
    snap = _watch.snapshot(brief, slot, NOW + _dt.timedelta(minutes=6),
                           agents=orch.AgentsView([]), health=lambda u: "HEALTHY")
    assert "- inbox: 1 added this shift" in _watch.render_status(snap)
    assert "- inbox: 1 added this shift" in _watch.render(snap)


def test_sanitise():
    assert _questions.sanitise("  a\n b  ", 10) == "a b"
    assert _questions.sanitise("@someone ping", 50) == "someone ping"
    assert _questions.sanitise("# Heading", 50) == "\\# Heading"
    assert _questions.sanitise("x" * 30, 10) == "x" * 9 + "…"


# --- the parked hold: answered releases, the rest hold ---------------------------

def _home_with_parks(tmp_path):
    home = tmp_path / "home"
    old = home / "2026-11-14-pm2"
    old.mkdir(parents=True)
    (old / "counters.json").write_text(json.dumps({
        "outcomes": {"alpha": {"questions": [Q1], "prs": [], "merged": []},
                     "beta": {"questions": [Q2], "prs": [], "merged": []},
                     "gamma": {"questions": [Q1], "prs": [], "merged": []},
                     "delta": {"questions": [Q2], "prs": [], "merged": []}},
        "parked": ["eps"]}))
    now = home / "2026-11-16-am"
    now.mkdir()
    return now


def _inbox(answered_at="2026-11-15T08:00Z", **states):
    return {t: [{"id": f"Q{i}", "shift": "2026-11-14-pm2", "issue": Q1, "state": s,
                 "answered": answered_at if s == "answered" else "",
                 "answer": "yes" if s == "answered" else "",
                 "comment": f"{Q1}#issuecomment-{i}" if s == "answered" else ""}]
            for i, (t, s) in enumerate(states.items(), 1)}


def test_an_answered_question_releases_the_hold_and_records_the_resume(tmp_path):
    slot = _home_with_parks(tmp_path)
    resumes = {}
    held = orch.parked_elsewhere(slot, _inbox(alpha="answered", beta="dropped",
                                              gamma="open", delta="deferred", eps="answered"),
                                 resumes)
    assert "alpha" not in held and "eps" not in held
    assert resumes == {"alpha": {"ids": ["Q1"], "shift": "2026-11-14-pm2",
                                 "comments": [f"{Q1}#issuecomment-1"], "answers": ["yes"],
                                 "picked_in": []},
                       "eps": {"ids": ["Q5"], "shift": "2026-11-14-pm2",
                               "comments": [f"{Q1}#issuecomment-5"], "answers": ["yes"],
                               "picked_in": []}}
    assert held["beta"] == ("question Q2 dropped by the human: task shelved (reopen it, name "
                            "it in a brief, or /add it)")
    assert held["gamma"] == "waiting on Q3 in your inbox"
    assert held["delta"] == "waiting on Q4 in your inbox"


def test_an_unreadable_inbox_or_a_park_with_no_entry_keeps_every_hold(tmp_path):
    slot = _home_with_parks(tmp_path)
    before = orch.parked_elsewhere(slot)
    assert set(before) == {"alpha", "beta", "gamma", "delta", "eps"}
    resumes = {}
    assert orch.parked_elsewhere(slot, None, resumes) == before and resumes == {}
    assert orch.parked_elsewhere(slot, {}, resumes) == before and resumes == {}
    # An answer from another shift's park does not release this one.
    other = {"alpha": [{"id": "Q9", "shift": "2026-11-01-am", "state": "answered"}]}
    assert orch.parked_elsewhere(slot, other, resumes) == before and resumes == {}


def test_a_later_park_holds_again_and_a_later_finish_releases(tmp_path):
    slot = _home_with_parks(tmp_path)
    later = slot.parent / "2026-11-15-am"
    later.mkdir()
    (later / "counters.json").write_text(json.dumps({
        "outcomes": {"alpha": {"questions": [Q2], "prs": [], "merged": []},
                     "beta": {"prs": ["https://github.com/example-org/w/pull/1"]}},
        "parked": []}))
    resumes = {}
    held = orch.parked_elsewhere(slot, _inbox(alpha="answered", beta="dropped"), resumes)
    assert "alpha" in held and "alpha" not in resumes      # parked again, no entry yet
    assert "beta" not in held                              # finished since


def _resumed_in(home, name, task, outcome=None, workers=None):
    d = home / name
    d.mkdir()
    (d / "counters.json").write_text(json.dumps({
        "outcomes": {task: outcome} if outcome else {}, "parked": [],
        "picks": {task: {"prompt": f"active/{task}.md"}},
        "workers": workers or [{"key": "0000000a", "task": task,
                                "spawned": f"{name[:10]}T09:00:00Z", "exits": ["spawned"]}]}))


@pytest.mark.parametrize("outcome,exits", [
    (None, ["spawned"]),                     # still out at its review-at
    (None, ["spawned", "crashed", "late"]),  # crashed, or abandoned
])
def test_a_release_is_used_up_by_the_shift_that_resumed_it(tmp_path, outcome, exits):
    """#645 review: one answer resumes a task once. A resume that did not
    finish holds it again — never a second worker on the same claim."""
    slot = _home_with_parks(tmp_path)
    _resumed_in(slot.parent, "2026-11-15-am", "alpha", outcome,
                [{"key": "0000000a", "task": "alpha", "spawned": "2026-11-15T09:00:00Z",
                  "exits": exits}])
    resumes = {}
    held = orch.parked_elsewhere(slot, _inbox(alpha="answered"), resumes)
    assert "alpha" not in resumes
    assert held["alpha"] == ("resumed in shift 2026-11-15-am after Q1 and not finished — not "
                             "resumed again until a new answer (or name it in a brief)")
    # A re-answer given after that pick releases it once more.
    resumes = {}
    held = orch.parked_elsewhere(slot, _inbox(answered_at="2026-11-15T12:00Z",
                                              alpha="answered"), resumes)
    assert "alpha" not in held and resumes["alpha"]["ids"] == ["Q1"]
    assert resumes["alpha"]["picked_in"] == ["2026-11-15-am"]


def test_a_resume_that_parks_again_waits_on_its_new_question(tmp_path):
    slot = _home_with_parks(tmp_path)
    _resumed_in(slot.parent, "2026-11-15-am", "alpha",
                {"questions": [Q2], "prs": [], "merged": []})
    held = orch.parked_elsewhere(slot, _inbox(alpha="answered"), {})
    assert held["alpha"].startswith("parked on a question in shift 2026-11-15-am")


# --- the reader, the op, and Mind origin/main (real git) ---------------------------

def git(cwd, *args, check=True):
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check:
        assert res.returncode == 0, (args, res.stderr)
    return res


ACTIVE = """# Active tasks

## alpha-claim
- status: library-dev
- prompt: active/alpha.md
- session: shift worker 2026-11-14-pm2 (00000001)
- repos:
  - widgets_ws

## beta
- status: library-dev
- prompt: active/beta.md
- session: claude-code desktop (WSL), interactive

## gears-claim
- status: library-dev
- prompt: active/gears.md
- session: claude-code desktop (WSL), interactive
- repos:
  - gears_ws
"""

PROMPT = """\
# {name}

Type: docs
Target: widgets_ws
Repos:
- widgets_ws
Lane: any
Difficulty: small
Autonomy: supervised
Priority: normal
Status: formalised
Consequence: glance
Witness: a unit test
Review-minutes: 3
Unattended: ready

Body.
"""


def _git_mind(tmp_path, questions: str | None = None):
    """(bare remote, canonical clone) of a fictional Mind with the real scripts."""
    bare = tmp_path / "remote" / "PyAutoMind.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(bare), str(seed))
    for repo in (seed,):
        git(repo, "config", "user.name", "Test")
        git(repo, "config", "user.email", "test@example.invalid")
    (seed / "scripts").mkdir()
    for name in ("ledger_merge.py", "lifecycle.py", "questions_edit.py"):
        shutil.copy(MIND_SRC / "scripts" / name, seed / "scripts" / name)
    (seed / "active").mkdir()
    for n in ("alpha", "beta"):
        (seed / "active" / f"{n}.md").write_text(PROMPT.format(name=n.title()))
    (seed / "draft" / "docs" / "widgets_ws").mkdir(parents=True)
    (seed / "draft" / "docs" / "widgets_ws" / "gamma.md").write_text(
        PROMPT.format(name="Gamma"))
    (seed / "active.md").write_text(ACTIVE)
    (seed / "repos.yaml").write_text("repos:\n  PyAutoMind:\n    github: example-org/PyAutoMind\n")
    if questions is not None:
        (seed / "questions.md").write_text(questions)
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "seed")
    git(seed, "push", "-q", "origin", "HEAD:main")
    canon = tmp_path / "canon"
    git(tmp_path, "clone", "-q", str(bare), str(canon))
    git(canon, "config", "user.name", "Test")
    git(canon, "config", "user.email", "test@example.invalid")
    return bare, canon


def _entry(task, issue=Q1, shift="2026-11-14-pm2", ask="Brass or steel?"):
    return {"task": task, "issue": issue, "kind": "question", "ask": ask,
            "options": ["brass", "steel"], "shift": shift, "asked": "2026-11-14T18:12Z",
            "worker": "00000001"}


@needs_mind
def test_the_question_add_op_lands_through_minds_own_add_text(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    bare, canon = _git_mind(tmp_path)
    slot = tmp_path / "slot"
    ledger = slot / mw.LEDGER_DIR
    mw.queue_op(ledger, _questions.add_op(_entry("draft/docs/widgets_ws/alpha.md")))
    mw.queue_op(ledger, _questions.add_op(_entry("draft/docs/widgets_ws/gamma.md", Q2)))
    mw.queue_op(ledger, _questions.add_op(_entry("draft/docs/widgets_ws/gone.md")))
    res = mw.commit_ledger(slot, canon, "shift test: questions")
    assert res["committed"] and res["ops"] == 2
    assert [a["why"] for a in res["set_aside"]] == [
        "question-add: task draft/docs/widgets_ws/gone.md is in neither draft/ nor active/ "
        "on Mind main — set aside, nothing to resume"]
    assert res["held"] == []
    text = git(bare, "show", "main:questions.md").stdout
    entries = _questions.parse(text)
    assert [(e["id"], e["state"], e["fields"]["task"]) for e in entries] == [
        ("Q1", "open", "active/alpha.md"),                       # claimed since: resolved
        ("Q2", "open", "draft/docs/widgets_ws/gamma.md")]
    # The canonical tree is untouched, no Mind module or path leaks, and no
    # bytecode was committed.
    assert git(canon, "status", "--porcelain").stdout == ""
    assert "lifecycle" not in sys.modules or "PyAutoMind" not in str(
        getattr(sys.modules.get("lifecycle"), "__file__", ""))
    assert not any("mind-writer-" in p for p in sys.path)
    assert "__pycache__" not in git(bare, "ls-tree", "-r", "--name-only", "main").stdout
    # A replay of the same op is a skipped note, never a Q3.
    mw.queue_op(ledger, _questions.add_op(_entry("draft/docs/widgets_ws/alpha.md")))
    res = mw.commit_ledger(slot, canon, "shift test: replay")
    assert res["committed"] is None
    assert res["skipped"] == ["question-add: already in questions.md as Q1 — skipped"]
    # And lifecycle check stays clean on what landed.
    tree = tmp_path / "check"
    git(tmp_path, "clone", "-q", str(bare), str(tree))
    out = subprocess.run([sys.executable, "scripts/lifecycle.py", "check"], cwd=tree,
                         capture_output=True, text=True, env=dict(os.environ, LIFECYCLE_NO_GH="1"))
    assert "questions.md" not in out.stdout, out.stdout


def test_question_add_validation():
    lm = type("lm", (), {"is_ledger_path": staticmethod(lambda p: p in ("questions.md",
                                                                        "queue.md"))})
    good = _questions.add_op(_entry("draft/x/y/z.md"))
    assert mw.validate_op(good, lm) == []
    assert "path must be questions.md" in mw.validate_op(dict(good, path="queue.md"), lm)[0]
    bad = dict(good, entry=dict(good["entry"], ask="two\nlines", extra="x"))
    errs = mw.validate_op(bad, lm)
    assert any("unknown entry keys extra" in e for e in errs)
    assert any("ask must be one non-empty line" in e for e in errs)
    assert any("options must be a list" in e for e in mw.validate_op(
        dict(good, entry=dict(good["entry"], options="brass")), lm))


@needs_mind
def test_read_origin(tmp_path):
    bare, canon = _git_mind(tmp_path)
    assert _questions.read_origin(canon) == {}                   # nothing asked yet
    assert _questions.read_origin(tmp_path / "not-a-checkout") is None
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(bare), str(other))
    git(other, "config", "user.name", "Test")
    git(other, "config", "user.email", "test@example.invalid")
    sys.path.insert(0, str(MIND_SRC / "scripts"))
    import questions_edit as qe
    text, _q, _a = qe.add_text(qe.TEMPLATE, _entry("active/alpha.md"))
    (other / "questions.md").write_text(text)
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "q")
    git(other, "push", "-q", "origin", "HEAD:main")
    fetched = []
    got = _questions.read_origin(canon, fetch=lambda: fetched.append(
        git(canon, "fetch", "-q", "origin", "main")))
    assert fetched and got == {"alpha": [{"id": "Q1", "shift": "2026-11-14-pm2", "issue": Q1,
                                          "state": "open", "answer": "", "comment": "",
                                          "kind": "question", "gate": "",
                                          "task": "active/alpha.md", "answered": ""}]}


@needs_mind
def test_reader_parity_with_minds_parser():
    sys.path.insert(0, str(MIND_SRC / "scripts"))
    import questions_edit as qe
    text, _q, _a = qe.add_text(qe.TEMPLATE, _entry("active/alpha.md"))
    text, _q, _a = qe.add_text(text, _entry("draft/x/y/gamma.md", Q2, ask="Second?"))
    text, _q, _a = qe.add_text(text, _entry("draft/x/y/delta.md", ask="Third?"))
    import lifecycle
    text = lifecycle.question_move_text(text, "Q2", "answered",
                                        {"answered": "t by h (chat)", "answer": "yes"})
    text = lifecycle.question_move_text(text, "Q3", "dropped", {"dropped": "d by h — no"})
    mine = [(e["id"], e["n"], e["title"], e["state"], e["fields"]) for e in _questions.parse(text)]
    theirs = [(e["id"], e["n"], e["title"], e["state"], e["fields"]) for e in qe.parse(text)]
    assert mine == theirs and [m[3] for m in mine] == ["open", "answered", "dropped"]


# --- resume: a claimed task, the shift-worker rule, RESUME_NOTE ---------------------

@needs_mind
def test_a_claimed_task_resumes_only_with_a_shift_worker_session(tmp_path):
    bare, canon = _git_mind(tmp_path)
    resumes = {"alpha": {"ids": ["Q1"], "shift": "2026-11-14-pm2", "comments": [],
                         "picked_in": ["2026-11-14-pm2"]},
               "beta": {"ids": ["Q2"], "shift": "2026-11-14-pm2", "comments": [],
                        "picked_in": ["2026-11-14-pm2"]}}
    # The canonical checkout still shows stale drafts nobody pulled.
    stale = [{"path": "draft/docs/widgets_ws/alpha.md", "repos": ["widgets_ws"],
              "declared_repos": ["widgets_ws"]},
             {"path": "draft/docs/widgets_ws/beta.md", "repos": ["widgets_ws"],
              "declared_repos": ["widgets_ws"]}]
    recs = orch.resume_records(stale, canon, resumes)
    assert sorted(r["path"] for r in recs) == ["active/alpha.md", "active/beta.md"]
    assert all(r["resume"]["ids"] for r in recs)
    for r in recs:      # fictional repos: the grader knows none, so declare them here
        r["declared_repos"] = ["widgets_ws"]
    kept, out = orch.on_origin(recs, canon, set(), resumes=resumes)
    assert [r["path"] for r in kept] == ["active/alpha.md"]   # its own repo claim ignored
    # A repo another claim holds still keeps it out.
    held = [dict(recs[0], declared_repos=["gears_ws"])]
    kept2, out2 = orch.on_origin(held, canon, set(), resumes=resumes)
    assert kept2 == [] and out2 == {
        "active/alpha.md": "repo gears_ws claimed by `gears-claim` in active.md on Mind origin/main"}
    assert out == {"active/beta.md": "resumed after Q2, but its claim `beta` in active.md is "
                                     "not this home's shift worker's (session: claude-code "
                                     "desktop (WSL), interactive) — left to the human"}
    # A shift-worker line from a slot of another home (or one that never
    # picked the task) is not trusted either.
    other = {"alpha": dict(resumes["alpha"], picked_in=["2026-11-01-am"])}
    kept3, out3 = orch.on_origin(recs[:1], canon, set(), resumes=other)
    assert kept3 == [] and "not this home's shift worker's" in out3["active/alpha.md"]
    # Without a release, the same claimed tasks are dropped as before.
    kept, out = orch.on_origin(recs, canon, set())
    assert kept == [] and set(out) == {"active/alpha.md", "active/beta.md"}


def test_the_resumed_worker_prompt_carries_resume_note_and_the_pick_names_the_answer(tmp_path):
    resume = {"ids": ["Q17"], "shift": "2026-11-14-pm2",
              "comments": [f"{Q1}#issuecomment-9"], "answers": ["(a) brass"]}
    argv = orch.session_command("alpha", "active/alpha.md", tmp_path / "shift.md",
                                tmp_path / "leases", "auto", resume=resume)
    prompt = argv[-1]
    assert prompt.startswith("This task parked on a question in shift `2026-11-14-pm2` and "
                             "the human has answered\nit (Q17): see \"## Answers from the "
                             "human\" in your prompt (and "
                             f"{Q1}#issuecomment-9).")
    assert "do not queue the claim\nagain" in prompt
    assert "The answer:\n> (a) brass\n" in prompt
    assert "Use the start-dev skill. active/alpha.md --auto" in prompt
    assert "RE-DISPATCH" not in prompt
    rec = orch.pick_record({"path": "active/alpha.md", "resume": resume, "queued": True,
                            "queue_rank": 1}, {"backlog": {"value": "fill-idle"}})
    assert rec["why"] == "resumed after Q17 was answered · backlog: fill-idle · queue.md #2"


def test_the_worker_template_pins_the_session_line_and_the_sidecar():
    text = (BATCH / "worker_template.md").read_text()
    assert "- session: shift worker" in text
    assert ".question.json" in text and "the watcher @-mentions" not in text
    assert orch.shift_worker_slot("shift worker 2026-11-16-am (00000001)") == "2026-11-16-am"
    for loose in ("Claude Code background job (shift 2026-11-14-pm2 worker)",
                  "claude-code shift worker (batch 2026-11-14-pm2, --auto)",
                  "claude-code desktop (WSL)", "taken over: shift worker x (y) by hand"):
        assert orch.shift_worker_slot(loose) == "", loose


# --- the dashboard section ----------------------------------------------------------

_spec = importlib.util.spec_from_file_location(
    "_intake_questions_under_test", BRAIN / "agents" / "conductors" / "intake" / "_intake.py")
_intake = importlib.util.module_from_spec(_spec)
sys.modules["_intake_questions_under_test"] = _intake
_spec.loader.exec_module(_intake)

QUESTIONS = """# Questions

```markdown
### Q<n>. <task> — <short ask>
- task: draft/<work-type>/<target>/<name>.md
```

## Open

### Q17. sprockets — Brass <b>or</b> steel?
- task: draft/feature/widgets/sprockets.md
- issue: https://github.com/example-owner/widgets/issues/70
- kind: question
- ask: Brass <b>or</b> steel?
- options: (a) brass · (b) steel
- shift: 2026-11-14-pm2
- asked: 2026-11-14T18:12Z
- worker: a1b2c3d4

## Deferred

### Q18. levers — Which lever?
- task: draft/feature/widgets/levers.md
- issue: https://github.com/example-owner/widgets/issues/71
- kind: question
- ask: Which lever?
- shift: 2026-11-14-pm2
- asked: 2026-11-14T18:30Z
- worker: a1b2c3d4
- until: 2026-11-20

## Answered

### Q16. gears — Done?
- task: draft/feature/widgets/gears.md
- issue: https://github.com/example-owner/widgets/issues/69
- kind: question
- ask: Done?
- shift: 2026-11-14-pm
- asked: 2026-11-14T10:00Z
- worker: a1b2c3d4
- answered: 2026-11-15T09:00Z by example-human (chat)
- answer: yes

## Dropped
"""


def _dash_mind(tmp_path, questions=QUESTIONS):
    sys.path.insert(0, str(BRAIN / "tests"))
    import test_intake_dashboard_queue as q
    root = q._mind(tmp_path)
    if questions is not None:
        (root / "questions.md").write_text(questions, encoding="utf-8")
    return root


def _csp(page):
    return re.search(r"script-src '(sha256-[^']+)'", page).group(1)


def _questions_part(page):
    """The Questions sub-part of the Autopilot block (PyAutoBrain#650)."""
    start = page.index('<h3 id="inbox">')
    return page[start:page.index('<h3 id="shift">', start)]


def test_the_inbox_section_renders_read_only_with_copy_buttons(tmp_path):
    with_q = _intake.render_dashboard_html(_intake.census(_dash_mind(tmp_path / "a")))
    without = _intake.render_dashboard_html(_intake.census(_dash_mind(tmp_path / "b", None)))
    # The CSP hash is unchanged: no new script, the page's one handler serves it.
    assert _csp(with_q) == _csp(without)
    script = re.findall(r"<script>(.*?)</script>", with_q, re.S)
    assert len(script) == 1
    assert _csp(with_q) == "sha256-" + base64.b64encode(
        hashlib.sha256(script[0].encode()).digest()).decode()
    box = _questions_part(with_q)
    assert box.startswith('<h3 id="inbox">Questions <span class="facets">(1 open, 1 deferred')
    # Ordinary task rows: the sitting's 📋, then one per question.
    assert ('<div class="task"><button class="copy" data-cmd="Use the questions skill." '
            in box)
    assert ('<div class="task"><button class="copy" data-cmd="Use the questions skill. Q17" '
            in box)
    sys.path.insert(0, str(BRAIN))
    from board.copy_contract import assert_portable_copy_payloads
    assert_portable_copy_payloads(with_q)            # no slash-skill clipboard text
    assert "Brass &lt;b&gt;or&lt;/b&gt; steel?" in box and "<b>or</b>" not in box
    assert "(a) brass · (b) steel" in box
    assert '<a href="https://github.com/example-owner/widgets/issues/70">issue #70</a>' in box
    assert "from shift 2026-11-14-pm2" in box
    assert "<details>\n<summary>1 deferred</summary>" in box
    assert "deferred until 2026-11-20" in box
    assert "Q16" not in box                                    # answered: not shown
    assert "read-only; answer by pasting a 📋 into a chat" in box
    for gone in ("<form", "<input", "<textarea", "fetch(", "<aside", 'class="qid"'):
        assert gone not in box
    # Inside the one Autopilot block, straight above Start here — never a box
    # of its own above the section cards.
    assert '<aside class="inbox"' not in with_q
    assert with_q.index('<nav class="board-nav"') \
        < with_q.index("<h2>Autopilot</h2>") \
        < with_q.index('<h3 id="inbox">') < with_q.index("<h2>Start here</h2>")
    assert '<span class="section-badge">2 queued · 1 question</span>' in with_q
    md = _intake.render_dashboard(_intake.census(_dash_mind(tmp_path / "c")))
    sec = md[md.index("**Questions**"):md.index("**Shift**")]
    assert sec.startswith("**Questions** (1 open, 1 deferred")
    assert "- Q17 — Brass &lt;b&gt;or&lt;/b&gt; steel? " \
           "(https://github.com/example-owner/widgets/issues/70" in sec


def test_an_absent_inbox_renders_empty(tmp_path):
    page = _intake.render_dashboard_html(_intake.census(_dash_mind(tmp_path, None)))
    box = _questions_part(page)
    assert "(0 open, 0 deferred" in box
    assert '<p class="muted">(no open questions)</p>' in box


def test_the_digest_link_is_the_dashboards_inbox_anchor(tmp_path):
    root = _dash_mind(tmp_path, None)
    assert _questions.dashboard_link(root) == "https://example-owner.github.io/PyAutoMind/#inbox"
    c = {"inbox": [{"task": "a", "issue": Q1}]}
    origin = {"a": [{"id": "Q3", "shift": "s1", "state": "open"}],
              "b": [{"id": "Q2", "shift": "s0", "state": "open"},
                    {"id": "Q1", "shift": "s0", "state": "answered"}]}
    assert _questions.inbox_line(c, "s1", root, origin) == (
        "Inbox: 1 question added to your inbox this shift (Q3), 2 open in all — "
        "https://example-owner.github.io/PyAutoMind/#inbox.")
    assert _questions.inbox_line({}, "s1", root, origin) == ""


# --- the /questions skill ---------------------------------------------------------

SKILL = BRAIN / "skills" / "questions"


def test_the_skill_ships_and_follows_the_queue_conventions():
    front = dict(line.split(": ", 1) for line in
                 (SKILL / "SKILL.md").read_text().split("---", 2)[1].strip().splitlines())
    assert front["name"] == "questions" and "never start dev" in front["description"]
    proc = (SKILL / "questions.md").read_text()
    assert "worktree add -q --detach" in proc and "origin/main" in proc
    assert re.search(r'prompt_sync_push "questions: [^"]*" questions\.md', proc)
    assert "PROMPT_SYNC_PUSH_TO=main" in proc
    assert "python3 scripts/lifecycle.py check" in proc
    assert "rebase origin/main" not in proc and "push origin" not in proc
    assert "Never hand-edit\n`questions.md`" in proc or "Never hand-edit `questions.md`" in proc
    assert "never a start-dev" in proc
    assert "../queue/queue.md" in proc
    for verb in ("answer Q<n>", "defer Q<n>", "drop Q<n>", "reopen Q<n>", "show --open"):
        assert verb in proc, verb
    for link in (BRAIN / ".claude" / "skills" / "questions", BRAIN / ".codex" / "skills" /
                 "questions", BRAIN / ".claude" / "commands" / "questions.md"):
        assert link.is_symlink() and link.resolve().exists(), link
    commands = (BRAIN / "skills" / "COMMANDS.md").read_text()
    assert "**`/questions`**" in commands


def test_a_later_claim_on_the_same_repo_refuses_the_resume(tmp_path, monkeypatch):
    """#645 review: `claimed_repos` keeps one claim per repo; with the task's
    own claim first, a desktop claim on the same repo after it must still
    refuse the resume."""
    active = ("# Active\n\n## alpha-claim\n- prompt: active/alpha.md\n"
              "- session: shift worker 2026-11-14-pm2 (00000001)\n- repos:\n  - widgets_ws\n\n"
              "## desk\n- prompt: active/desk.md\n- session: claude-code desktop (WSL)\n"
              "- repos:\n  - widgets_ws\n")
    sections = orch.claim_sections(active)
    assert orch.claimed_repos(sections)[orch._repo_key("widgets_ws")][1] == "alpha-claim"
    monkeypatch.setattr(orch, "origin_claims", lambda mind, fetch=None: {
        "drafts": set(), "active": set(sections), "sections": sections,
        "repos": orch.claimed_repos(sections)})
    rec = {"path": "active/alpha.md", "declared_repos": ["widgets_ws"]}
    resumes = {"alpha": {"ids": ["Q1"], "picked_in": ["2026-11-14-pm2"]}}
    kept, out = orch.on_origin([rec], tmp_path, set(), resumes=resumes)
    assert kept == [] and out == {
        "active/alpha.md": "repo widgets_ws claimed by `desk` in active.md on Mind origin/main"}


def test_a_merged_outcome_lands_no_question_and_retires_the_inbox(tmp_path):
    """#645 review: a `.done` that merged in-turn files no question, and its
    open inbox entries are answered as the queue entry is retired."""
    mind, brief, home, slot = _shift(tmp_path, names=("t1",))
    claude, gh = d.FakeClaude(), FakeGh()
    _tick(brief, mind, home, NOW, claude, gh)
    (slot / "leases" / "t1.done").write_text(
        f"merged https://github.com/example-org/widgets/pull/9\nquestion: {Q1}\n")
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=5), claude, gh,
          d._agents({"t1": "done"}, slot))
    ops = _ops(slot)
    assert [o["op"] for o in ops] == ["queue-retire", "question-retire"]
    assert ops[1] == {"op": "question-retire", "path": "questions.md", "prompt": "t1.md",
                      "day": "2026-11-04", "by": "the shift worker, in-turn"}
    assert "inbox" not in orch.read_counters(slot)


@needs_mind
def test_question_retire_answers_a_dangling_blocked_entry_on_the_remote(tmp_path):
    sys.path.insert(0, str(MIND_SRC / "scripts"))
    import questions_edit as qe
    text, _q, _a = qe.add_text(qe.TEMPLATE, dict(_entry("active/alpha.md"), kind="blocked"))
    bare, canon = _git_mind(tmp_path, questions=text)
    slot = tmp_path / "slot"
    counters = {"picks": {"alpha": {"prompt": "draft/docs/widgets_ws/alpha.md"}}}
    mw.queue_op(slot / mw.LEDGER_DIR, orch.question_retire_op(
        counters, "alpha", _dt.datetime(2026, 11, 16, tzinfo=_dt.timezone.utc)))
    res = mw.commit_ledger(slot, canon, "shift test: retire")
    assert res["committed"]
    [e] = _questions.parse(git(bare, "show", "main:questions.md").stdout)
    assert e["state"] == "answered" and e["fields"]["answer"] == "(task completed)"
    assert e["fields"]["answered"] == "2026-11-16 by the unattended close-out (close)"


def test_question_ops_are_held_on_a_missing_script(tmp_path):
    """#645 review: a Mind main without questions_edit.py holds a question
    (critical), never sets it aside."""
    assert mw.is_critical(_questions.add_op(_entry("draft/x/y/z.md")))
    assert mw.is_critical({"op": "question-retire"})
    tree = tmp_path / "tree"
    (tree / "scripts").mkdir(parents=True)
    with pytest.raises(mw.MindWriteError) as e:
        mw.apply_op(tree, _questions.add_op(_entry("draft/x/y/z.md")),
                    type("lm", (), {})())
    assert not isinstance(e.value, mw.GoneError)


def test_an_unfiled_question_is_named_in_the_digest(tmp_path):
    mind, brief, home, slot = _shift(tmp_path, names=("t1",))
    claude, gh = d.FakeClaude(), FakeGh()
    _tick(brief, mind, home, NOW, claude, gh)
    lease = orch.leases(slot)["t1"]
    c = orch.read_counters(slot)
    assert not orch.land_question(slot, c, dict(lease, shift_issue=""), "t1",
                                  "", "blocked", "x", [], "k", NOW)
    assert not orch.land_question(slot, c, lease, "t1", "issue-70", "question", "x", [],
                                  "k", NOW)
    text = _digest.build(_brief.parse(brief.read_text())["brief"], slot, c,
                         health=lambda u: "HEALTHY")
    assert ("Inbox: not filed — `t1` (blocked): no shift issue on its lease (spawned before "
            "M3.5); see the task's issue or session yourself.") in text
    assert "Inbox: not filed — `t1` (question): issue `issue-70` is not an https URL" in text


def test_the_stream_says_added_to_your_inbox_only_for_a_filed_question(tmp_path):
    """Build A's `question` / `parked` stream lines (DESIGN §1.4) carry
    "Added to your inbox." and `inbox: true` once the reap filed it (#645)."""
    import _events
    mind, brief, home, slot = _shift(tmp_path)
    claude, gh = d.FakeClaude(), FakeGh()
    _tick(brief, mind, home, NOW, claude, gh)
    (slot / "leases" / "t1.done").write_text(f"question: {Q1}\n")
    (slot / "leases" / "t2.done").write_text(
        f"merged https://github.com/example-org/widgets/pull/9\nquestion: {Q2}\n")
    _tick(brief, mind, home, NOW + _dt.timedelta(minutes=5), claude, gh,
          d._agents({"t1": "done", "t2": "done"}, slot))
    qs = {e["task"]: e for e in _events.read_events(slot) if e["kind"] == "question"}
    assert qs["t1"]["line"] == "t1 parked with a question on widgets#70. Added to your inbox."
    assert qs["t1"]["inbox"] is True and not qs["t1"]["needs_you"]
    assert qs["t2"]["line"] == "t2 parked with a question on widgets#71."   # merged: not filed
    assert "inbox" not in qs["t2"]


def test_the_inbox_section_shows_a_ruling_by_its_gate_and_counts_it_apart(tmp_path):
    ruling = ("### Q19. cogs — Repo claimed: wait, coordinate or drop?\n"
              "- task: draft/feature/widgets/cogs.md\n- kind: ruling\n- gate: claimed\n"
              "- ask: Repo claimed: wait, coordinate or drop?\n"
              "- options: (a) wait · (b) coordinate\n- shift: ready-2026-11-18\n"
              "- asked: 2026-11-18T18:00Z\n- worker: readiness pass\n\n")
    text = QUESTIONS.replace("## Deferred\n", ruling + "## Deferred\n")
    page = _intake.render_dashboard_html(_intake.census(_dash_mind(tmp_path / "a", text)))
    box = _questions_part(page)
    assert box.startswith('<h3 id="inbox">Questions <span class="facets">(1 open, 1 deferred, '
                          '1 ruling')
    assert '<span class="facets">ruling claimed</span>' in box and "()" not in box
    assert '<span class="section-badge">2 queued · 1 question</span>' in page
    md = _intake.render_dashboard(_intake.census(_dash_mind(tmp_path / "b", text)))
    sec = md[md.index("**Questions**"):md.index("**Shift**")]
    assert sec.startswith("**Questions** (1 open, 1 deferred, 1 ruling")
    assert "- Q19 — Repo claimed: wait, coordinate or drop? (ruling claimed" in sec


# --- a question sidecar is never a lease (2026-11-20-am) ---------------------------

def test_a_question_sidecar_is_not_a_lease_and_holds_no_worker_slot(tmp_path):
    """Each parked worker's `{task}.question.json` was read as a lease with no
    pid, `_alive(0)` called it running, and it held a worker slot until
    `review-at:`: four of them filled `max-workers 4` and 11 tasks waited."""
    mind, brief, home, slot = _shift(tmp_path)
    claude, gh = d.FakeClaude(), FakeGh()
    _tick(brief, mind, home, NOW, claude, gh)
    leases = slot / "leases"
    for task, q in (("t1", Q1), ("t2", Q2)):
        (leases / f"{task}.done").write_text(f"question: {q}\n")
        (leases / f"{task}.question.json").write_text(json.dumps(
            {"issue": q, "ask": "Brass or steel?", "options": ["brass", "steel"]}))
    later = NOW + _dt.timedelta(minutes=5)
    _tick(brief, mind, home, later, claude, gh, d._agents({"t1": "done", "t2": "done"}, slot))
    # The sidecars outlive the reap, and none of them is a lease.
    assert sorted(f.name for f in leases.glob("*.question.json")) == [
        "t1.question.json", "t2.question.json"]
    assert orch.leases(slot) == {} and _digest.held_leases(slot) == {}
    c = orch.read_counters(slot)
    assert not [w for w in c["workers"] if w["task"].endswith(".question")]
    # A later tick refuses nothing on `max-workers` and adds no phantom worker.
    r = _tick(brief, mind, home, later + _dt.timedelta(minutes=2), claude, gh)
    assert not [x for x in r.get("refused") or [] if "max-workers" in str(x.get("why"))]
    c = orch.read_counters(slot)
    assert not [w for w in c["workers"] if w["task"].endswith(".question")]
