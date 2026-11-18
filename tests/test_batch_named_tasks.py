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
    other = _write(mind, "grid_offset_roundtrip", target="PyAutoCortex")
    sharer = _write(mind, "three_autos_public_framing", target="PyAutoCortex")
    (mind / "active.md").write_text(
        "# Active\n\n## ep-projected-model-shared-prior\n- status: library-dev\n"
        "- repos:\n  - PyAutoCortex: feature/ep-projected-model-shared-prior\n"
        "- conflict-override: PyAutoCortex also claimed by three-autos-public-framing; "
        "human approved a separate worktree\n")
    _git(mind, "add", "-A")
    _git(mind, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-q",
         "-m", "seed")
    _git(mind, "push", "-q", "origin", "HEAD:main")
    _git(mind, "fetch", "-q", "origin")
    records = [_batch.grade(mind / p, mind) for p in (other, sharer)]
    kept, out = orch.on_origin(records, mind, own=set())
    assert [r["path"] for r in kept] == [sharer]
    assert out == {other: "repo PyAutoCortex claimed by `ep-projected-model-shared-prior` "
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


# --- review fixes (Fable 5.2, FINDINGS 1, 2, 3, 7, 8) -----------------------------------

def _organ(tmp_path, body, *, target="PyAutoBrain", repos=None):
    """organ_findings for one prompt with `body`, declaring `repos` (default: the target)."""
    mind = tmp_path / "mind"
    (mind / "scripts").mkdir(parents=True, exist_ok=True)
    (mind / "scripts" / "lifecycle.py").write_text("")
    rel = _write(mind, "t", target=target, body=body)
    if repos is not None:
        f = mind / rel
        f.write_text(f.read_text().replace(f"Repos:\n- {target}\n",
                                           "Repos:\n" + "".join(f"- {r}\n" for r in repos)))
    return _batch._brief.organ_findings("t", mind / rel, mind)


@pytest.mark.parametrize("body", [
    "Change `example-org/PyAutoBrain/agents/conductors/batch/_orchestrator.py`.",
    "Change `./agents/conductors/batch/_orchestrator.py`.",
    "Change `/home/u/PyAutoBrain/agents/conductors/batch/_orchestrator.py`.",
    "Change `_orchestrator.py` and `agents/conductors/intake/_dashboard.py`.",
    "Change agents/conductors/batch/_orchestrator.py and `docs/x.md`.",
    "Change `PyAutoMind/scripts/lifecycle.py`.",
    "Change `lifecycle.py` in Mind.",
])
def test_review_the_shift_own_code_is_refused_however_it_is_written(tmp_path, body):
    target = "PyAutoMind" if "lifecycle.py` in" in body else "PyAutoBrain"
    errors, warnings, notes = _organ(tmp_path, body, target=target)
    assert errors and "watcher, writer or release path" in errors[0], (errors, warnings, notes)


@pytest.mark.parametrize("body", [
    "Then run `/prm` and see `/`.",
    "Touch `*/__init__.py` across `example-org/PyAutoEyes`.",
    "Edit `PyAutoHeart/scripts/x.py`.",
])
def test_review_non_paths_and_other_repos_paths_are_not_refused(tmp_path, body):
    errors, _, _ = _organ(tmp_path, body, target="PyAutoBrain",
                          repos=["PyAutoBrain", "PyAutoHands", "PyAutoHeart"])
    assert errors == []


def test_review_an_unprefixed_self_path_with_other_repos_declared_is_the_humans_call(tmp_path):
    errors, warnings, _ = _organ(tmp_path, "Run `scripts/fit.py` on the cluster.",
                                 target="PyAutoMind", repos=["PyAutoMind", "PyAutoHeart"])
    assert errors == [] and warnings and "the human decides" in warnings[0]


def test_review_a_phase_label_keeps_its_leading_number_and_counts_as_a_phase():
    assert _batch._phase_of("Phase: 5A\n") == 5 and _batch._phase_of("Phase: 6b2\n") == 6
    assert _batch._phase_of("Phase: C2\n") == float("inf") and _batch._phase_declared("Phase: C2\n")
    a, b = rec("a.md", epic="e", phase=5), rec("b.md", epic="e", phase=float("inf"))
    b["phase_declared"] = True        # `Phase: C2`: a phase, not a side task
    dec = _batch.plan([a, b], budget=100)
    assert [m["path"] for m in dec["members"]] == ["a.md"]
    assert dict(dec["rejected"])["b.md"] == "epic e phase (unnumbered) is not next"


@pytest.mark.parametrize("task", ["coordination", "conflict_override", "human"])
def test_review_the_coordination_key_and_common_words_free_nothing_by_themselves(task):
    sec = {"coordination": orch._COORDINATION_LINE_RE.search(
        "- conflict-override: human approved sharing with three-autos-public-framing").group(1)}
    assert not orch.coordinated_for(sec, task if task != "human" else "humans")
    assert orch.coordinated_for(sec, "three_autos_public_framing")


def test_review_a_named_task_already_in_active_says_why_it_will_not_start(tmp_path, capsys):
    mind, brief, _ = _shift(tmp_path)
    issued = mind / "active" / "already.md"
    issued.parent.mkdir(parents=True)
    issued.write_text(PROMPT.format(name="already", target="PyAutoHeart", headers="",
                                    witness="Witness: a unit test\n", body="Body."))
    brief.write_text(brief.read_text().replace("draft/feature/x/none.md",
                                               "draft/feature/x/already.md"))
    rc, out = _check(brief, mind, capsys)
    assert any("already" in ln and "will not start" in ln and "in active/" in ln
               for ln in out.splitlines()), out


def test_review_a_resumed_task_is_not_held_back_for_want_of_a_witness():
    r = rec("draft/feature/x/r.md", witness=None)
    r["resume"] = ["Q3"]
    brief = {"backlog": {"value": "fill-idle", "children": []},
             "lanes": {"value": "any", "children": []}}
    dec = _batch.plan([r], budget=100, brief=brief, queue=["x"])
    assert [m["path"] for m in dec["members"]] == ["draft/feature/x/r.md"], dec["rejected"]


# --- second review (Fable 5.2) ---------------------------------------------------------

@pytest.mark.parametrize("body,target", [
    ("Rework everything under `agents/conductors/batch/`.", "PyAutoBrain"),
    ("Rework `PyAutoBrain/agents/conductors/batch/` and `docs/x.md`.", "PyAutoBrain"),
    ("Edit `.github/workflows/` and `docs/x.md`.", "PyAutoMind"),
    ("Edit `scripts/` and `docs/x.md`.", "PyAutoMind"),
    ("Edit `agents/conductors/batch/_*.py` and `tests/test_x.py`.", "PyAutoBrain"),
    ("Reword `worker_template.md` and `docs/x.md`.", "PyAutoBrain"),
    ("Change _orchestrator.py and `docs/x.md`.", "PyAutoBrain"),
    ("See `/home/u/worktrees/PyAutoBrain-foo/agents/conductors/batch/_batch.py`.", "PyAutoBrain"),
    ("See `Agents/Conductors/Batch/_batch.py`.", "PyAutoBrain"),
    ("See `agents/conductors/batch/autolens.py` and `docs/x.md`.", "PyAutoBrain"),
])
def test_review2_self_code_is_refused_in_every_spelling(tmp_path, body, target):
    errors, warnings, notes = _organ(tmp_path, body, target=target)
    assert errors, (warnings, notes)


@pytest.mark.parametrize("body", [
    "Fires on `example-org/PyAutoPulse` and `example-org/PyAutoHands`.",
    "Moves the watcher, as `draft/feature/pyautobrain/other.md` and `batches/2026-11-13-am.md` say.",
    "From v1.2/v1.3.0 onwards.",
])
def test_review2_repo_names_mind_records_and_versions_show_nothing(tmp_path, body):
    errors, warnings, notes = _organ(tmp_path, body, target="PyAutoBrain")
    assert errors == [] and notes == [] and "names no path" in warnings[0], (errors, warnings)


def test_review2_branch_names_are_not_hands_paths(tmp_path):
    """Any real path in a Hands-only task is Hands code (the approved rule);
    a branch name is not a path."""
    errors, warnings, _ = _organ(tmp_path, "Push `origin/main` from `feature/x`.",
                                 target="PyAutoHands")
    assert errors == [] and "names no path" in warnings[0]


def test_review2_a_target_header_naming_several_repos_is_read(tmp_path):
    mind = tmp_path / "mind"
    rel = _write(mind, "t", target="PyAutoHeart",
                 body="Change `agents/conductors/batch/_batch.py`.")
    f = mind / rel
    f.write_text(f.read_text().replace("Target: PyAutoHeart", "Target: PyAutoBrain, PyAutoMind"))
    errors, _, _ = _batch._brief.organ_findings("t", f, mind)
    assert errors


# --- third review (Fable 5.2) ----------------------------------------------------------

def test_review3_a_repos_own_ci_workflow_is_not_the_minds(tmp_path):
    errors, _, notes = _organ(tmp_path, "Edit `.github/workflows/tests.yml`.", target="PyAutoBrain")
    assert errors == [] and notes, notes
    errors, warnings, _ = _organ(tmp_path, "Edit `.github/workflows/heart-health.yml`.",
                                 target="PyAutoBrain", repos=["PyAutoBrain", "PyAutoHeart"])
    assert errors == []


@pytest.mark.parametrize("body", ["Add a workflow under `.github/workflows` and update `docs/x.md`.",
                                  "Add `scripts` and update `docs/x.md`."])
def test_review3_a_self_directory_without_its_slash_is_still_read(tmp_path, body):
    errors, _, _ = _organ(tmp_path, body, target="PyAutoMind")
    assert errors


@pytest.mark.parametrize("body", ["See `PyAutoBrain/`.", "See `example-org/PyAutoBrain/`.",
                                  "As `../../../active/foo.md` says."])
def test_review3_repo_dirs_and_relative_records_show_nothing(tmp_path, body):
    errors, warnings, notes = _organ(tmp_path, body, target="PyAutoBrain")
    assert errors == [] and notes == [] and "names no path" in warnings[0], (warnings, notes)


def test_review4_the_batch_conductor_is_refused_whatever_the_task_declares(tmp_path):
    errors, _, _ = _organ(tmp_path, "Edit `agents/conductors/batch/_orchestrator.py`.",
                          target="PyAutoMind")
    assert errors
    errors, _, _ = _organ(tmp_path, "Edit `PyAutoMind/scripts` and `docs/x.md`.",
                          target="PyAutoMind")
    assert errors


# --- PyAutoBrain#679: a shift's library slot frees once its task's PR has merged ------

PR1 = "https://github.com/example-org/PyAutoGalaxy/pull/7"
GALAXY = ("ag_bug_one", "ag_bug_two")


def _galaxy_shift(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A brief naming two glance tasks on one library, first tick already run."""
    mind, brief, home = _shift(tmp_path)
    rels = []
    for name in GALAXY:
        rel = _write(mind, name, target="PyAutoGalaxy")
        f = mind / rel
        f.write_text(f.read_text().replace("Consequence: notify", "Consequence: glance"))
        rels.append(rel)
    brief.write_text(brief.read_text().replace(
        "    - draft/feature/x/none.md", "\n".join(f"    - {r}" for r in rels)))
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert [s["task"] for s in r["spawned"]] == ["ag_bug_one"], r
    return mind, brief, home


def _end(brief: Path, home: Path, task: str, outcome: dict | None, *, how="done",
         **extra) -> None:
    """The first task's worker has ended: its lease gone, its outcome recorded."""
    slot = orch.slot_dir(brief, home)
    (slot / "leases" / f"{task}.json").unlink()
    c = orch.read_counters(slot)
    c[how].append(task)
    if outcome is not None:
        c["outcomes"][task] = outcome
    for k, v in extra.items():
        c[k] = v
    orch._write_counters(slot, c)


def test_679_1_the_second_task_on_a_library_waits_while_the_first_is_live(tmp_path):
    mind, brief, home = _galaxy_shift(tmp_path)
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert r["spawned"] == [], r
    named = orch.read_counters(orch.slot_dir(brief, home))["backlog_gates"]["named"]
    assert named == {"draft/feature/x/ag_bug_two.md":
                     "autogalaxy held by ag_bug_one — will start after ag_bug_one's PR "
                     "merges"}, named


def test_679_2_the_second_task_starts_once_every_pr_of_the_first_has_merged(tmp_path):
    mind, brief, home = _galaxy_shift(tmp_path)
    _end(brief, home, "ag_bug_one", {"prs": [PR1], "merged": [PR1], "issues": []})
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert [s["task"] for s in r["spawned"]] == ["ag_bug_two"], r


@pytest.mark.parametrize("outcome, extra", [
    ({"prs": [PR1], "merged": [], "issues": []}, {}),                     # PR open
    ({"prs": [PR1], "merged": [], "issues": []},                          # refused
     {"closeouts": {PR1: {"task": "ag_bug_one", "state": "refused", "why": "red"}}}),
    ({"prs": [], "merged": [], "issues": [ISSUE], "questions": [ISSUE]}, {}),  # question
    ({"prs": [PR1, PR1 + "0"], "merged": [PR1], "issues": []}, {}),       # one of two
])
def test_679_3_an_open_or_refused_pr_or_a_question_still_holds(tmp_path, outcome, extra):
    mind, brief, home = _galaxy_shift(tmp_path)
    _end(brief, home, "ag_bug_one", outcome, **extra)
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert r["spawned"] == [], r


def test_679_3_a_park_on_a_person_still_holds(tmp_path):
    mind, brief, home = _galaxy_shift(tmp_path)
    _end(brief, home, "ag_bug_one", None, how="parked")
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert r["spawned"] == [], r


def test_679_4_an_abandoned_task_with_no_pr_frees_its_library(tmp_path):
    mind, brief, home = _galaxy_shift(tmp_path)
    _end(brief, home, "ag_bug_one", None, how="abandoned")
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert [s["task"] for s in r["spawned"]] == ["ag_bug_two"], r


def test_679_5_a_released_picks_leftover_claim_does_not_hold_its_repo(tmp_path):
    """The close-out queues `drop-section active.md`, but a set-aside op or a
    failed push leaves the claim on origin: only this shift's own worker's
    claim on a released pick is passed over; any other claim still holds."""
    if shutil.which("git") is None:
        pytest.skip("needs git")
    bare, mind = tmp_path / "mind.git", tmp_path / "mind"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    _git(tmp_path, "clone", "-q", str(bare), str(mind))
    first = _write(mind, "ag_bug_one", target="PyAutoGalaxy")
    second = _write(mind, "ag_bug_two", target="PyAutoGalaxy")

    def claim(session):
        (mind / "active.md").write_text(
            f"# Active\n\n## ag-bug-one\n- prompt: {first}\n- session: {session}\n"
            "- repos:\n  - PyAutoGalaxy: feature/ag-bug-one\n")
        _git(mind, "add", "-A")
        _git(mind, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit",
             "-q", "-m", "claim")
        _git(mind, "push", "-q", "origin", "HEAD:main")
        _git(mind, "fetch", "-q", "origin")

    claim("shift worker 2026-11-18-pm (abc123)")
    records = [_batch.grade(mind / second, mind)]
    held = {second: "repo PyAutoGalaxy claimed by `ag-bug-one` in active.md on "
                    "Mind origin/main"}
    assert orch.on_origin(records, mind, own={"ag_bug_one"}) == ([], held)
    kept, out = orch.on_origin(records, mind, own={"ag_bug_one"}, released={"ag_bug_one"},
                               slot_name="2026-11-18-pm")
    assert (kept, out) == (records, {})
    # Another shift's worker, or a human who took the claim over: it holds.
    assert orch.on_origin(records, mind, own={"ag_bug_one"}, released={"ag_bug_one"},
                          slot_name="2026-11-18-am") == ([], held)
    claim("desktop session, human")
    assert orch.on_origin(records, mind, own={"ag_bug_one"}, released={"ag_bug_one"},
                          slot_name="2026-11-18-pm") == ([], held)
