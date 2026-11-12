"""Autonomous orchestrators phase 2 (PyAutoBrain#553): `Lane:` resource values,
the shift-brief validator, intake pass-through and the census lane histogram.

One test group per clause of the prompt's `Witness:` — (a) lane parsing,
(b) `_lane_ok` routing, (c) `batch brief --check`, (d) intake, (e) census.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BRAIN / "agents" / "conductors" / "intake"))
import _sizing  # noqa: E402
import _intake  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "_batch_p2", BRAIN / "agents" / "conductors" / "batch" / "_batch.py")
_batch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_batch)
_brief = _batch._brief

NEW_LANES = ("ral", "gpu", "wsl-data")

# The brief the schema in PyAutoMind/batches/AGENTS.md documents, as shipped in
# PyAutoMind/batches/examples/shift_brief_example.md. Carried here because the
# Brain's CI checks out the Brain alone; `test_mind_example_validates` checks
# the real file whenever a Mind checkout is beside this one.
EXAMPLE = """\
# Batch 2026-11-04 am
- dispatched: 2026-11-04T08:30Z
- review-at: 2026-11-04T11:30Z      # stated by the human
- shift: morning
- issue: https://github.com/example-owner/mind/issues/1
- packet: yes
- heart-ack:
  - Release YELLOW; monitoring RED
- brief:
  - goals:
    - 1. land the next cluster-strong-lensing slice
  - tasks:
    - draft/feature/autolens/example_named_task.md
  - backlog: scoped
  - scoped:
    - epics: cluster-strong-lensing
    - tiers: notify, glance
  - exclude:
    - epics: euclid-dr1
  - review-minutes: 45
  - lanes: any local-dev ral
  - merge-cap: 3
  - token-budget: 2000000
  - ral-allowance:
    - packets: 2
    - partition: ral
    - cpu-hours: 64
