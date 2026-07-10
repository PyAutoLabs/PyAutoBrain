"""Seam tests for the 4b config extraction (PyAutoBrain#75): every constant
table that moved to config/policy.yaml or now derives from the body map gets
one test pinning the seam, so a broken policy file or body map fails loudly
here rather than mis-routing an agent."""

import subprocess
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN_HOME / "agents" / "faculties" / "sizing"))

import _sizing  # noqa: E402


def test_policy_file_parses_with_all_blocks():
    pol = _sizing.policy()
    for key in ("repo_aliases", "sizing_categories", "memory_wikis",
                "target_signals", "target_default_wiki", "test_witness",
                "release", "extra_workspace_targets", "extra_organism_targets"):
        assert key in pol, key


def test_library_set_derives_from_body_map():
    cats = _sizing._body_map_categories()
    body_libraries = {n.lower() for n, c in cats.items() if c == "library"}
    assert body_libraries <= _sizing.LIBRARY_REPOS
    # the package form of every library resolves too
    assert "autofit" in _sizing.LIBRARY_REPOS
    assert "autoreduce" in _sizing.LIBRARY_REPOS  # derived, not hand-listed


def test_workspace_and_organism_sets():
    assert "autolens_workspace" in _sizing.WORKSPACE_REPOS
    assert "howtolens" in _sizing.WORKSPACE_REPOS
    assert "workspaces" in _sizing.WORKSPACE_REPOS  # policy extra
    assert "pyautobrain" in _sizing.ORGANISM_REPOS
    assert "autobuild" in _sizing.ORGANISM_REPOS    # policy extra
    # the three sets stay disjoint — a repo must classify one way
    assert not (_sizing.LIBRARY_REPOS & _sizing.WORKSPACE_REPOS)
    assert not (_sizing.LIBRARY_REPOS & _sizing.ORGANISM_REPOS)


def test_aliases_normalise_known_mentions():
    assert _sizing.normalise_repo("@aa.decorators.to_vector_yx") == "autoarray"
    assert _sizing.normalise_repo("PyAutoFit") == "autofit"


def test_memory_wikis_route_science_vocabulary():
    wikis = _sizing.MEMORY_WIKIS
    assert "lens" in wikis["lensing_wiki"]
    assert "sampler" in wikis["methods_wiki"]
    assert _sizing.SCIENCE_KEYWORDS  # derived, non-empty


def test_intake_target_signals_load():
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "intake"))
    import _intake

    assert "lens" in _intake.TARGET_SIGNALS["autolens"]
    assert "sampler" in _intake.TARGET_SIGNALS["autofit"]


def test_feature_default_wiki_loads():
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "feature"))
    import _feature

    assert _feature.TARGET_DEFAULT_WIKI["autolens"] == "lensing_wiki"


def test_refactor_test_witness_loads():
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "refactor"))
    import _refactor

    assert _refactor.TEST_WITNESS["autofit"] == "PyAutoFit/test_autofit"


def test_release_policy_loads():
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "release"))
    import activity_gate

    assert "PyAutoLens" in activity_gate.RELEASE_RELEVANT_REPOS
    assert "PyAutoMind" not in activity_gate.RELEASE_RELEVANT_REPOS


def test_nightly_tag_repo_resolves():
    here = BRAIN_HOME / "agents" / "conductors" / "release"
    out = subprocess.run(
        [sys.executable, "-c",
         "import yaml, pathlib; print(yaml.safe_load((pathlib.Path("
         f"'{here}').parents[2] / 'config' / 'policy.yaml').read_text())"
         "['release']['tag_repo'])"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0 and "/" in out.stdout
