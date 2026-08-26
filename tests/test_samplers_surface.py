"""Contract tests for the SamplerSurface's findings-maturation-lane tiers.

Hermetic: every test fabricates a temp checkout and drives ``_samplers.py``
directly with explicit ``--`` paths, so nothing depends on which sibling repos
happen to be cloned. The faculty is read-only — asserted in test_never_writes —
and these tests name no repositories (tenant firewall), taking tier labels and
surface names from the module's own constants instead.
"""

import json
import subprocess
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
FACULTY = BRAIN_HOME / "agents" / "faculties" / "samplers"
sys.path.insert(0, str(FACULTY))

import _samplers  # noqa: E402


def _digest(*args):
    result = subprocess.run(
        [sys.executable, str(FACULTY / "_samplers.py"), "--json", *args],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _make_experiment(root: Path) -> Path:
    """One checkout with two probes, one private helper (must not be listed),
    a findings doc with a verdict heading, and one with no heading at all."""
    minimal = root / "searches_minimal"
    minimal.mkdir(parents=True)
    (minimal / "alpha_probe.py").write_text("# probe\n")
    (minimal / "beta_probe.py").write_text("# probe\n")
    (minimal / "_helper.py").write_text("# shared helper, not a probe\n")
    (minimal / "alpha_findings.md").write_text(
        "# Does alpha work on the ringed mesh? YES — once damping is handled.\n"
        "\nbody\n"
    )
    (minimal / "headless_findings.md").write_text("no heading here\n")
    return root


def _cell(root: Path, dataset_dir, sampler, model_type, declared=None):
    """Write a leaf at scripts/<dataset_dir>/searches/<sampler>/<model>.py.

    ``declared`` overrides the dataset_class the leaf *declares*, so a fixture
    can reproduce the live divergence between path and declaration.
    """
    leaf = root / "scripts" / dataset_dir / "searches" / sampler
    leaf.mkdir(parents=True, exist_ok=True)
    (leaf / f"{model_type}.py").write_text(
        "from searches._runner import run_search\n\n"
        "run_search(\n"
        f'    sampler="{sampler}",\n'
        f'    dataset_class="{declared or dataset_dir}",\n'
        f'    model_type="{model_type}",\n'
        '    default_instrument="hst",\n'
        ")\n"
    )


def _make_mature(root: Path) -> Path:
    _cell(root, "imaging", "nautilus", "mge")
    # the live divergence: a leaf under one directory declaring another class
    _cell(root, "cluster", "nautilus", "mge", declared="group")
    # framework helpers under misc/ are not cells
    misc = root / "scripts" / "misc" / "searches"
    misc.mkdir(parents=True)
    (misc / "_runner.py").write_text("def run_search(**kw): ...\n")
    (misc / "sweep.py").write_text("# driver, not a cell\n")
    # a private helper inside a real sampler dir is not a cell either
    (root / "scripts" / "imaging" / "searches" / "nautilus" / "_shared.py").write_text("x = 1\n")
    return root


def test_experiment_tier_lists_probes_and_findings_verdicts(tmp_path):
    d = _digest("--lens-developer", str(_make_experiment(tmp_path)))
    assert _samplers.SURFACE_LENS_DEVELOPER in d["surfaces_present"]
    assert d["tiers"][_samplers.TIER_LENS_PROBES] == ["alpha_probe", "beta_probe"]
    findings = d["tiers"][_samplers.TIER_LENS_FINDINGS]
    assert findings[0].startswith("alpha_findings — Does alpha work")
    # a doc with no heading degrades to its bare name rather than an empty row
    assert findings[1] == "headless_findings"


def test_mature_tier_reads_the_declaration_not_the_path(tmp_path):
    d = _digest("--profiling", str(_make_mature(tmp_path)))
    assert _samplers.SURFACE_PROFILING in d["surfaces_present"]
    cells = d["tiers"][_samplers.TIER_LENS_MATURE]
    # the cluster/ leaf declares `group`, and the declaration wins — parsing the
    # path instead would mislabel it and silently collide with a real cell
    assert cells == ["nautilus/group/mge", "nautilus/imaging/mge"]


def test_mature_tier_falls_back_to_path_when_undeclared(tmp_path):
    root = _make_mature(tmp_path)
    undeclared = root / "scripts" / "interferometer" / "searches" / "emcee"
    undeclared.mkdir(parents=True)
    (undeclared / "delaunay.py").write_text("# no run_search call at all\n")
    cells = _digest("--profiling", str(root))["tiers"][_samplers.TIER_LENS_MATURE]
    assert "emcee/interferometer/delaunay" in cells


def test_lane_tiers_add_no_gaps(tmp_path):
    """Inventory only — `gaps` stays keyed on the autofit promotion tiers."""
    root = _make_mature(_make_experiment(tmp_path))
    d = _digest("--lens-developer", str(root), "--profiling", str(root))
    assert d["gaps"] == []


def test_absent_lane_checkouts_are_not_fatal(tmp_path):
    result = subprocess.run(
        [sys.executable, str(FACULTY / "_samplers.py"), "--json",
         "--lens-developer", str(tmp_path / "nope"),
         "--profiling", str(tmp_path / "also-nope")],
        capture_output=True, text=True,
    )
    assert result.returncode == 4  # no surface, reported cleanly
    assert "Traceback" not in result.stderr


def test_never_writes(tmp_path):
    root = _make_mature(_make_experiment(tmp_path))
    before = sorted(str(p) for p in root.rglob("*"))
    _digest("--lens-developer", str(root), "--profiling", str(root))
    assert sorted(str(p) for p in root.rglob("*")) == before
