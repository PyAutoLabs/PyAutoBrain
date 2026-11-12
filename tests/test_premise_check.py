"""The premise check (PyAutoBrain#608, M1.3 slice 1): `batch premise`, its
`Verified:` stamp through the one-Mind-writer ledger, the brief-time leg and
the worker template's first step.

Witness (a) is replayed here on the two drafts that were obsolete in the
2026-11-06-pm shift, exactly as they stood in the Mind before it
(`tests/fixtures/premise/`, from the Mind commit before the shift's brief).
The repos they name are rebuilt as small git fixtures carrying the facts the
real ones carried at dispatch: the harness deleted on 2026-09-30, and a Heart
timing record showing the "300 s" script at ~8-16 s for the days before.
Repo names are read from the fixtures, never written here (tenant firewall).
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / "fixtures" / "premise"
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BRAIN / "agents" / "conductors" / "batch"))
_spec = importlib.util.spec_from_file_location(
    "_batch_premise", BRAIN / "agents" / "conductors" / "batch" / "_batch.py")
_batch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_batch)
import _mind_writer  # noqa: E402
import _orchestrator as orch  # noqa: E402
import _premise  # noqa: E402

SHIFT = "2026-11-06T11:20Z"
DELAUNAY = FIX / "delaunay_smoke_300s_cap.md"
GALLERY = FIX / "gallery_runner_missing_tiers.md"


def _repo_of(draft: Path) -> str:
    return _premise.declared_repos(draft.read_text())[0]


def _git(repo: Path, *args, date: str = "2026-09-01T12:00:00Z"):
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c",
                    "user.email=t@example.invalid", *args], check=True,
                   capture_output=True, env=env)


def _repo(root: Path, name: str, files: dict[str, str], date="2026-09-01T12:00:00Z") -> Path:
    repo = root / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    for rel, body in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial", date=date)
    return repo


def _heart(root: Path, repo: str, script: str, secs, start: str):
    day = _dt.date.fromisoformat(start)
    rows = []
    for i, s in enumerate(secs):
        at = (day + _dt.timedelta(days=i // 2)).isoformat()
        rows.append(json.dumps({"at": f"{at}T10:00:00Z", "date": at,
                                "entries": {script: [s, "passed", 300.0]}}))
    _repo(root, "PyAutoHeart",
          {f"timings/scripts/{repo}.jsonl": "\n".join(rows) + "\n"},
          date="2026-11-05T12:00:00Z")


SCRIPT = "scripts/imaging/features/pixelization/delaunay.py"


def _delaunay_root(tmp_path, secs, start="2026-11-02"):
    root = tmp_path / "root"
    name = _repo_of(DELAUNAY)
    _repo(root, name, {SCRIPT: "# seven Nautilus fits\n",
                       "smoke_tests.txt": "imaging/features/pixelization/delaunay.py\n"})
    _heart(root, name, SCRIPT, secs, start)
    return root


def _gallery_root(tmp_path):
    root = tmp_path / "root"
    repo = _repo(root, _repo_of(GALLERY), {"gallery/gallery_run.sh": "DEFAULT_SCRIPTS=()\n",
                                          "scripts/imaging/visualization/x.py": "\n"})
    (repo / "gallery" / "gallery_run.sh").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "chore: retire the pre-organ gallery harness",
         date="2026-09-30T12:00:00Z")
    return root


# --- Witness (a): the two obsolete prompts of the 2026-11-06-pm shift ----------

def test_witness_a_delaunay_smoke_cap_is_obsolete_by_the_timing_record(tmp_path):
    root = _delaunay_root(tmp_path, [8.3, 9.8, 15.9, 14.4, 9.3, 11.0, 8.6, 14.5])
    res = _premise.check(DELAUNAY, root, fetch=False, at=SHIFT, offline=True)
    assert res["status"] == "obsolete", res
    timing = next(e for e in res["evidence"] if e.startswith("timing contradicted"))
    assert SCRIPT in timing and "≥300 s" in timing
    # A bug says what a worker must reproduce before fixing anything.
    assert res["reproduce"].startswith("reproduce before fixing:")


def test_witness_a_gallery_runner_is_obsolete_by_the_deleted_harness(tmp_path):
    res = _premise.check(GALLERY, _gallery_root(tmp_path), fetch=False, at=SHIFT,
                         offline=True)
    assert res["status"] == "obsolete", res
    gone = next(e for e in res["evidence"] if e.startswith("GONE"))
    assert "scripts/gallery/gallery_run.sh" in gone
    assert "retire the pre-organ gallery harness" in gone
    assert any("title or Witness" in r for r in res["reasons"])


def test_witness_a_is_cheap(tmp_path):
    """A few git reads, never an LLM: the whole replay stays well under the
    witness's 'few thousand tokens' when printed."""
    root = _delaunay_root(tmp_path, [9.0, 10.0])
    out = _premise.report(_premise.check(DELAUNAY, root, fetch=False, at=SHIFT,
                                         offline=True))
    assert len(out) < 4000


