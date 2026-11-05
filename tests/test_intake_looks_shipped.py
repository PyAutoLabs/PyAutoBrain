"""The close-out guard: `intake looks-shipped` and its consumers.

Witness (PyAutoMind draft close_out_guard_catch_shipped_work_whose.md): a
fixture Mind plus fixture commit history where

  (i)   a draft's Witness test now exists in its target repo,
  (ii)  a commit message (and a merged-PR body) names a draft's path or slug,
  (iii) a completion record's `## Original prompt` duplicates an open draft,

are each flagged `looks-shipped` with the evidence cited; a control set that
shares only vocabulary is not flagged; nothing under draft/ is written; and the
batch planner drops flagged drafts from its proposals.

Hermetic: every repo is a git repo built in tmp_path with pinned dates.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, BRAIN / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_shipped = _load("_shipped_under_test", "agents/conductors/intake/_shipped.py")
_intake = _load("_intake_ls_under_test", "agents/conductors/intake/_intake.py")
_batch = _load("_batch_ls_under_test", "agents/conductors/batch/_batch.py")
_state = _load("_state_ls_under_test", "board/_state.py")


# --------------------------------------------------------------------------- #
# fixture organism
# --------------------------------------------------------------------------- #
def _git(repo: Path, *args, date: str = "2026-01-01T12:00:00"):
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env,
                   capture_output=True, text=True)


def _commit(repo: Path, files: dict, message: str, date: str):
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", message, date=date)


def _init(repo: Path):
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")


HEADER = """Type: {wt}
Target: pyautowidget
Repos:
- PyAutoWidget
Difficulty: small
Autonomy: safe
Priority: normal
Status: formalised
Filed: 2026-01-10
Consequence: notify
Review-minutes: 5
Unattended: ready
Witness: {witness}
"""


def _draft(title, wt, witness, body):
    return f"# {title}\n\n{HEADER.format(wt=wt, witness=witness)}\n{body}\n"


GEAR_BODY = ("The gear ratio dashboard should render one row per gearbox with "
             "its measured ratio, the declared ratio and the drift between "
             "them, sorted by drift so the worst gearbox is at the top. Each "
             "row links the gearbox's calibration log and carries a copy "
             "button for the recalibration command. The page is generated "
             "nightly and never hand edited, and a stale page states its own "
             "generation date so nobody trusts an old render by accident.")

DRAFTS = {
    # (i) witness test defined after Filed
    "draft/feature/pyautowidget/sprocket_guard.md": _draft(
        "Guard sprockets against overflow", "feature",
        "`test_sprocket_guard_refuses_overflow` passes in PyAutoWidget",
        "Sprockets overflow when the flange spins too fast."),
    # (ii) a commit names the draft path
    "draft/bug/pyautowidget/flange_rattle_under_load.md": _draft(
        "Flange rattles under load", "bug", "the rattle test passes",
        "The flange rattles under load; the sprocket shakes loose."),
    # (ii, PR leg) a merged PR body names the slug
    "draft/feature/pyautowidget/torque_limiter_for_spindles.md": _draft(
        "Torque limiter for spindles", "feature", "spindles stop at the limit",
        "Add a torque limiter so spindles stop before the gear strips."),
    # (iii) a completion record duplicates it
    "draft/feature/pyautowidget/gear_ratio_dashboard.md": _draft(
        "Gear ratio dashboard for every gearbox", "feature",
        "the dashboard renders", GEAR_BODY),
    # --- controls: vocabulary only ---------------------------------------
    # Witness names a helper that existed BEFORE the draft was filed.
    "draft/feature/pyautowidget/sprocket_flange_gear_polish.md": _draft(
        "Sprocket flange gear polish", "feature",
        "`test_existing_sprocket_helper` still passes",
        "Polish the sprocket, the flange and the gear ratio dashboard copy."),
    # Named only by a follow-up line, a ledger-only Mind commit and a commit
    # that predates its filing.
    "draft/bug/pyautowidget/spindle_wobble_on_cold_start.md": _draft(
        "Spindle wobble on cold start", "bug", "no wobble",
        "Spindles wobble on a cold start; related to the torque limiter."),
}

RECORD = ("## gear-ratio-dashboard\n- summary: shipped the gearbox board.\n\n"
          "## Original prompt\n\n"
          + _draft("Gear ratio dashboard for every gearbox", "feature",
                   "the dashboard renders", GEAR_BODY))

PRS = [{"repo": "PyAutoWidget", "number": 7, "merged_at": "2026-02-05T10:00:00Z",
        "title": "Spindle torque limiter",
        "body": "Implements torque-limiter-for-spindles (the Mind draft)."},
       {"repo": "PyAutoWidget", "number": 8, "merged_at": "2026-02-06T10:00:00Z",
        "title": "Docs", "body": "Follow-up filed: spindle_wobble_on_cold_start.md"}]


@pytest.fixture()
def organism(tmp_path):
    root = tmp_path / "root"
    mind = root / "PyAutoMind"
    widget = root / "PyAutoWidget"
    _init(mind)
    _commit(mind, {"README.md": "# Mind\n"}, "init", "2026-01-01T09:00:00")
    _commit(mind, DRAFTS, "prompt: file six widget drafts", "2026-01-10T09:00:00")
    _commit(mind, {"complete/2026/02/gear-ratio-dashboard.md": RECORD},
            "close: gear-ratio-dashboard", "2026-02-03T09:00:00")
    # A ledger-only Mind commit naming a control by path: bookkeeping, not a ship.
    _commit(mind, {"queue.md": "# Queue\n"},
            "fix: queue draft/bug/pyautowidget/spindle_wobble_on_cold_start.md",
            "2026-02-04T09:00:00")

    _init(widget)
    _commit(widget, {"widget/core.py": "def spin():\n    return 1\n",
                     "tests/test_core.py":
                         "def test_existing_sprocket_helper():\n    assert True\n"},
            "init", "2025-12-01T09:00:00")
    # Names a control BEFORE it was filed — cannot be evidence of shipping it.
    _commit(widget, {}, "fix: spindle_wobble_on_cold_start.md cured",
            "2026-01-02T09:00:00")
    _commit(widget, {"tests/test_guard.py":
                     "def test_sprocket_guard_refuses_overflow():\n    assert True\n"},
            "feat: sprocket overflow guard", "2026-02-01T09:00:00")
    _commit(widget, {"widget/core.py": "def spin():\n    return 2\n"},
            "fix: flange rattle\n\nCloses draft/bug/pyautowidget/"
            "flange_rattle_under_load.md.", "2026-02-02T09:00:00")
    _commit(widget, {}, "docs: note\n\nFollow-up filed as "
            "draft/bug/pyautowidget/spindle_wobble_on_cold_start.md",
            "2026-02-03T09:00:00")
    cache = tmp_path / "prs.json"
    cache.write_text(json.dumps(PRS), encoding="utf-8")
    return {"root": root, "mind": mind, "widget": widget, "cache": cache}


def _snapshot(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix():
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def _flags(res):
    return {f["path"]: f for f in res["flags"]}


# --------------------------------------------------------------------------- #
# the three legs, and the controls
# --------------------------------------------------------------------------- #
def test_each_strong_leg_flags_its_draft_with_evidence(organism):
    res = _shipped.detect(organism["mind"], organism["root"],
                          pr_cache=organism["cache"], today="2026-03-01")
    flags = _flags(res)
    kinds = {p: {s["kind"] for s in f["signals"]} for p, f in flags.items()}

    witness = "draft/feature/pyautowidget/sprocket_guard.md"
    assert kinds[witness] == {"witness-exists"}
    ev = flags[witness]["signals"][0]["evidence"]
    assert "test_sprocket_guard_refuses_overflow" in ev
    assert "tests/test_guard.py" in ev and "sprocket overflow guard" in ev

    commit = "draft/bug/pyautowidget/flange_rattle_under_load.md"
    assert kinds[commit] == {"commit-names-draft"}
    assert "PyAutoWidget@" in flags[commit]["signals"][0]["evidence"]
    assert "Closes draft/bug" in flags[commit]["signals"][0]["evidence"]

    pr = "draft/feature/pyautowidget/torque_limiter_for_spindles.md"
    assert kinds[pr] == {"pr-names-draft"}
    assert "PyAutoWidget#7" in flags[pr]["signals"][0]["evidence"]

    dup = "draft/feature/pyautowidget/gear_ratio_dashboard.md"
    assert kinds[dup] == {"record-duplicates-draft"}
    assert "complete/2026/02/gear-ratio-dashboard.md" in flags[dup]["signals"][0]["evidence"]

    for f in flags.values():
        assert f["grade"] == "looks-shipped"
        assert f["close"].startswith("python3 scripts/lifecycle.py close ")
        assert f"--prompt {f['path']}" in f["close"]
        assert _shipped.DISMISS_FILE in f["dismiss"]


def test_the_vocabulary_control_set_is_not_flagged(organism):
    res = _shipped.detect(organism["mind"], organism["root"],
                          pr_cache=organism["cache"])
    flagged = set(_flags(res))
    assert "draft/feature/pyautowidget/sprocket_flange_gear_polish.md" not in flagged
    assert "draft/bug/pyautowidget/spindle_wobble_on_cold_start.md" not in flagged
    assert len(flagged) == 4
    # ...while the vocabulary ranker does see the shared words. The control is
    # a control: it shares vocabulary, not evidence.
    assert res["scanned"] == 6


def test_absent_checkouts_and_cache_degrade_to_no_evidence(organism, tmp_path):
    empty = tmp_path / "nowhere"
    empty.mkdir()
    res = _shipped.detect(organism["mind"], empty,
                          pr_cache=tmp_path / "missing.json")
    # Only the Mind-local leg (iii) remains.
    assert set(_flags(res)) == {"draft/feature/pyautowidget/gear_ratio_dashboard.md"}


def test_a_phase_series_title_is_not_a_duplicate():
    recs = [{"path": "complete/x.md", "title": "Widget rollout phase 1: gears",
             "words": ["a"]}]
    drafts = [{"path": "draft/feature/w/p2.md",
               "title": "Widget rollout phase 2: gears", "text": "", "filed": ""}]
    assert _shipped.leg_records(drafts, recs) == {}


def test_witness_names_tests_and_callables_not_paths():
    names = _shipped.witness_names(
        "`tests/test_x.py::test_widget_spins` and test_other_thing pass; "
        "`autowidget.fit_from()` works; `scripts/run.py` exists; `--flag`")
    assert {"test_widget_spins", "test_other_thing", "fit_from"} <= names
    assert not any("/" in n or n.endswith(".py") for n in names)


# --------------------------------------------------------------------------- #
# write path: only looks_shipped.json, never draft/
# --------------------------------------------------------------------------- #
def test_apply_writes_only_the_flags_file_and_never_draft(organism, capsys):
    mind = organism["mind"]
    before = _snapshot(mind / "draft")
    rc = _intake.main(["--mind", str(mind), "--apply", "looks-shipped",
                       "--root", str(organism["root"]),
                       "--pr-cache", str(organism["cache"])])
    assert rc == 0
    assert _snapshot(mind / "draft") == before
    data = json.loads((mind / "looks_shipped.json").read_text())
    assert len(data["flags"]) == 4
    status = subprocess.run(["git", "-C", str(mind), "status", "--porcelain"],
                            capture_output=True, text=True).stdout.split("\n")
    assert [ln for ln in status if ln.strip()] == ["?? looks_shipped.json"]
    # A re-run on an unchanged Mind is not a change (the daily job commits
    # nothing on a quiet night).
    res = _shipped.detect(mind, organism["root"], pr_cache=organism["cache"],
                          today="2099-01-01")
    assert _shipped.write(mind, res) is False


def test_reconcile_strong_lists_looks_shipped_above_vocabulary(organism, capsys):
    rc = _intake.main(["--mind", str(organism["mind"]), "--json", "reconcile",
                       "--strong", "--root", str(organism["root"])])
    assert rc == 0
    res = json.loads(capsys.readouterr().out)
    strong = {f["path"] for f in res["looks_shipped"]["flags"]}
    assert "draft/feature/pyautowidget/sprocket_guard.md" in strong
    assert not strong & {s["path"] for s in res["suspects"]}


# --------------------------------------------------------------------------- #
# consumers: dismissal, dashboard, state.json, batch plan
# --------------------------------------------------------------------------- #
def _apply(organism):
    res = _shipped.detect(organism["mind"], organism["root"],
                          pr_cache=organism["cache"])
    _shipped.write(organism["mind"], res)
    return res


def test_dismissed_and_closed_drafts_drop_out_at_once(organism):
    mind = organism["mind"]
    _apply(organism)
    assert len(_shipped.active_flags(mind)) == 4
    (mind / _shipped.DISMISS_FILE).write_text(
        "# Looks shipped — dismissed\n\n"
        "- draft/bug/pyautowidget/flange_rattle_under_load.md — 2026-03-01 — "
        "the commit fixed a different flange\n", encoding="utf-8")
    (mind / "draft/feature/pyautowidget/sprocket_guard.md").unlink()  # closed
    left = {f["path"] for f in _shipped.active_flags(mind)}
    assert left == {"draft/feature/pyautowidget/torque_limiter_for_spindles.md",
                    "draft/feature/pyautowidget/gear_ratio_dashboard.md"}
    # and a fresh run does not re-flag the dismissed draft
    res = _shipped.detect(mind, organism["root"], pr_cache=organism["cache"])
    assert "draft/bug/pyautowidget/flange_rattle_under_load.md" not in _flags(res)


def test_dashboard_renders_a_looks_shipped_section_and_feed(organism):
    _apply(organism)
    c = _intake.census(organism["mind"])
    assert len(c["looks_shipped"]) == 4
    md = _intake.render_dashboard(c)
    assert "## Looks shipped — confirm" in md
    assert "witness-exists" in md and "lifecycle.py close" in md
    # flagged drafts are not offered as picks
    start = md.split("## Start here", 1)[1].split("## Epics", 1)[0]
    assert "sprocket_guard.md" not in start
    assert "sprocket_flange_gear_polish.md" in start
    html = _intake.render_dashboard_html(c)
    assert "Looks shipped — confirm" in html
    state = json.loads(_intake.render_state(c))
    assert _state.validate_state(state) == []
    texts = [i["text"] for i in state["items"]]
    assert sum(t.startswith("looks shipped — confirm") for t in texts) == 4


def test_batch_plan_drops_looks_shipped_drafts(organism):
    mind = organism["mind"]
    _apply(organism)
    d = _batch.plan(_batch.survey(mind), budget=600, session_lane="local-dev")
    rejected = dict(d["rejected"])
    planned = {m["path"] for m in d["members"]}
    for path in _flags(_apply(organism)):
        assert path not in planned
        assert rejected[path].startswith("looks shipped")
    assert "draft/feature/pyautowidget/sprocket_flange_gear_polish.md" in planned
    # A dismissal returns the draft to the pool.
    (mind / _shipped.DISMISS_FILE).write_text(
        "- `draft/bug/pyautowidget/flange_rattle_under_load.md` — not it\n",
        encoding="utf-8")
    d = _batch.plan(_batch.survey(mind), budget=600, session_lane="local-dev")
    assert "draft/bug/pyautowidget/flange_rattle_under_load.md" in {
        m["path"] for m in d["members"]}
