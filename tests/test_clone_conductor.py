"""Contract tests for the Clone (Mitosis) Agent's reference profiles.

Hermetic: exercises the pure classification logic (`reference_profile`,
`match_any`, the pattern sets) without git or the real checkouts. The point
under test is that the generic-vs-domain seam is *per reference* — the same
path lands on opposite sides for `autolens_assistant` (a domain assistant) and
`autofit_assistant` (the domain-agnostic base).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

CLONE = (
    Path(__file__).resolve().parents[1]
    / "agents" / "conductors" / "clone" / "_clone.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("_clone_under_test", CLONE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


clone = _load()


def _classify(path, profile):
    """Mirror partition()'s first-match GENERIC -> DOMAIN -> MIXED order."""
    for key in ("generic", "domain", "mixed"):
        if clone.match_any(path, profile[key]):
            return key
    return "unclassified"


def test_both_references_have_profiles():
    assert set(clone.REFERENCE_PROFILES) >= {"autolens_assistant", "autofit_assistant"}
    for profile in clone.REFERENCE_PROFILES.values():
        assert len(profile["markers"]) == 3
        assert clone.SEED_SECTION == "## Assistant-as-template"


def test_unknown_reference_fails_cleanly():
    with pytest.raises(SystemExit) as exc:
        clone.reference_profile("no_such_assistant")
    assert exc.value.code == 4


@pytest.mark.parametrize(
    "path,expected",
    [
        # generic framework kept verbatim
        ("AGENTS.md", "generic"),
        ("scripts/README.md", "generic"),
        # the domain-agnostic base keeps af_* inference skills as GENERIC
        ("skills/af_compose_model.md", "generic"),
        (".claude/skills/af_wrap_likelihood.md", "generic"),
        # ...and wiki/core teaches statistics here, so it too is GENERIC
        ("wiki/core/index.md", "generic"),
        ("wiki/core/concepts/priors.md", "generic"),
        # the literature wiki ships as a near-empty GENERIC scaffold here
        # (a domain reference ships a filled corpus, so there it is domain)
        ("wiki/literature/index.md", "generic"),
        ("wiki/literature/AGENTS.md", "generic"),
        # domain content the newborn regrows for its field
        ("dataset/gaussian_x1/data.json", "domain"),
        ("README.md", "domain"),
        ("hpc/batch_cpu/submit_fit", "domain"),
        # mixed: copied then adapted
        ("config/priors/model.yaml", "mixed"),
        ("llms.txt", "mixed"),
    ],
)
def test_autofit_profile_classification(path, expected):
    assert _classify(path, clone.REFERENCE_PROFILES["autofit_assistant"]) == expected


@pytest.mark.parametrize(
    "path,expected",
    [
        # The euclid mode is a survey-specific *lensing* register — its skills
        # and its own sub-wiki. A newborn grows whatever survey modes its own
        # domain has, if any.
        ("skills/euclid_model_lens.md", "domain"),
        (".claude/skills/euclid_hpc_runs.md", "domain"),
        ("wiki/euclid/index.md", "domain"),
        ("wiki/euclid/entities/vis.md", "domain"),
        ("wiki/euclid/bibliography/euclid.bib", "domain"),
        # This assistant's own JOSS paper; a newborn writes its own.
        ("paper/paper.md", "domain"),
        ("paper/.gitignore", "domain"),
        # Bundled science scripts are tied to a named lens...
        ("scripts/model_cosmos_web_ring.py", "domain"),
        ("scripts/prepare_cosmos_web_ring.py", "domain"),
        # ...but scripts/'s own docs are framework, not science.
        ("scripts/AGENTS.md", "generic"),
        # .mcp.json only wires `autoassistant.mcp` — generic tooling, so the
        # wiring carries no domain either and clones verbatim.
        (".mcp.json", "generic"),
    ],
)
def test_autolens_profile_classification(path, expected):
    assert _classify(path, clone.REFERENCE_PROFILES["autolens_assistant"]) == expected


def test_wiki_core_and_skills_flip_between_references():
    """The seam is reference-owned: wiki/core/ and the domain skills sit on
    opposite sides for the two references."""
    autofit = clone.REFERENCE_PROFILES["autofit_assistant"]
    autolens = clone.REFERENCE_PROFILES["autolens_assistant"]
    # wiki/core: generic (stats) under autofit, domain (lensing API) under autolens
    assert _classify("wiki/core/api/tracer.md", autofit) == "generic"
    assert _classify("wiki/core/api/tracer.md", autolens) == "domain"
    # wiki/literature: generic near-empty scaffold under autofit, shipped corpus
    # (domain) under autolens
    assert _classify("wiki/literature/index.md", autofit) == "generic"
    assert _classify("wiki/literature/index.md", autolens) == "domain"
    # the reference's own domain skills are domain under autolens
    assert _classify("skills/al_fit_imaging.md", autolens) == "domain"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
