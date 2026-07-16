"""Contract tests for the workspace conductor's CLI footing.

Hermetic: PYAUTO_ROOT points at a fabricated temp workspace layout, so
decisions/surveys are asserted structurally without depending on the state of
the real checkouts. The conductor is decision-only — every test also relies on
it never writing anything (asserted explicitly in test_never_writes).
"""

import json
import os
import subprocess
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
BRAIN = BRAIN_HOME / "bin" / "pyauto-brain"

DECISION_KEYS = {
    "title", "prompt_path", "family", "target_repo", "register", "placement",
    "example_packages", "sibling_to_mirror", "prose_tier", "format_checklist",
    "format_grounding", "notes", "next_action",
}


def _run(args, root):
    env = {**os.environ, "PYAUTO_ROOT": str(root)}
    return subprocess.run(
        [str(BRAIN), "workspace", *args],
        capture_output=True, text=True, env=env,
    )


def _fabricate_workspace(root, repo, packages):
    for package, n_scripts in packages.items():
        d = root / repo / "scripts" / package
        d.mkdir(parents=True)
        for i in range(n_scripts):
            (d / f"example_{i}.py").write_text("# example\n")


def test_plan_json_is_a_complete_workspace_decision(tmp_path):
    _fabricate_workspace(tmp_path, "autolens_workspace", {"imaging": 2})
    r = _run(["--json", "an imaging example for autolens_workspace"], tmp_path)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert set(d) == DECISION_KEYS
    assert d["family"] == "autolens"
    assert d["target_repo"] == "autolens_workspace"
    assert d["register"] == "workspace"
    assert d["placement"] == "imaging"
    assert d["sibling_to_mirror"] == "autolens_workspace/scripts/imaging/"
    assert d["prose_tier"] == "judgment"
    assert d["format_checklist"]


def test_howto_register_from_target_repo(tmp_path):
    r = _run(["--json", "new HowToLens chapter on mass profiles"], tmp_path)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["family"] == "autolens"
    assert d["target_repo"] == "HowToLens"
    assert d["register"] == "howto"
    # The howto register carries its own checklist items on top of the shared ones.
    assert any("first-time learner" in item for item in d["format_checklist"])


def test_howto_register_from_teaching_words(tmp_path):
    r = _run(["--json", "an autogalaxy tutorial for undergrads"], tmp_path)
    d = json.loads(r.stdout)
    assert d["register"] == "howto"
    assert d["target_repo"] == "HowToGalaxy"


def test_newborn_workspace_anchors_on_fallback_sibling(tmp_path):
    _fabricate_workspace(tmp_path, "autolens_workspace", {"imaging": 1, "guides": 1})
    r = _run(["--json", "an imaging example for autoreduce_workspace"], tmp_path)
    d = json.loads(r.stdout)
    assert d["family"] == "autoreduce"
    assert d["target_repo"] == "autoreduce_workspace"
    assert d["placement"] == "imaging"
    assert d["sibling_to_mirror"] == "autolens_workspace/scripts/imaging/"
    assert any("anchored on autolens_workspace" in n for n in d["notes"])


def test_plan_reads_a_mind_prompt_path(tmp_path):
    prompt = (
        tmp_path / "PyAutoMind" / "draft" / "docs" / "workspaces" / "example.md"
    )
    prompt.parent.mkdir(parents=True)
    prompt.write_text("# Interferometer example\n\nAdd it to @autolens_workspace.\n")
    _fabricate_workspace(tmp_path, "autolens_workspace", {"interferometer": 1})
    r = _run(["--json", "draft/docs/workspaces/example.md"], tmp_path)
    d = json.loads(r.stdout)
    assert d["prompt_path"] == str(prompt)
    assert d["placement"] == "interferometer"


def test_unresolvable_family_exits_4(tmp_path):
    r = _run(["--json", "write some documentation please"], tmp_path)
    assert r.returncode == 4
    assert "cannot resolve" in r.stderr


def test_no_intent_exits_5(tmp_path):
    r = _run([], tmp_path)
    assert r.returncode == 5


def test_survey_inventories_and_diffs_against_sibling(tmp_path):
    _fabricate_workspace(
        tmp_path, "autolens_workspace", {"imaging": 3, "interferometer": 2, "guides": 1}
    )
    _fabricate_workspace(tmp_path, "autoreduce_workspace", {"imaging": 1})
    r = _run(
        ["survey", "autoreduce_workspace", "--against", "autolens_workspace", "--json"],
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    s = json.loads(r.stdout)
    assert s["repo"] == "autoreduce_workspace"
    assert s["total_scripts"] == 1
    assert s["missing_packages"] == ["guides", "interferometer"]
    assert s["extra_packages"] == []
    assert s["shared_packages"]["imaging"] == {"repo": 1, "sibling": 3}


def test_survey_missing_repo_exits_4(tmp_path):
    r = _run(["survey", "autoreduce_workspace"], tmp_path)
    assert r.returncode == 4


def test_never_writes(tmp_path):
    _fabricate_workspace(tmp_path, "autolens_workspace", {"imaging": 1})
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    _run(["an imaging example for autolens_workspace"], tmp_path)
    _run(["survey", "autolens_workspace"], tmp_path)
    after = sorted(str(p) for p in tmp_path.rglob("*"))
    assert before == after
