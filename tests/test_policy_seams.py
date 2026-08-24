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


# Repos allowed to have no witness row, with the reason. An entry here is a
# statement that the repo has no test suite — not a licence to skip one.
WITNESS_EXEMPT = {
    "PyAutoGut": "no test suite (bin/ + docs only, verified at PyAutoBrain#269)",
}


def test_every_library_and_organ_is_witnessed():
    """PyAutoBrain#269: a tested repo missing from the map reads as untested.

    ``behaviour_preservation`` reports any repo absent from ``test_witness`` as
    ``unwitnessed`` and advises "strengthen tests first". For a repo that has a
    suite that advice is wrong, and it is wrong silently — which is how one
    library and five organs went unnoticed until the #267 rename work looked.
    Pin coverage to the body map so a new library or organ cannot be added
    without either a witness row or a reasoned exemption.
    """
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "refactor"))
    import _refactor

    cats = _sizing._body_map_categories()
    missing = [
        name for name, cat in cats.items()
        if cat in ("library", "organ")
        and name not in WITNESS_EXEMPT
        and _sizing.normalise_repo(name) not in _refactor.TEST_WITNESS
    ]
    assert not missing, (
        "library/organ repos with no test_witness row — add the row, or add the "
        f"repo to WITNESS_EXEMPT with its reason: {missing}"
    )


def test_witness_exemptions_are_still_real_repos():
    """An exemption for a repo that left the body map is stale, not a waiver."""
    cats = _sizing._body_map_categories()
    stale = [name for name in WITNESS_EXEMPT if name not in cats]
    assert not stale, f"WITNESS_EXEMPT names repos not in the body map: {stale}"


def test_every_witness_key_is_what_its_repo_normalises_to():
    """A row keyed on something the normaliser never produces is a dead row.

    That is exactly what ``autoconf: PyAutoConf/test_autoconf`` had become
    (PyAutoBrain#267): reachable only through a stale alias, pointing at a repo
    path that no longer existed, and invisible because nothing checked the key
    against the repo it names. Derive the expectation from the row's own value
    so this holds for any body map, not just ours.
    """
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "refactor"))
    import _refactor

    wrong = {
        key: witness
        for key, witness in _refactor.TEST_WITNESS.items()
        if _sizing.normalise_repo(witness.split("/")[0]) != key
    }
    assert not wrong, (
        "test_witness rows whose key is not what their repo normalises to — "
        f"the conductor can never look them up: {wrong}"
    )


def test_witness_repos_resolve_from_the_package_spelling_too():
    """Prompts name a library by its package, not by its repo.

    Where a witness row's repo ships a package — inferable from the row itself,
    since a ``<Repo>/test_<package>`` value names one and a ``<Repo>/tests``
    value does not — both spellings must reach the same key, or which one the
    prompt happened to use silently decides whether the witness resolves
    (PyAutoBrain#268, #269).
    """
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "refactor"))
    import _refactor

    split = {}
    for key, witness in _refactor.TEST_WITNESS.items():
        repo, _, test_dir = witness.partition("/")
        if not test_dir.startswith("test_"):
            continue  # organ suite in a plain `tests/` dir — no package spelling
        package = test_dir[len("test_"):]
        if _sizing.normalise_repo(package) != key:
            split[repo] = (package, _sizing.normalise_repo(package), key)
    assert not split, (
        "package spelling normalises to a different key than the repo spelling "
        f"— add a repo_aliases entry joining them: {split}"
    )