# --- the timing probe's guards ---------------------------------------------------

def test_a_timing_record_that_still_shows_the_overrun_is_not_obsolete(tmp_path):
    root = _delaunay_root(tmp_path, [330.0, 338.8, 353.9, 305.0])
    res = _premise.check(DELAUNAY, root, fetch=False, at=SHIFT, offline=True)
    assert res["status"] == "ok", res
    assert any(e.startswith("timing reproduced") for e in res["evidence"])


def test_a_stale_timing_record_decides_nothing(tmp_path):
    root = _delaunay_root(tmp_path, [9.0, 10.0], start="2026-09-16")
    res = _premise.check(DELAUNAY, root, fetch=False, at=SHIFT, offline=True)
    assert res["status"] == "ok", res
    assert any(e.startswith("timing stale-record") for e in res["evidence"])


def test_a_release_profile_claim_is_not_compared_with_smoke_timings(tmp_path):
    root = _delaunay_root(tmp_path, [9.0, 10.0])
    text = DELAUNAY.read_text().replace(
        "sits on the 300 s smoke cap (330–354 s under the release profile)",
        "needs its 3600 s release override")
    res = _premise.check(DELAUNAY, root, fetch=False, at=SHIFT, offline=True, text=text)
    assert not any(e.startswith("timing") for e in res["evidence"])


# --- gone, moved, ignored, absent -----------------------------------------------

def _draft(tmp_path, repo: str, body: str, witness: str = "") -> Path:
    f = tmp_path / "d.md"
    f.write_text(f"# A task\n\nType: feature\nTarget: {repo}\nRepos:\n- {repo}\n"
                 + (f"Witness: {witness}\n" if witness else "") + f"\n{body}\n")
    return f


def _demo(tmp_path) -> Path:
    root = tmp_path / "root"
    repo = _repo(root, "demo_repo", {"pkg/a.py": "def keep_me():\n    pass\n",
                                     "pkg/old.py": "def dropped():\n    pass\n",
                                     "pkg/other.py": "x = 1\n",
                                     "pkg/moved.py": "def m():\n    return 'a long enough body'\n"})
    (repo / "pkg" / "old.py").unlink()
    (repo / "pkg" / "other.py").unlink()
    (repo / "pkg" / "new").mkdir()
    (repo / "pkg" / "moved.py").rename(repo / "pkg" / "new" / "moved.py")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "refactor: drop old, move moved",
         date="2026-10-01T12:00:00Z")
    return root


def test_everything_found_is_ok(tmp_path):
    root = _demo(tmp_path)
    d = _draft(tmp_path, "demo_repo", "Edit `pkg/a.py` and `keep_me()`.")
    res = _premise.check(d, root, fetch=False, offline=True)
    assert res["status"] == "ok", res
    assert res["repos"]["demo_repo"]
    assert _premise.verified_value(res).startswith(res["date"])


def test_a_rename_is_moved_not_gone(tmp_path):
    root = _demo(tmp_path)
    d = _draft(tmp_path, "demo_repo", "Body.", witness="`pkg/moved.py` still runs")
    res = _premise.check(d, root, fetch=False, offline=True)
    assert res["status"] == "ok", res
    assert any("pkg/new/moved.py" in e for e in res["evidence"])


def test_one_path_gone_in_the_body_only_is_unknown(tmp_path):
    root = _demo(tmp_path)
    d = _draft(tmp_path, "demo_repo", "Read `pkg/old.py` for context; edit `pkg/a.py`.")
    res = _premise.check(d, root, fetch=False, offline=True)
    assert res["status"] == "unknown", res
    assert any(e.startswith("GONE pkg/old.py") for e in res["evidence"])


