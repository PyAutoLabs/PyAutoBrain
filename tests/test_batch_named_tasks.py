"""M3.6b (PyAutoBrain#667): named tasks and the planner's skips.

Human rulings 2026-11-17 (PyAutoMind `active/shift_named_tasks_and_planner_skips.md`):

- R5 (option a): the per-epic limit is for `Phase:` tasks only; a side task
  orders itself by `Blocked-by:`; every named task that will not start is
  listed with its reason at `brief --check` and in the digest.
- R2: the planner never dispatches a task whose repo another active task
  claims; the digest counts those skipped. A `coordination:` /
  `conflict-override:` line frees a repo only for the task it names.

One test per Witness clause (1-7); each fails on main 8f36ae6. Fictional
fixtures only.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_dispatch as d  # noqa: E402 — the real-spawner fixtures
from test_orchestrator_dispatch import _digest, orch  # noqa: E402
import _batch  # noqa: E402

NOW = d.NOW
ISSUE = "https://github.com/example-org/PyAutoMind/issues/42"

PROMPT = """\
# {name}

Type: feature
Target: {target}
Repos:
- {target}
Difficulty: small
Autonomy: safe
Priority: normal
Status: draft
{headers}Consequence: notify
{witness}Review-minutes: 3
Unattended: ready
Lane: any

{body}
"""

SHIFT = """\
# Batch 2026-11-04 am
- dispatched: 2026-11-04T08:30Z
- review-at: 2026-11-04T11:30Z
- issue: {issue}
- brief:
  - goals:
    - 1. a shift
  - tasks:
{tasks}
  - backlog: {backlog}
  - review-minutes: 45
  - lanes: any local-dev
  - merge-cap: 0
  - token-budget: 100000
  - max-workers: 4
  - max-sessions: 8
