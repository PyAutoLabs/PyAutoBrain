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
    assert "autohands" in _sizing.ORGANISM_REPOS    # policy extra
    # the three sets stay disjoint — a repo must classify one way
    assert not (_sizing.LIBRARY_REPOS & _sizing.WORKSPACE_REPOS)
    assert not (_sizing.LIBRARY_REPOS & _sizing.ORGANISM_REPOS)


def test_aliases_normalise_known_mentions():
    assert _sizing.normalise_repo("@aa.decorators.to_vector_yx") == "autoarray"
    assert _sizing.normalise_repo("PyAutoFit") == "autofit"


def test_nerves_spellings_share_one_canonical_key():
    # PyAutoBrain#267: before the rename cleanup `@PyAutoConf` normalised to
    # `autoconf` and `@PyAutoNerves` to `pyautonerves` — two dead keys for one
    # repo, neither of them in the body map. All four spellings must land on the
    # single key the policy maps are written against.
    for mention in ("PyAutoNerves", "@autonerves", "PyAutoConf", "@autoconf"):
        assert _sizing.normalise_repo(mention) == "autonerves", mention
    # ...and that key must be a repo the organism actually knows about.
    assert "autonerves" in _sizing.KNOWN_REPOS


def test_memory_wikis_route_science_vocabulary():
    wikis = _sizing.MEMORY_WIKIS
    # Keys are the wiki/<domain>/ names (the *_wiki root layout is retired).
    assert "lens" in wikis["lensing"]
    assert "sampler" in wikis["methods"]
    assert not any(k.endswith("_wiki") for k in wikis)
    assert _sizing.SCIENCE_KEYWORDS  # derived, non-empty


def test_intake_target_signals_load():
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "intake"))
    import _intake

    assert "lens" in _intake.TARGET_SIGNALS["autolens"]
    assert "sampler" in _intake.TARGET_SIGNALS["autofit"]


def test_feature_default_wiki_loads():
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "feature"))
    import _feature

    assert _feature.TARGET_DEFAULT_WIKI["autolens"] == "lensing"
    # The Nerves repo resolves under every spelling, via the alias table rather
    # than duplicate wiki rows (PyAutoBrain#267).
    assert _feature.TARGET_DEFAULT_WIKI[_sizing.normalise_repo("PyAutoConf")] == "methods"
    assert _feature.TARGET_DEFAULT_WIKI["autonerves"] == "methods"


def test_refactor_test_witness_loads():
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "refactor"))
    import _refactor

    assert _refactor.TEST_WITNESS["autofit"] == "PyAutoFit/test_autofit"
    # PyAutoBrain#267: the Nerves suite is real (test_autonerves, 157 tests), so
    # a refactor touching it must not be reported `[unwitnessed: pyautonerves]`.
    assert _refactor.TEST_WITNESS["autonerves"] == "PyAutoNerves/test_autonerves"
    for mention in ("PyAutoNerves", "@autonerves", "PyAutoConf"):
        assert _sizing.normalise_repo(mention) in _refactor.TEST_WITNESS, mention


def test_release_policy_loads():
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "release"))
    import activity_gate

    assert "PyAutoLens" in activity_gate.RELEASE_RELEVANT_REPOS
    assert "PyAutoMind" not in activity_gate.RELEASE_RELEVANT_REPOS


def test_release_relevant_repos_all_exist_in_the_body_map():
    """The drift guard PyAutoBrain#267 was missing.

    ``nightly.sh`` fetches ``repos/<org>/$repo/commits`` for every name in
    this list verbatim. A repo renamed in the body map but not here leaves the
    gate polling a name that only a GitHub rename redirect could answer — which
    is how ``PyAutoConf`` survived the Nerves rename. Pin the set to identity.
    """
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "release"))
    import activity_gate

    known = set(_sizing._body_map_categories())
    unknown = [r for r in activity_gate.RELEASE_RELEVANT_REPOS if r not in known]
    assert not unknown, f"not in PyAutoMind/repos.yaml: {unknown}"


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
