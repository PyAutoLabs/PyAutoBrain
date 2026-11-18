"""The readiness pass, `batch ready` (M3.3 slice 1, PyAutoBrain#671).

It walks Mind `queue.md`, resolves each entry to its next startable unit(s),
checks the gates, and files each gate as a questions-inbox entry of kind
`ruling` through the shift's one Mind writer (`question-add`). It runs at the
end of every shift, and the digest ends "The next shift needs N rulings from
you." The fixture Mind is a git repo whose `origin/main` is a local ref: the
pass reads it locally and never fetches.
"""

from __future__ import annotations

import datetime as _dt
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
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BATCH))
sys.path.insert(0, str(BRAIN / "tests"))
import _batch  # noqa: E402
import _brief  # noqa: E402
import _digest  # noqa: E402
import _mind_writer as mw  # noqa: E402
import _orchestrator as orch  # noqa: E402
import _questions  # noqa: E402
import test_orchestrator_dispatch as d  # noqa: E402

needs_git = pytest.mark.skipif(not shutil.which("git"), reason="needs git")

NOW = d.NOW
FOLDER = "draft/feature/pyautogut"
EPIC = f"{FOLDER}/example_epic.md"
TASK = f"{FOLDER}/example_task.md"
LAST = "The next shift needs 2 rulings from you."

PROMPT = """\
# {name}

Type: feature
Target: PyAutoGut
Repos:
- PyAutoGut
{extra}Lane: any
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

LEDGER = """\
# Example epic

Epic: example-epic
Type: feature
Target: PyAutoGut
Status: campaign map

| Phase | What |
|---|---|
| 1 | done |
| 2 | next, no prompt yet |
"""

QUEUE = """\
# Queue

```
## <n>. <label>
- kind: prompt
- ref: draft/x.md
```

## 1. Example epic
- kind: prompt
- ref: {epic}

## 2. Example task
- kind: prompt
- ref: {task}
"""

ACTIVE = """\
# Active tasks

## other-task
- status: library-dev
- prompt: active/other_task.md
- session: claude-code desktop (WSL), interactive
- repos:
  - PyAutoGut