"""


def _prompt(lane_line: str) -> dict:
    return _sizing.declared_header(
        f"# T\n\nType: feature\nTarget: PyAutoBrain\n{lane_line}\n\nBody.\n")


# --- (a) lane parsing ----------------------------------------------------------

@pytest.mark.parametrize("lane", ("any", "local-dev") + NEW_LANES)
def test_every_lane_value_parses(lane):
    assert _prompt(f"Lane: {lane}")["lane"] == lane


def test_archived_two_value_spelling_is_rejected_and_recorded():
    h = _prompt("Lane: any | local-dev")
    assert h["lane"] is None            # read as `any` by every consumer
    assert h["lane_invalid"] == "any | local-dev"


def test_first_valid_declaration_wins():
    h = _sizing.declared_header("Type: feature\nLane: ral\nLane: gpu\n")
    assert h["lane"] == "ral"


# --- (b) routing ---------------------------------------------------------------

@pytest.mark.parametrize("lane", NEW_LANES + ("local-dev",))
def test_resource_lanes_are_laptop_only(lane):
    assert _sizing.lane_is_local(lane)
    assert _batch._lane_ok(lane, "web-github") is False
    assert _batch._lane_ok(lane, "local-dev") is True


def test_any_runs_anywhere():
    assert not _sizing.lane_is_local("any") and not _sizing.lane_is_local(None)
    assert _batch._lane_ok("any", "web-github")


def _rec(path, lane="any", tier="glance", **kw):
    r = {"path": path, "repos": [], "work_type": "feature", "difficulty": "small",
         "score": 1, "consequence": tier, "witness": "w", "review_minutes": 3,
         "unattended": "ready", "why": "", "ready_why": "", "epic": None,
         "lane": lane, "priority": "normal", "blocked": False,
         "autonomy": "supervised", "autonomy_cap": "supervised",
         "declared_autonomy": None, "done": False, "themes": []}
    r.update(kw)
    return r


def test_plan_names_the_other_lane_resources():
    recs = [_rec("draft/a.md", "ral"), _rec("draft/b.md", "ral"),
            _rec("draft/c.md", "gpu"), _rec("draft/d.md")]
    d = _batch.plan(recs, session_lane="web-github")
    assert d["other_lane_ready"] == 3
    assert d["other_lane_by_lane"] == {"ral": 2, "gpu": 1}
    assert d["lane_counts"] == {"ral": 2, "any": 1, "gpu": 1}


# --- (c) brief --check ---------------------------------------------------------

def _mind(tmp_path: Path) -> Path:
    mind = tmp_path / "mind"
    (mind / "draft" / "feature" / "x").mkdir(parents=True)
    (mind / "batches").mkdir()
    return mind


def _write(tmp_path: Path, text: str) -> Path:
    f = tmp_path / "brief.md"
    f.write_text(text, encoding="utf-8")
    return f


def test_example_brief_is_accepted(tmp_path):
    res = _brief.check(_write(tmp_path, EXAMPLE), _mind(tmp_path))
    assert res["ok"], res["errors"]
    # The named task is a placeholder: a warning, never a refusal.
    assert any("resolves to no prompt" in w for w in res["warnings"])


def test_mind_example_validates():
    mind = Path(os.environ.get("PYAUTO_MIND") or BRAIN.parent / "PyAutoMind")
    example = mind / "batches" / "examples" / "shift_brief_example.md"
    if not example.is_file():
        pytest.skip("no PyAutoMind checkout beside this Brain")
    res = _brief.check(example, mind)
    assert res["ok"], res["errors"]


def test_brief_without_review_at_is_refused(tmp_path):
    text = "\n".join(l for l in EXAMPLE.splitlines() if "review-at" not in l)
    res = _brief.check(_write(tmp_path, text), _mind(tmp_path))
    assert not res["ok"]
    assert any(e.startswith("review-at: missing") for e in res["errors"])


def test_cloud_is_not_a_lane(tmp_path):
    text = EXAMPLE.replace("lanes: any local-dev ral", "lanes: cloud")
    res = _brief.check(_write(tmp_path, text), _mind(tmp_path))
    assert not res["ok"]
    assert any(e.startswith("brief.lanes: cloud") for e in res["errors"])


def test_merge_cap_refused_when_every_named_task_is_judge(tmp_path):
    mind = _mind(tmp_path)
    for name in ("one", "two"):  # no Witness: -> judge
        (mind / "draft" / "feature" / "x" / f"{name}.md").write_text(
            f"# {name}\n\nType: feature\nTarget: PyAutoBrain\n\nBody.\n")
    text = (EXAMPLE
            .replace("    - draft/feature/autolens/example_named_task.md",
                     "    - draft/feature/x/one.md\n    - draft/feature/x/two.md")
            .replace("backlog: scoped", "backlog: none"))
    res = _brief.check(_write(tmp_path, text), mind)
    assert not res["ok"]
    assert any(e.startswith("brief.merge-cap: 3") for e in res["errors"])
    # A dip can still pick glance work, so the same cap stands under one.
    res = _brief.check(_write(tmp_path, text.replace("backlog: none",
                                                     "backlog: fill-idle")), mind)
    assert res["ok"], res["errors"]
    # And 0 is always allowed.
    res = _brief.check(_write(tmp_path, text.replace("merge-cap: 3",
                                                     "merge-cap: 0")), mind)
    assert res["ok"], res["errors"]


def test_ral_lane_needs_an_allowance(tmp_path):
    text = EXAMPLE.split("  - ral-allowance:")[0]
    res = _brief.check(_write(tmp_path, text), _mind(tmp_path))
    assert any(e.startswith("brief.ral-allowance: missing") for e in res["errors"])


def test_calibration_refuses_a_brief_after_an_unmeasured_record(tmp_path):
    mind = _mind(tmp_path)
    (mind / "batches" / "2026-11-03-pm.md").write_text(
        "# Batch 2026-11-03 pm\n- dispatched: 2026-11-03T17:00Z\n")
    brief = mind / "batches" / "2026-11-04-am.md"
    brief.write_text(EXAMPLE)
    res = _brief.check(brief, mind)
    assert any(e.startswith("review-minutes-actual: missing") for e in res["errors"])
    (mind / "batches" / "2026-11-03-pm.md").write_text(
        "# Batch 2026-11-03 pm\n- dispatched: 2026-11-03T17:00Z\n"
        "- review-minutes-actual: 20\n")
    assert _brief.check(brief, mind)["ok"]


def test_cli_exit_codes(tmp_path):
    mind = _mind(tmp_path)
    good = _write(tmp_path, EXAMPLE)
    assert _batch.main(["brief", "--check", str(good), "--mind", str(mind)]) == 0
    good.write_text(EXAMPLE.replace("lanes: any local-dev ral", "lanes: cloud"))
    assert _batch.main(["brief", "--check", str(good), "--mind", str(mind)]) == 1


def test_plan_under_a_brief_puts_named_tasks_first_and_never_dips_outside():
    brief = _brief.parse(EXAMPLE.replace(
        "draft/feature/autolens/example_named_task.md", "draft/named.md"))["brief"]
    recs = [_rec("draft/cheap.md", tier="judge", epic="other-epic"),
            _rec("draft/named.md", tier="judge", review_minutes=20),
            _rec("draft/in_scope.md", epic="cluster-strong-lensing"),
            _rec("draft/excluded.md", epic="euclid-dr1", tier="notify")]
    d = _batch.plan(recs, session_lane="local-dev", brief=brief)
    paths = [m["path"] for m in d["members"]]
    assert paths[0] == "draft/named.md"
    assert "draft/in_scope.md" in paths
    reasons = dict(d["rejected"])
    assert reasons["draft/cheap.md"] == "outside the brief's scoped backlog"
    assert reasons["draft/excluded.md"] == "excluded by the brief"
    assert d["review_budget"] == 45


# --- (d) intake ----------------------------------------------------------------

def test_intake_proposes_ral_from_the_text():
    d = _intake.analyse("Profile the likelihood on RAL with SLURM for @PyAutoBrain.",
                        "test")
    assert "\nLane: ral" in d["header"]


@pytest.mark.parametrize("text,lane", [
    ("Benchmark the CUDA path on the laptop GPU for @PyAutoBrain.", "gpu"),
    ("Read the dataset under /mnt/c/Users/x for @PyAutoBrain.", "wsl-data"),
])
def test_intake_proposes_gpu_and_wsl_data(text, lane):
    assert f"\nLane: {lane}" in _intake.analyse(text, "test")["header"]


def test_intake_writes_no_lane_when_nothing_decides_one():
    """M2.3 (2026-11-12): with no signal, no header and no `--lane`, intake
    leaves the lane undecided and refuses to file (`test_lane_fail_closed_queue`)."""
    d = _intake.analyse("Tidy a docstring in @PyAutoBrain.", "test")
    assert "Lane:" not in d["header"] and d["lane"] is None and d["lane_refusal"]


DECLARED = """\
# Wire the watcher

