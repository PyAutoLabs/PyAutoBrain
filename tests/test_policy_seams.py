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
    # Derived since PyAutoBrain#287 — every spelling of every body-map repo is
    # registered, so this no longer needs an `extra_organism_targets` literal.
    assert "autohands" in _sizing.ORGANISM_REPOS
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
    "PyAutoCortex": "born empty 2026-09-01 (cortex-birth phase 0, PyAutoMind#377); "
                    "phase 1 adds tests/ and the test_witness row",
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


# --- the alias/known-target seam (PyAutoBrain#287) ---------------------------
#
# The three guards below close the defect class the witness-map guards above
# only closed one instance of. `repo_aliases` was HAND-MAINTAINED while the
# known-target set is DERIVED from the body map, so the two drifted silently and
# the gap surfaced only as a wrong-but-plausible conductor message. Seven repos
# hit it in sequence — one at #267, two more at #269, then the organs and a
# project repo at #287. These pin the *class*: a repo may not split across two
# keys, an alias may not point at a key nothing is filed under, and the body
# map's `package:` must agree with the witness map.
#
# Every repo name here is derived from the body map, never typed: the tenant
# firewall allows only three literals in this file, and a guard that hardcoded
# names would stop holding for an adopting fork the moment its body map differed.


def _sizing_category_repos():
    """Body-map repos the sizing sets actually register, by name -> canonical key."""
    specs = _sizing._body_map_specs()
    grouping = _sizing.policy()["sizing_categories"]
    registered = {c for kinds in grouping.values() for c in kinds}
    unreachable = _sizing.unreachable_repos()
    return {
        name: _sizing.canonical_key(name, spec)
        for name, spec in specs.items()
        if spec["category"] in registered and name not in unreachable
    }


def test_no_repo_splits_across_two_keys():
    """Every spelling of a registered repo must reach ONE key, and that key must
    itself be a known target.

    This is the #287 defect stated directly. `_target_sets` registers both
    `pyautobrain` and `autobrain` as known targets, but only the prefixed one was
    filed under, so `@autobrain` resolved to a live target with no witness row:
    `pyauto-brain refactor` advised "strengthen tests first" for the best-tested
    repo in the organism, and `pyauto-brain intake` filed `Target: autobrain`, a
    folder that does not exist.
    """
    split = {}
    for name, canonical in _sizing_category_repos().items():
        keys = {s: _sizing.normalise_repo(s) for s in _sizing.spellings_of(name)}
        if set(keys.values()) != {canonical}:
            split[name] = keys
        elif canonical not in _sizing.KNOWN_REPOS:
            split[name] = f"canonical key {canonical!r} is not a known target"
    assert not split, (
        "repos whose spellings do not all reach one known-target key — the "
        f"spelling a prompt happens to use decides whether routing works: {split}"
    )


def test_no_alias_points_at_a_key_nothing_is_filed_under():
    """An alias whose VALUE is not a canonical key is a dead end.

    That is what `pyautoconf: autoconf` had become (#267): both spellings of one
    repo resolved, to two keys, neither of which was anything. Checking values
    (not just keys, as the witness guards do) catches the next one at the source
    map rather than in whichever consumer notices first.
    """
    canonical = set(_sizing_category_repos().values())
    extras = set(_sizing.policy()["extra_workspace_targets"])
    extras |= set(_sizing.policy()["extra_organism_targets"])
    dead = {
        alias: target
        for alias, target in _sizing.REPO_ALIASES.items()
        if target not in canonical
        and _sizing.normalise_repo(target) not in canonical
        and target not in extras
    }
    assert not dead, (
        "repo_aliases rows pointing at a key no body-map repo is filed under "
        f"— routing through them reaches nothing: {dead}"
    )


def test_body_map_package_agrees_with_the_witness_map():
    """The body map's `package:` and the witness map must corroborate each other.

    A `<Repo>/test_<pkg>` witness row names the package that repo ships; so does
    `repos.yaml`. Two independent statements of one fact are only worth having if
    something compares them — #269 verified every witness row by reading each
    repo's own tree, and this pins the body map to that verified evidence rather
    than to a second, unchecked transcription.

    ALL-OR-NOTHING, not lockstep. A body map that declares NO package anywhere
    simply predates the field (this repo's CI pins the sibling Mind checkout to
    `main`, and an adopting fork may never adopt it) — absence is an older map,
    not a contradiction, so there is nothing to compare and the guard stands
    down. Once the map declares even one, every witness row that names a package
    must have one: a PARTIALLY declared map is the drift this exists to catch,
    and is what a new library added without its `package:` would look like.
    """
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "refactor"))
    import _refactor

    specs = _sizing._body_map_specs()
    if not any("package" in spec for spec in specs.values()):
        return  # a body map from before the field existed — nothing to corroborate

    disagree = {}
    for key, witness in _refactor.TEST_WITNESS.items():
        repo, _, test_dir = witness.partition("/")
        declared = specs.get(repo, {}).get("package")
        if test_dir.startswith("test_"):
            witnessed = test_dir[len("test_"):]
            if declared != witnessed:
                disagree[repo] = f"repos.yaml package={declared!r}, witness names {witnessed!r}"
        elif declared is not None:
            disagree[repo] = (
                f"repos.yaml declares package={declared!r} but the witness row is "
                f"{witness!r} — a plain tests/ dir names no package"
            )
    assert not disagree, (
        "body map and witness map disagree about which package a repo ships: "
        f"{disagree}"
    )


def test_unreachable_repos_are_excluded_rather_than_half_registered():
    """The acceptance criterion's other branch: deliberately NOT registered.

    ``normalise_repo`` truncates at the first ``.``/``/``, so a repo whose name
    carries one can never be reached by an @-mention. The tempting fix — alias
    the truncated head — is worse than the gap: where that head is the ORG's own
    name, every org-qualified ``@<org>/<repo>`` mention would resolve to that one
    repo. Excluding such a repo is therefore the deliberate choice, and this pins
    BOTH halves of it: it is out of the known targets, and the org-qualified path
    it would have hijacked still does not resolve to it.
    """
    for name in _sizing.unreachable_repos():
        assert name not in _sizing.KNOWN_REPOS, name
        head = name.split(".")[0].split("/")[0]
        assert _sizing.normalise_repo(head) not in _sizing.KNOWN_REPOS, (
            f"the truncated head of {name!r} resolves to a known target — an "
            "org-qualified mention would be hijacked by it"
        )


def test_canonical_keys_survive_a_body_map_without_package():
    """The Brain half must stand alone against a Mind that predates `package:`.

    This repo's CI checks the sibling Mind out at `main`, and an adopting fork's
    body map may never carry the field at all. `canonical_key` therefore falls
    back to the hand table, which still holds the library rows — so the keys come
    out identical either way. Without this the fix would be un-mergeable except
    in lockstep, and the fallback would be the kind of load-bearing path nothing
    exercises until it breaks.
    """
    specs = {
        name: {k: v for k, v in spec.items() if k != "package"}
        for name, spec in _sizing._body_map_specs().items()
    }
    for name, stripped in specs.items():
        assert _sizing.canonical_key(name, stripped) == _sizing.canonical_key(name), (
            f"{name}: canonical key moves when `package:` is absent — the "
            "pre-package fallback in config/policy.yaml no longer covers it"
        )