"""

LIFECYCLE = 'QUESTION_KINDS = ({kinds})\n'


def git(cwd, *args):
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert res.returncode == 0, (args, res.stderr)
    return res


def _prompt(name, extra="", **swap):
    text = PROMPT.format(name=name, extra=extra)
    for key, value in swap.items():
        text = re.sub(rf"(?m)^{key}:.*$", f"{key}: {value}", text)
    return text


def _mind(tmp_path, files=None, *, ruling=True, queue=None, active=ACTIVE,
          questions=None):
    """A fixture Mind: a git repo on `main` whose `origin/main` is a local ref
    (the pass never fetches). `files` adds or replaces prompts."""
    mind = tmp_path / "m"
    tree = {
        "scripts/lifecycle.py": LIFECYCLE.format(kinds=", ".join(
            repr(k) for k in ("question", "blocked") + (("ruling",) if ruling else ()))),
        "queue.md": queue if queue is not None else QUEUE.format(epic=EPIC, task=TASK),
        "active.md": active,
        EPIC: LEDGER,
        TASK: _prompt("Example task"),
    }
    if questions is not None:
        tree["questions.md"] = questions
    tree.update(files or {})
    for rel, text in tree.items():
        if text is None:
            continue
        (mind / rel).parent.mkdir(parents=True, exist_ok=True)
        (mind / rel).write_text(text)
    git(tmp_path, "init", "-q", "-b", "main", str(mind))
    git(mind, "config", "user.name", "Test")
    git(mind, "config", "user.email", "test@example.invalid")
    git(mind, "add", "-A")
    git(mind, "commit", "-q", "-m", "seed")
    git(mind, "update-ref", "refs/remotes/origin/main", "HEAD")
    return mind


def _make_slot(slot):
    """A watcher slot as a tick leaves it: its directory and counters.json."""
    slot.mkdir(parents=True, exist_ok=True)
    orch._write_counters(slot, orch.read_counters(slot))
    return slot


def _behind(mind, change):
    """Commit `change` (a {path: text or None}) as origin/main, then put the
    working tree back one commit: the canonical checkout nobody pulled."""
    for rel, text in change.items():
        if text is None:
            git(mind, "rm", "-q", rel)
        else:
            (mind / rel).parent.mkdir(parents=True, exist_ok=True)
            (mind / rel).write_text(text)
    git(mind, "add", "-A")
    git(mind, "commit", "-q", "-m", "on origin")
    git(mind, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(mind, "reset", "-q", "--hard", "HEAD~1")


def _run(mind, tmp_path, **kw):
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    return __import__("_ready").run(mind, root=root, now=NOW, **kw)


def _ops(slot):
    return [json.loads(f.read_text()) for f in mw.pending_ops(slot)]


def _gates(res):
    return sorted((Path(r["task"]).name, r["gate"]) for r in res["rulings"])


# --- the Witness --------------------------------------------------------------------

@needs_git
def test_witness_two_rulings_queued_and_the_digest_ends_with_them(tmp_path, capsys):
    mind = _mind(tmp_path)
    _m, brief, home = d._shift(tmp_path, names=("t1",))
    slot = orch.slot_dir(brief, home)
    _make_slot(slot)
    root = tmp_path / "root"
    root.mkdir()
    rc = _batch.main(["ready", "--mind", str(mind), "--queue", str(slot),
                      "--root", str(root)])
    assert rc == 0, capsys.readouterr()
    ops = _ops(slot)
    assert [o["op"] for o in ops] == ["question-add", "question-add"]
    assert sorted((o["entry"]["task"], o["entry"]["gate"]) for o in ops) == [
        (EPIC, "no-next-phase"), (TASK, "claimed")]
    for o in ops:
        e = o["entry"]
        assert e["kind"] == "ruling" and "issue" not in e
        assert e["shift"] == slot.name and e["worker"] == "readiness pass"
        assert 2 <= len(e["options"]) <= 3
        assert mw.validate_op(o, type("lm", (), {"is_ledger_path": staticmethod(
            lambda p: p == "questions.md")})) == []
    claimed = next(o["entry"] for o in ops if o["entry"]["gate"] == "claimed")
    assert "other-task" in claimed["ask"]
    assert "wait for other-task to ship" in claimed["options"]
    capsys.readouterr()
    assert _batch.main(["digest", "--record", str(brief), "--home", str(home)]) == 0
    out = capsys.readouterr().out
    assert out.rstrip("\n").splitlines()[-1] == LAST


# --- resolution ---------------------------------------------------------------------

@needs_git
def test_every_open_member_at_the_lowest_phase_is_a_unit(tmp_path):
    files = {
        f"{FOLDER}/p1_done.md": _prompt("P1", "Epic: example-epic\nPhase: 1\n",
                                        Status="shipped"),
        f"{FOLDER}/p2a.md": _prompt("P2a", "Epic: example-epic\nPhase: 2a\n"),
        f"{FOLDER}/p2b.md": _prompt("P2b", "Epic: example-epic\nPhase: 2b\n",
                                    Unattended="needs-slicing"),
        f"{FOLDER}/p3.md": _prompt("P3", "Epic: example-epic\nPhase: 3\n",
                                   Unattended="needs-slicing"),
    }
    res = _run(_mind(tmp_path, files, active="# Active tasks\n"), tmp_path)
    epic = res["entries"][0]
    assert sorted(Path(u["path"]).name for u in epic["units"]) == ["p2a.md", "p2b.md"]
    assert _gates(res) == [("p2b.md", "unattended")]


@needs_git
def test_a_member_in_active_is_in_flight_not_gated(tmp_path):
    files = {"active/p1.md": _prompt("P1", "Epic: example-epic\nPhase: 1\n",
                                     Unattended="needs-slicing"),
             f"{FOLDER}/p2.md": _prompt("P2", "Epic: example-epic\nPhase: 2\n",
                                        Unattended="needs-slicing")}
    res = _run(_mind(tmp_path, files, active="# Active tasks\n"), tmp_path)
    [unit] = res["entries"][0]["units"]
    assert unit["path"] == "active/p1.md" and unit["state"] == "in flight"
    assert unit["gates"] == [] and res["rulings"] == []


@needs_git
def test_looks_shipped_stops_the_other_gates(tmp_path):
    files = {TASK: _prompt("Example task", "Blocked-by: something\n",
                           Unattended="needs-slicing"),
             "looks_shipped.json": json.dumps({"flags": [{"path": TASK}]})}
    res = _run(_mind(tmp_path, files), tmp_path)
    assert _gates(res) == [("example_epic.md", "no-next-phase"),
                           ("example_task.md", "looks-shipped")]


@needs_git
def test_one_ruling_per_gate_on_a_multi_gate_unit(tmp_path):
    files = {TASK: _prompt("Example task", "Blocked-by: something\n",
                           Unattended="needs-slicing",
                           Autonomy="human-required").replace("Lane: any\n", "")}
    res = _run(_mind(tmp_path, files), tmp_path)
    assert [g for t, g in _gates(res) if t == "example_task.md"] == sorted(
        ["claimed", "unattended", "human-required", "blocked-by", "no-lane"])
    # In the plan's order.
    assert [r["gate"] for r in res["rulings"] if r["task"] == TASK] == [
        "claimed", "unattended", "human-required", "blocked-by", "no-lane"]


@needs_git
def test_a_judge_unit_gets_a_note_not_a_ruling(tmp_path):
    files = {TASK: _prompt("Example task", Consequence="judge")}
    res = _run(_mind(tmp_path, files, active="# Active tasks\n"), tmp_path)
    [unit] = res["entries"][1]["units"]
    assert unit["gates"] == [] and any("judge" in n for n in unit["notes"])
    assert _gates(res) == [("example_epic.md", "no-next-phase")]


# --- dedupe against the inbox on Mind origin/main -----------------------------------

def _inbox_with(state, extra=""):
    entry = (f"### Q1. example_task — earlier\n- task: {TASK}\n- kind: ruling\n"
             "- gate: claimed\n- ask: earlier\n- shift: 2026-11-17-pm\n"
             f"- asked: 2026-11-17T18:00Z\n- worker: readiness pass\n{extra}")
    out = ["# Questions", ""]
    for s in _questions.SECTIONS:
        out += [f"## {s}", ""] + ([entry] if s == state else [])
    return "\n".join(out) + "\n"


@needs_git
def test_an_open_ruling_on_origin_is_not_filed_again(tmp_path):
    res = _run(_mind(tmp_path, questions=_inbox_with("Open")), tmp_path)
    assert _gates(res) == [("example_epic.md", "no-next-phase")]
    assert [(Path(r["task"]).name, r["gate"], q) for r, q in res["skipped"]] == [
        ("example_task.md", "claimed", "Q1")]
    assert [o["id"] for o in res["open"]] == ["Q1"]


@needs_git
def test_a_ruling_is_filed_again_once_the_earlier_one_is_answered(tmp_path):
    res = _run(_mind(tmp_path, questions=_inbox_with(
        "Answered", "- answered: 2026-11-18 by h (chat)\n- answer: wait\n")), tmp_path)
    assert _gates(res) == [("example_epic.md", "no-next-phase"),
                           ("example_task.md", "claimed")]
    assert res["skipped"] == [] and res["open"] == []


# --- the Mind-version guard ---------------------------------------------------------

@needs_git
def test_no_ruling_kind_on_mind_main_files_nothing(tmp_path):
    mind = _mind(tmp_path, ruling=False)
    res = _run(mind, tmp_path)
    assert res["not_filed"] == ("Mind has no `ruling` inbox kind yet (PyAutoBrain#671)")
    assert len(res["found"]) == 2 and res["rulings"] == []
    slot = _make_slot(tmp_path / "slot")
    __import__("_ready").queue(res, slot)
    assert _ops(slot) == []
    c = orch.read_counters(slot)
    lines = __import__("_ready").digest_lines(c)
    assert lines[-2].startswith("Rulings not filed: Mind has no `ruling` inbox kind yet")
    assert lines[-1] == "The next shift needs 0 rulings from you."


# --- the inbox readers ignore rulings -----------------------------------------------

def _origin(state="open", kind="ruling", shift="2026-11-14-pm2"):
    return {"t1": [{"id": "Q1", "shift": shift, "issue": "", "state": state,
                    "answer": "", "comment": "", "kind": kind, "gate": "claimed",
                    "answered": "2026-11-15", "task": "draft/x/t1.md"}]}


def test_hold_for_and_answered_since_ignore_rulings():
    assert _questions.hold_for("t1", "2026-11-14-pm2", _origin()) == ("held", None)
    assert _questions.hold_for("t1", "2026-11-14-pm2", _origin(kind="question"))[0] == \
        "waiting"
    # An open ruling never blocks a release from an answered question.
    both = {"t1": _origin(state="answered", kind="question")["t1"] + _origin()["t1"]}
    both["t1"][1] = dict(both["t1"][1], id="Q2")
    assert _questions.hold_for("t1", "2026-11-14-pm2", both)[0] == "answered"
    assert _questions.answered_since("t1", both, "2026-11-14")["ids"] == ["Q1"]
    assert _questions.answered_since("t1", _origin(state="answered"), "2026-11-14") is None


def test_inbox_line_leaves_rulings_out():
    c = {"inbox": [{"task": "t1", "issue": "u", "kind": "question", "asked": "x"}]}
    origin = {"t1": [{"id": "Q1", "shift": "s", "state": "open", "kind": "question"},
                     {"id": "Q2", "shift": "s", "state": "open", "kind": "ruling"}]}
    assert _questions.inbox_line(c, "s", origin=origin) == (
        "Inbox: 1 question added to your inbox this shift (Q1), 1 open in all.")
    # A ruling is counted apart from the questions.
    c2 = {}
    assert _questions.note_added(c2, {"task": "draft/x/t1.md", "kind": "ruling",
                                      "gate": "claimed", "asked": "x"})
    assert not _questions.note_added(c2, {"task": "draft/x/t1.md", "kind": "ruling",
                                          "gate": "claimed", "asked": "y"})
    assert "inbox" not in c2 and c2["rulings"]["new"] == [
        {"task": "t1", "path": "draft/x/t1.md", "gate": "claimed"}]


# --- --apply ------------------------------------------------------------------------

@needs_git
def test_apply_refuses_on_branch_main(tmp_path, capsys):
    mind = _mind(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    rc = _batch.main(["ready", "--mind", str(mind), "--apply", "--root", str(root)])
    assert rc == _batch.RC_USAGE
    assert "main" in capsys.readouterr().err
    assert not (mind / "questions.md").exists()


@needs_git
def test_queue_and_apply_are_exclusive(tmp_path, capsys):
    mind = _mind(tmp_path)
    assert _batch.main(["ready", "--mind", str(mind), "--apply", "--queue",
                        str(tmp_path / "s")]) == _batch.RC_USAGE


@needs_git
def test_the_dry_run_writes_nothing(tmp_path, capsys):
    mind = _mind(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    before = git(mind, "status", "--porcelain").stdout
    assert _batch.main(["ready", "--mind", str(mind), "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "no-next-phase" in out and "claimed" in out and "would file 2" in out
    assert git(mind, "status", "--porcelain").stdout == before


MIND_SRC = BRAIN.parent / "PyAutoMind"
if not (MIND_SRC / "scripts" / "questions_edit.py").is_file():
    MIND_SRC = Path(os.environ.get("PYAUTO_MIND", "/nonexistent"))


def _mind_has_ruling() -> bool:
    try:
        text = (MIND_SRC / "scripts" / "lifecycle.py").read_text(encoding="utf-8")
    except OSError:
        return False
    m = re.search(r"^QUESTION_KINDS\s*=\s*\(([^)]*)\)", text, re.M)
    return bool(m and "ruling" in m.group(1))


@needs_git
@pytest.mark.skipif(not _mind_has_ruling(),
                    reason="the PyAutoMind checkout found has no `ruling` in "
                           "lifecycle.QUESTION_KINDS (Mind main lacks it until the Mind "
                           "half of PyAutoBrain#671 merges)")
def test_apply_writes_rulings_with_minds_real_questions_edit(tmp_path, capsys):
    mind = _mind(tmp_path)
    for name in ("lifecycle.py", "questions_edit.py"):
        shutil.copy(MIND_SRC / "scripts" / name, mind / "scripts" / name)
    git(mind, "add", "-A")
    git(mind, "commit", "-q", "-m", "real scripts")
    git(mind, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(mind, "checkout", "-q", "-b", "session")
    root = tmp_path / "root"
    root.mkdir()
    assert _batch.main(["ready", "--mind", str(mind), "--apply", "--root", str(root)]) == 0
    entries = _questions.parse((mind / "questions.md").read_text())
    assert sorted((e["fields"]["task"], e["fields"]["gate"], e["state"]) for e in entries) == [
        (EPIC, "no-next-phase", "open"), (TASK, "claimed", "open")]
    assert all(e["fields"]["kind"] == "ruling" for e in entries)
    # Nothing committed: the session commits it.
    assert "questions.md" in git(mind, "status", "--porcelain").stdout
    # A second --apply adds nothing (Mind's own duplicate check).
    capsys.readouterr()
    assert _batch.main(["ready", "--mind", str(mind), "--apply", "--root", str(root)]) == 0
    assert len(_questions.parse((mind / "questions.md").read_text())) == 2


# --- finish_shift -------------------------------------------------------------------

@needs_git
def test_finish_shift_queues_the_rulings_and_the_digest_ends_with_them(tmp_path,
                                                                       monkeypatch):
    mind = _mind(tmp_path)
    _m, brief, home = d._shift(tmp_path, names=("t1",))
    slot = orch.slot_dir(brief, home)
    slot.mkdir(parents=True)
    monkeypatch.setenv("PYAUTO_ROOT", str(tmp_path / "root"))
    (tmp_path / "root").mkdir()
    monkeypatch.setattr(mw, "commit_ledger", lambda *a, **k: {"committed": None})
    orch.finish_shift(brief, mind, slot, NOW, poster=lambda *a: None,
                      health=lambda u: "HEALTHY")
    digest = (slot / orch.DIGEST_FILE).read_text()
    assert digest.rstrip("\n").splitlines()[-1] == LAST
    gates = sorted(o["entry"]["gate"] for o in _ops(slot) if o["op"] == "question-add")
    assert gates == ["claimed", "no-next-phase"]
    c = orch.read_counters(slot)
    assert sorted(r["gate"] for r in c["rulings"]["new"]) == ["claimed", "no-next-phase"]


@needs_git
def test_finish_shift_survives_a_failing_pass(tmp_path, monkeypatch):
    import _ready
    mind = _mind(tmp_path)
    _m, brief, home = d._shift(tmp_path, names=("t1",))
    slot = orch.slot_dir(brief, home)
    slot.mkdir(parents=True)

    def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(_ready, "run", boom)
    monkeypatch.setattr(mw, "commit_ledger", lambda *a, **k: {"committed": None})
    orch.finish_shift(brief, mind, slot, NOW, poster=lambda *a: None,
                      health=lambda u: "HEALTHY")
    lines = (slot / orch.DIGEST_FILE).read_text().rstrip("\n").splitlines()
    assert lines[-2] == "Readiness pass failed: RuntimeError: kaboom"
    assert lines[-1] == "The next shift needs 0 rulings from you."
    assert not [o for o in _ops(slot) if o["op"] == "question-add"]


def test_question_add_validation_for_rulings():
    lm = type("lm", (), {"is_ledger_path": staticmethod(lambda p: p == "questions.md")})
    good = _questions.add_op(__import__("_ready").ruling(
        TASK, "claimed", "ask?", ["a", "b"], "2026-11-18-pm", "2026-11-18T18:00Z"))
    assert "issue" not in good["entry"] and mw.validate_op(good, lm) == []
    no_gate = dict(good, entry={k: v for k, v in good["entry"].items() if k != "gate"})
    assert any("gate must be one non-empty line" in e for e in mw.validate_op(no_gate, lm))
    question = dict(good, entry=dict(good["entry"], kind="question",
                                     issue="https://github.com/example-org/x/issues/1"))
    assert "question-add: gate is for kind ruling only" in mw.validate_op(question, lm)
    no_issue = dict(question, entry={k: v for k, v in question["entry"].items()
                                     if k != "gate" and k != "issue"})
    assert any("issue must be one non-empty line" in e for e in mw.validate_op(no_issue, lm))


# --- fix round 1 (the independent review of #671) ----------------------------------

@needs_git
def test_a_unit_origin_has_moved_is_in_flight_with_no_ruling(tmp_path):
    mind = _mind(tmp_path)
    _behind(mind, {TASK: None, "active/example_task.md": _prompt("Example task"),
                   "active.md": ACTIVE + "\n## example-task\n- prompt: active/example_task.md\n"
                                         "- session: shift worker 2026-11-18-am (abc)\n"})
    assert (mind / TASK).is_file()                       # the stale working tree
    res = _run(mind, tmp_path)
    [unit] = res["entries"][1]["units"]
    assert unit["state"] == "in flight" and unit["gates"] == []
    assert "claimed by `example-task`" in unit["notes"][0]
    assert _gates(res) == [("example_epic.md", "no-next-phase")]


@needs_git
def test_a_member_only_origin_has_files_no_no_next_phase_ruling(tmp_path):
    mind = _mind(tmp_path)
    _behind(mind, {f"{FOLDER}/p2.md": _prompt("P2", "Epic: example-epic\nPhase: 2\n")})
    res = _run(mind, tmp_path)
    assert res["entries"][0]["units"] == []
    assert any("behind origin/main" in n for n in res["entries"][0]["notes"])
    assert _gates(res) == [("example_task.md", "claimed")]


@needs_git
def test_a_lowest_phase_origin_disagrees_on_files_no_ruling(tmp_path):
    p1 = f"{FOLDER}/p1.md"
    files = {p1: _prompt("P1", "Epic: example-epic\nPhase: 1\n", Unattended="needs-slicing"),
             f"{FOLDER}/p2.md": _prompt("P2", "Epic: example-epic\nPhase: 2\n")}
    mind = _mind(tmp_path, files, active="# Active tasks\n")
    _behind(mind, {p1: _prompt("P1", "Epic: example-epic\nPhase: 1\n", Status="shipped")})
    res = _run(mind, tmp_path)
    assert res["entries"][0]["units"] == [] and res["rulings"] == []
    assert any("behind origin/main" in n for n in res["entries"][0]["notes"])


@needs_git
def test_a_queued_side_task_resolves_to_itself(tmp_path):
    side = f"{FOLDER}/side.md"
    queue = QUEUE.format(epic=side, task=TASK)
    files = {side: _prompt("Side", "Epic: example-epic\n", Unattended="needs-slicing")}
    res = _run(_mind(tmp_path, files, queue=queue, active="# Active tasks\n"), tmp_path)
    assert [u["path"] for u in res["entries"][0]["units"]] == [side]
    assert _gates(res) == [("side.md", "unattended")]


@needs_git
def test_a_queued_member_that_is_not_next_gets_a_note(tmp_path):
    p3 = f"{FOLDER}/p3.md"
    files = {f"{FOLDER}/p2.md": _prompt("P2", "Epic: example-epic\nPhase: 2\n"),
             p3: _prompt("P3", "Epic: example-epic\nPhase: 3\n", Unattended="needs-slicing")}
    queue = QUEUE.format(epic=p3, task=TASK)
    res = _run(_mind(tmp_path, files, queue=queue, active="# Active tasks\n"), tmp_path)
    assert res["entries"][0]["units"] == []
    assert "epic example-epic phase 3 is not next — phase 2 is" in res["entries"][0]["notes"]
    assert res["rulings"] == []


@needs_git
def test_a_unit_reached_twice_is_one_ruling(tmp_path, capsys):
    p2 = f"{FOLDER}/p2.md"
    files = {p2: _prompt("P2", "Epic: example-epic\nPhase: 2\n", Unattended="needs-slicing")}
    queue = QUEUE.format(epic=EPIC, task=p2)
    res = _run(_mind(tmp_path, files, queue=queue, active="# Active tasks\n"), tmp_path)
    assert [(Path(f["task"]).name, f["gate"]) for f in res["found"]] == [("p2.md", "unattended")]
    assert len(res["would_file"]) == 1
    text = __import__("_ready").report(res)
    assert text.count("ruling unattended —") == 1 and "(listed above)" in text


@needs_git
def test_queue_refuses_what_is_not_a_live_slot(tmp_path, capsys):
    mind = _mind(tmp_path)
    root = tmp_path / "root"
    root.mkdir()

    def ready(slot):
        return _batch.main(["ready", "--mind", str(mind), "--queue", str(slot),
                            "--root", str(root)])
    missing = tmp_path / "home" / "nope"
    assert ready(missing) == _batch.RC_USAGE and not missing.exists()
    bare = tmp_path / "bare"
    bare.mkdir()
    assert ready(bare) == _batch.RC_USAGE and list(bare.iterdir()) == []
    slot = _make_slot(tmp_path / "slot")
    (slot / orch.LOCK_FILE).write_text(json.dumps({"pid": os.getpid(),
                                                    "at": NOW.timestamp() + 10**9}))
    assert ready(slot) == _batch.RC_USAGE and "tick lock" in capsys.readouterr().err
    assert (slot / orch.LOCK_FILE).exists() and _ops(slot) == []
    (slot / orch.LOCK_FILE).unlink()
    (slot / orch.DIGEST_MARKER).write_text("{}")
    assert ready(slot) == _batch.RC_USAGE and "digest" in capsys.readouterr().err
    assert _ops(slot) == []


@needs_git
def test_a_ready_module_that_will_not_import_never_breaks_the_digest(tmp_path, monkeypatch):
    mind = _mind(tmp_path)
    _m, brief, home = d._shift(tmp_path, names=("t1",))
    slot = _make_slot(orch.slot_dir(brief, home))
    monkeypatch.setitem(sys.modules, "_ready", None)       # import raises ImportError
    monkeypatch.setattr(mw, "commit_ledger", lambda *a, **k: {"committed": None})
    orch.finish_shift(brief, mind, slot, NOW, poster=lambda *a: None,
                      health=lambda u: "HEALTHY")
    lines = (slot / orch.DIGEST_FILE).read_text().rstrip("\n").splitlines()
    assert lines[-1].startswith("Readiness pass failed")
    assert "import of _ready halted" in orch.read_counters(slot)["rulings"]["error"]