def test_every_named_path_gone_is_obsolete(tmp_path):
    root = _demo(tmp_path)
    d = _draft(tmp_path, "demo_repo", "Merge `pkg/old.py` into `pkg/other.py`.")
    assert _premise.check(d, root, fetch=False, offline=True)["status"] == "obsolete"


def test_a_removed_function_named_by_the_witness_is_obsolete(tmp_path):
    root = _demo(tmp_path)
    d = _draft(tmp_path, "demo_repo", "Edit `pkg/a.py`.", witness="`dropped()` is fast")
    res = _premise.check(d, root, fetch=False, offline=True)
    assert res["status"] == "obsolete", res
    assert any(e.startswith("GONE dropped()") for e in res["evidence"])


def test_a_file_to_create_is_not_evidence(tmp_path):
    root = _demo(tmp_path)
    d = _draft(tmp_path, "demo_repo", "Add `pkg/brand_new.py` beside `pkg/a.py`.",
               witness="`pkg/brand_new.py` exists")
    assert _premise.check(d, root, fetch=False, offline=True)["status"] == "ok"


def test_at_replays_main_as_it_stood(tmp_path):
    root = _demo(tmp_path)
    d = _draft(tmp_path, "demo_repo", "Merge `pkg/old.py` into `pkg/other.py`.")
    res = _premise.check(d, root, fetch=False, offline=True, at="2026-09-15T00:00Z")
    assert res["status"] == "ok", res


def test_a_root_level_namesake_deletion_is_not_evidence(tmp_path):
    """Review finding 1: a deleted root-level `__init__.py` must not make the
    `pkg/solver_v2/__init__.py` a Witness means to CREATE read as gone."""
    root = tmp_path / "root"
    repo = _repo(root, "demo_repo", {"__init__.py": "\n", "pkg/a.py": "\n"})
    (repo / "__init__.py").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "drop the root __init__", date="2022-01-01T00:00:00Z")
    d = _draft(tmp_path, "demo_repo", "Add a solver beside `pkg/a.py`.",
               witness="`pkg/point/solver_v2/__init__.py` exports Solver")
    res = _premise.check(d, root, fetch=False, offline=True)
    assert res["status"] == "ok", res
    assert not any(e.startswith("GONE") for e in res["evidence"])
    assert any("pkg/point/solver_v2/__init__.py" in e for e in res["evidence"]
               if e.startswith("absent"))


def _two_repos(tmp_path) -> Path:
    """A function removed from the declared repo long ago, alive in another
    library checkout — review finding 2 (`LensCalc.from_tracer()`)."""
    root = tmp_path / "root"
    lens = _repo(root, "lens_lib", {"lens/calc.py": "def from_tracer():\n    pass\n"},
                 date="2020-01-01T00:00:00Z")
    (lens / "lens" / "calc.py").write_text("x = 1\n")
    _git(lens, "add", "-A")
    _git(lens, "commit", "-q", "-m", "removed from_tracer", date="2020-03-28T00:00:00Z")
    _repo(root, "galaxy_lib", {"galaxy/calc.py": "class LensCalc:\n"
                               "    def from_tracer(cls):\n        pass\n"})
    return root


def test_a_function_alive_in_another_checkout_is_found_not_gone(tmp_path):
    root = _two_repos(tmp_path)
    d = _draft(tmp_path, "lens_lib", "Edit `lens/calc.py`.",
               witness="`LensCalc.from_tracer()` returns the plane")
    res = _premise.check(d, root, fetch=False, offline=True)
    assert res["status"] == "ok", res
    assert any("from_tracer (galaxy_lib" in e for e in res["evidence"])


def test_a_removal_older_than_the_draft_is_not_evidence(tmp_path):
    root = _two_repos(tmp_path)
    shutil_rm = __import__("shutil").rmtree
    shutil_rm(root / "galaxy_lib")                     # alive nowhere now
    text = _draft(tmp_path, "lens_lib", "Edit `lens/calc.py`.",
                  witness="`from_tracer()` returns the plane").read_text()
    d = tmp_path / "filed.md"
    d.write_text(text.replace("Type: feature\n", "Type: feature\nFiled: 2026-09-01\n"))
    res = _premise.check(d, root, fetch=False, offline=True)
    assert res["status"] == "ok", res
    assert not any(e.startswith("GONE") for e in res["evidence"])
    # The same removal AFTER the draft was filed is evidence.
    d.write_text(text.replace("Type: feature\n", "Type: feature\nFiled: 2020-02-01\n"))
    assert _premise.check(d, root, fetch=False, offline=True)["status"] == "obsolete"