"""


def _write(mind: Path, name: str, *, target="PyAutoHeart", epic="", phase="",
           blocked_by="", witness=True, body="Body.") -> str:
    headers = "".join(f"{k}: {v}\n" for k, v in (("Epic", epic), ("Phase", phase),
                                                   ("Blocked-by", blocked_by)) if v)
    rel = f"draft/feature/x/{name}.md"
    f = mind / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(PROMPT.format(name=name, target=target, headers=headers, body=body,
                               witness="Witness: a unit test\n" if witness else ""))
    return rel


def _shift(tmp_path: Path, named=(), *, backlog="none") -> tuple[Path, Path, Path]:
    mind = tmp_path / "mind"
    mind.mkdir(parents=True, exist_ok=True)
    (mind / "queue.md").write_text("# Queue\n\n## 1. q\n- kind: prompt\n"
                                   "- ref: draft/feature/x/elsewhere.md\n")
    tasks = "\n".join(f"    - {t}" for t in named) or "    - draft/feature/x/none.md"
    brief = tmp_path / "shift.md"
    brief.write_text(SHIFT.format(issue=ISSUE, tasks=tasks, backlog=backlog))
    return mind, brief, tmp_path / "home"


def _check(brief: Path, mind: Path, capsys) -> tuple[int, str]:
    capsys.readouterr()
    rc = _batch.main(["brief", "--check", str(brief), "--mind", str(mind), "--no-premise"])
    return rc, capsys.readouterr().out


def rec(path, *, epic="", phase=float("inf"), blocked_by=(), witness="a test"):
    return {"path": path, "repos": [], "work_type": "feature", "difficulty": "small",
            "score": 1, "consequence": "notify", "witness": witness,
            "review_minutes": 3, "unattended": "ready", "why": "", "ready_why": [],
            "epic": epic, "lane": "any", "priority": "normal",
            "blocked": bool(blocked_by), "blocked_by": list(blocked_by),
            "autonomy": "safe", "autonomy_cap": "safe", "declared_autonomy": "safe",
            "done": False, "phase": phase}


# --- 1. a side task shares the shift with its epic's phase ---------------------------

def test_1_a_named_phase_task_and_a_same_epic_side_task_both_dispatch(tmp_path):
    mind, brief, home = _shift(tmp_path)
    p5 = _write(mind, "p5a", epic="lifecycle", phase="5")
    side = _write(mind, "wall_bug", epic="lifecycle")
    brief.write_text(brief.read_text().replace("    - draft/feature/x/none.md",
                                               f"    - {p5}\n    - {side}"))
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert sorted(s["task"] for s in r["spawned"]) == ["p5a", "wall_bug"], r


# --- 2. two Phase tasks of one epic: the second says why it did not start -------------

def test_2_the_second_phase_task_of_an_epic_is_not_started_with_its_reason(tmp_path, capsys):
    mind, brief, home = _shift(tmp_path)
    a = _write(mind, "p5a", epic="lifecycle", phase="5a")
    b = _write(mind, "p5b", epic="lifecycle", phase="5b")
    brief.write_text(brief.read_text().replace("    - draft/feature/x/none.md",
                                               f"    - {a}\n    - {b}"))
    # At launch: `brief --check` names it, one line, with the reason.
    rc, out = _check(brief, mind, capsys)
    assert rc == 0, out
    line = next(ln for ln in out.splitlines() if "p5b" in ln and "will not start" in ln)
    assert "epic lifecycle" in line, out
    assert not any("p5a" in ln and "will not start" in ln for ln in out.splitlines())
    # In the shift: the digest's "Not started" line gives the same reason.
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert [s["task"] for s in r["spawned"]] == ["p5a"], r
    counters = orch.read_counters(orch.slot_dir(brief, home))
    state, _ = _digest.task_state("p5b", counters, lambda u: "?")
    assert state.startswith("not started — skipped: ") and "epic lifecycle" in state, state


# --- 3. a side task with Blocked-by: waits for the phase it names ----------------------

def test_3_a_side_task_blocked_by_the_phase_prompt_waits_for_it():
    phase = "draft/feature/x/p5a.md"
    dec = _batch.plan([rec(phase, epic="lifecycle", phase=5),
                       rec("draft/feature/x/side.md", epic="lifecycle", blocked_by=[phase])],
                      budget=100)
    assert [m["path"] for m in dec["members"]] == [phase]
    why = dict(dec["rejected"])["draft/feature/x/side.md"]
    assert "p5a.md" in why and "waits" in why, why


# --- 4. the backlog dip skips a draft with no Witness: and counts it ------------------

def test_4_a_backlog_draft_with_no_witness_is_skipped_and_counted(tmp_path):
    mind, brief, home = _shift(tmp_path, backlog="fill-idle")
    _write(mind, "witnessed")
    bare = _write(mind, "unwitnessed", witness=False)
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert [s["task"] for s in r["spawned"]] == ["witnessed"], r
    counters = orch.read_counters(orch.slot_dir(brief, home))
    assert counters["backlog_gates"]["witness_absent"] == [bare]
    lines = _digest.backlog_gate_lines(counters)
    assert any(ln.startswith("No Witness: 1 draft(s) not dipped") for ln in lines), lines
    # A named task is the human's pick: no Witness: does not hold it back.
    mind2, brief2, home2 = _shift(tmp_path / "named")
    named = _write(mind2, "unwitnessed_named", witness=False)
    brief2.write_text(brief2.read_text().replace("draft/feature/x/none.md", named))
    r = d._tick(brief2, mind2, home2, NOW, d.FakeClaude())
    assert [s["task"] for s in r["spawned"]] == ["unwitnessed_named"], r


# --- 5. R2: a repo another active task claims is never dispatched, and counted --------

def _git(cwd, *args):
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert res.returncode == 0, (args, res.stderr)


def test_5_a_coordinated_claim_frees_its_repo_only_for_the_task_it_names(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("needs git")
    bare, mind = tmp_path / "mind.git", tmp_path / "mind"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    _git(tmp_path, "clone", "-q", str(bare), str(mind))
    other = _write(mind, "grid_offset_roundtrip", target="PyAutoFit")
    sharer = _write(mind, "three_autos_public_framing", target="PyAutoFit")
    (mind / "active.md").write_text(
        "# Active\n\n## ep-projected-model-shared-prior\n- status: library-dev\n"
        "- repos:\n  - PyAutoFit: feature/ep-projected-model-shared-prior\n"
        "- conflict-override: PyAutoFit also claimed by three-autos-public-framing; "
        "human approved a separate worktree\n")
    _git(mind, "add", "-A")
    _git(mind, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-q",
         "-m", "seed")
    _git(mind, "push", "-q", "origin", "HEAD:main")
    _git(mind, "fetch", "-q", "origin")
    records = [_batch.grade(mind / p, mind) for p in (other, sharer)]
    kept, out = orch.on_origin(records, mind, own=set())
    assert [r["path"] for r in kept] == [sharer]
    assert out == {other: "repo PyAutoFit claimed by `ep-projected-model-shared-prior` "
                          "in active.md on Mind origin/main"}
    lines = _digest.backlog_gate_lines({"backlog_gates": {"origin": out}})
    assert any(ln.startswith("Repo claimed on Mind origin/main: 1 draft(s) skipped")
               for ln in lines), lines


# --- 6. `brief --new` defaults to the backlog-reach scope ------------------------------

def test_6_brief_new_writes_the_scoped_reach_default_not_fill_idle(tmp_path, capsys):
    mind = tmp_path / "mind"
    mind.mkdir()
    (mind / "goals.md").write_text("# Goals\n\n## 1. Land the flywheel rework\n")
    text = _batch.new_brief(mind, "2026-11-17-pm", "2099-01-01T12:00Z", issue=ISSUE)
    assert "fill-idle" not in text
    assert "  - backlog: scoped" in text and "    - tiers: notify, glance" in text, text
    assert "2026-11-16" in text          # the ruling it applies is named on the line
    brief = tmp_path / "brief.md"
    brief.write_text(text)
    rc, out = _check(brief, mind, capsys)
    assert rc == 0, out


# --- 7. the organ rule at `--check`: a renderer passes, saying why ---------------------

def test_7_a_named_renderer_task_passes_the_organ_rule_with_a_line(tmp_path, capsys):
    mind, brief, _ = _shift(tmp_path)
    render = _write(mind, "dashboard_census", target="PyAutoBrain",
                    body="Fix the census in `agents/conductors/intake/_dashboard.py`.")
    brief.write_text(brief.read_text().replace("draft/feature/x/none.md", render))
    rc, out = _check(brief, mind, capsys)
    assert rc == 0, out
    line = next(ln for ln in out.splitlines() if "dashboard_census" in ln and "organ" in ln)
    assert "not the watcher, writer or release path" in line, out
    # One that names the shift's own code is refused.
    watcher = _write(mind, "tick_fix", target="PyAutoBrain",
                     body="Change `agents/conductors/batch/_orchestrator.py`.")
    brief.write_text(brief.read_text().replace(f"    - {render}",
                                               f"    - {render}\n    - {watcher}"))
    rc, out = _check(brief, mind, capsys)
    assert rc != 0
    assert any("tick_fix" in ln and "✗" in ln and "watcher, writer or release path" in ln
               for ln in out.splitlines()), out
    # One that names no path at all is the human's call: a warning, not a refusal.
    vague = _write(mind, "vague", target="PyAutoMind", body="Tidy it up.")
    brief.write_text(brief.read_text().replace(f"    - {watcher}\n", f"    - {vague}\n"))
    rc, out = _check(brief, mind, capsys)
    assert rc == 0, out
    assert any("vague" in ln and "!" in ln and "names no path" in ln
               for ln in out.splitlines()), out