Type: feature
Target: PyAutoBrain
Epic: autonomous-orchestrators
Phase: 3
Filed: 2026-11-03
Blocked-by: PyAutoBrain#1
Closes-when: PyAutoBrain#2 merged
Lane: local-dev

It submits to RAL via sbatch, but the declared lane wins.
"""


def test_declared_optional_headers_survive_apply_unchanged(tmp_path):
    mind = tmp_path / "mind"
    (mind / "draft").mkdir(parents=True)
    d = _intake.analyse(DECLARED, "test")
    rel = _intake.write_prompt(mind, d, DECLARED, "test")
    written = (mind / rel).read_text()
    head = written.split("\n\n", 2)[1].splitlines()
    for line in ("Epic: autonomous-orchestrators", "Phase: 3", "Filed: 2026-11-03",
                 "Blocked-by: PyAutoBrain#1", "Closes-when: PyAutoBrain#2 merged",
                 "Lane: local-dev"):
        assert line in head, line
    # Documented order: pass-through keys after Status:, Lane: after Unattended:.
    assert head.index("Status: formalised") < head.index("Filed: 2026-11-03") \
        < head.index("Epic: autonomous-orchestrators") < head.index("Phase: 3") \
        < head.index("Blocked-by: PyAutoBrain#1")
    assert head.index(next(l for l in head if l.startswith("Unattended:"))) \
        < head.index("Lane: local-dev")
    # The input's own header block is not echoed into the body.
    assert written.count("Epic: autonomous-orchestrators") == 1


# --- (e) census ----------------------------------------------------------------

def test_census_lane_histogram_totals_the_prompt_count(tmp_path, capsys):
    mind = tmp_path / "mind"
    folder = mind / "draft" / "feature" / "x"
    folder.mkdir(parents=True)
    for name, lane in (("a", "ral"), ("b", "gpu"), ("c", None), ("d", "local-dev"),
                       ("e", "any | local-dev")):
        lane_line = f"Lane: {lane}\n" if lane else ""
        (folder / f"{name}.md").write_text(
            f"# {name}\n\nType: feature\nTarget: PyAutoBrain\n{lane_line}\nBody.\n")
    c = _intake.census(mind)
    assert c["by_lane"] == {"any": 2, "gpu": 1, "local-dev": 1, "ral": 1}
    assert sum(c["by_lane"].values()) == c["total"] == 5
    assert any("unknown Lane: 'any | local-dev'" in h for h in c["hygiene"])
    _intake.emit_census(c)
    assert "By lane:         any 2 · gpu 1 · local-dev 1 · ral 1" in capsys.readouterr().out
    assert "Lanes: any 2 · gpu 1 · local-dev 1 · ral 1" in _intake.render_dashboard(c)