def test_a_crashing_check_is_unknown_and_exit_0(tmp_path, monkeypatch, capsys):
    root = _demo(tmp_path)
    mind, f = _mind_with(tmp_path, DEMO_DRAFT)
    monkeypatch.setattr(_premise, "extract", lambda text: 1 / 0)
    rc = _batch.main(["premise", str(f), "--mind", str(mind), "--root", str(root),
                      "--no-fetch", "--offline", "--write-verified"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("premise: unknown (check failed: ZeroDivisionError")
    assert f.read_text() == DEMO_DRAFT


def test_no_resolvable_repo_is_unknown(tmp_path):
    d = _draft(tmp_path, "no_such_repo", "Edit `pkg/a.py`.")
    res = _premise.check(d, tmp_path, fetch=False, offline=True)
    assert res["status"] == "unknown"


def test_extract_reads_paths_functions_and_refs():
    got = _premise.extract("Edit `scripts/x.py:29` and `a/b/`; call `mod.fetch(x)`; "
                           "see Repo#12 and https://github.com/o/r/pull/7; "
                           "not `draft/a.md`, `n_live=100` or `*.py`.")
    assert got["paths"] == ["scripts/x.py", "a/b"]
    assert got["functions"] == ["fetch"]
    assert ("o/r", 7) in got["refs"] and ("Repo", 12) in got["refs"]


# --- the Verified: stamp, through the ledger -------------------------------------

def _mind_with(tmp_path, draft_text: str) -> tuple[Path, Path]:
    mind = tmp_path / "mind"
    f = mind / "draft" / "feature" / "demo" / "d.md"
    f.parent.mkdir(parents=True)
    f.write_text(draft_text)
    return mind, f


DEMO_DRAFT = ("# A task\n\nType: feature\nTarget: demo_repo\nRepos:\n- demo_repo\n"
              "Unattended: ready\nLane: any\n\nEdit `pkg/a.py`.\n")


def test_cli_stamps_verified_through_the_ledger_inside_a_shift(tmp_path, monkeypatch):
    root = _demo(tmp_path)
    mind, f = _mind_with(tmp_path, DEMO_DRAFT)
    ledger = tmp_path / "ledger"
    monkeypatch.setenv("PYAUTO_SHIFT_LEDGER_DIR", str(ledger))
    rc = _batch.main(["premise", "draft/feature/demo/d.md", "--mind", str(mind),
                      "--root", str(root), "--no-fetch", "--offline", "--write-verified"])
    assert rc == 0
    assert f.read_text() == DEMO_DRAFT            # a worker never writes the Mind
    op = json.loads(next(ledger.glob("*.json")).read_text())
    assert op["op"] == "set-header" and op["key"] == "Verified"
    assert op["path"] == "draft/feature/demo/d.md"
    assert re.match(r"\d{4}-\d\d-\d\d [0-9a-f]{8} \(demo_repo\)$", op["value"])


def test_cli_stamps_in_place_outside_a_shift_and_never_on_obsolete(tmp_path, monkeypatch):
    root = _demo(tmp_path)
    monkeypatch.delenv("PYAUTO_SHIFT_LEDGER_DIR", raising=False)
    mind, f = _mind_with(tmp_path, DEMO_DRAFT)
    assert _batch.main(["premise", str(f), "--mind", str(mind), "--root", str(root),
                        "--no-fetch", "--offline", "--write-verified"]) == 0
    head = f.read_text().split("\n\n")[1].splitlines()
    assert head.index("Unattended: ready") + 1 == head.index(
        next(l for l in head if l.startswith("Verified: ")))
    obsolete = DEMO_DRAFT.replace("Edit `pkg/a.py`.", "Merge `pkg/old.py` into `pkg/other.py`.")
    f.write_text(obsolete)
    assert _batch.main(["premise", str(f), "--mind", str(mind), "--root", str(root),
                        "--no-fetch", "--offline", "--write-verified"]) == 1
    assert f.read_text() == obsolete


def test_set_header_replaces_or_inserts_and_touches_nothing_else():
    text = "# T\n\nType: bug\nRepos:\n- a\nUnattended: ready\nLane: any\n\nBody: prose.\n"
    once = _mind_writer.set_header(text, "Verified", "2026-11-12 abc (a)")
    assert once == text.replace("Unattended: ready\n",
                                "Unattended: ready\nVerified: 2026-11-12 abc (a)\n")
    twice = _mind_writer.set_header(once, "Verified", "2026-11-13 def (a)")
    assert twice.count("Verified:") == 1 and "2026-11-13 def (a)" in twice
    bare = _mind_writer.set_header("# T\n\nJust prose.\n", "Lane", "any")
    assert bare == "# T\n\nLane: any\n\nJust prose.\n"


def test_set_header_on_a_draft_gone_from_main_skips_not_raises(tmp_path):
    lm = types.SimpleNamespace(is_ledger_path=lambda p: p.startswith("draft/"))
    op = {"op": "set-header", "path": "draft/x/moved.md", "key": "Verified", "value": "v"}
    note = _mind_writer.apply_op(tmp_path, op, lm)
    assert note and "skipped" in note and not (tmp_path / "draft").exists()


def test_set_header_op_validates_and_applies(tmp_path):
    lm = types.SimpleNamespace(is_ledger_path=lambda p: p.startswith("draft/"))
    good = {"op": "set-header", "path": "draft/x/d.md", "key": "Verified", "value": "v"}
    assert _mind_writer.validate_op(good, lm) == []
    assert _mind_writer.validate_op({**good, "value": "a\nb"}, lm)
    assert _mind_writer.validate_op({**good, "key": "verified: x"}, lm)
    assert _mind_writer.validate_op({**good, "path": "scripts/x.py"}, lm)
    (tmp_path / "draft" / "x").mkdir(parents=True)
    (tmp_path / "draft" / "x" / "d.md").write_text(DEMO_DRAFT)
    assert _mind_writer.apply_op(tmp_path, good, lm) is None
    assert "Verified: v\n" in (tmp_path / "draft" / "x" / "d.md").read_text()


# --- brief time, and the worker's first step ------------------------------------

BRIEF = """\
# Batch 2026-11-06 pm
- dispatched: 2026-11-06T11:20Z
- review-at: 2026-11-06T12:20Z
- brief:
  - goals:
    - 1. replay
  - tasks:
    - {task}
  - backlog: none
  - review-minutes: 30
  - lanes: any local-dev
  - merge-cap: 1
  - token-budget: 2000000
"""


def test_brief_check_flags_a_stale_pick_before_the_shift(tmp_path, capsys):
    root = _gallery_root(tmp_path)
    mind, f = _mind_with(tmp_path, GALLERY.read_text())
    brief = tmp_path / "brief.md"
    brief.write_text(BRIEF.format(task="draft/feature/demo/d.md"))
    rc = _batch.main(["brief", "--check", str(brief), "--mind", str(mind), "--root",
                      str(root), "--no-fetch", "--offline", "--json"])
    res = json.loads(capsys.readouterr().out)
    assert rc == 0                                 # flagged, not refused
    assert res["premise"][0]["status"] == "obsolete"
    assert any("premise OBSOLETE" in w and "gallery_run.sh" in w for w in res["warnings"])
    rc = _batch.main(["brief", "--check", str(brief), "--mind", str(mind), "--root",
                      str(root), "--no-premise", "--json"])
    assert json.loads(capsys.readouterr().out)["premise"] == []


def test_the_premise_check_is_the_workers_first_step(tmp_path):
    prompt = orch.session_command("t1", "draft/x/t1.md", tmp_path / "shift.md",
                                  tmp_path / "leases", "auto")[-1]
    step = f"{orch.BRAIN_CLI} batch premise draft/x/t1.md --write-verified"
    assert step in prompt
    assert prompt.index(step) < prompt.index("Use the start-dev skill.")
    assert "`obsolete` (exit 1): stop." in prompt
    assert "`unknown` (exit 0, including `check failed: …`): go on" in prompt


def test_the_digest_names_an_obsolete_worker():
    import _digest
    out = _digest.parse_done("obsolete a file the Witness: names is gone on main\n")
    assert out == {"prs": [], "merged": [],
                   "obsolete": "a file the Witness: names is gone on main"}
    state, tiered = _digest.task_state("t1", {"outcomes": {"t1": out}}, None)
    assert state == ("obsolete (premise check): a file the Witness: names is gone "
                     "on main") and not tiered
    bare = _digest.task_state("t1", {"outcomes": {"t1": _digest.parse_done("obsolete")}}, None)
    assert bare[0] == "obsolete (premise check): see its proof packet"
