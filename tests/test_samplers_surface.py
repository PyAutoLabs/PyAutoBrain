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
    d = _digest("--inference", str(_make_mature(tmp_path)))
    assert _samplers.SURFACE_INFERENCE in d["surfaces_present"]
    cells = d["tiers"][_samplers.TIER_LENS_MATURE]
    # the cluster/ leaf declares `group`, and the declaration wins — parsing the
    # path instead would mislabel it and silently collide with a real cell
    assert cells == ["nautilus/group/mge", "nautilus/imaging/mge"]


def test_mature_tier_falls_back_to_path_when_undeclared(tmp_path):
    root = _make_mature(tmp_path)
    undeclared = root / "scripts" / "interferometer" / "searches" / "emcee"
    undeclared.mkdir(parents=True)
    (undeclared / "delaunay.py").write_text("# no run_search call at all\n")
    cells = _digest("--inference", str(root))["tiers"][_samplers.TIER_LENS_MATURE]
    assert "emcee/interferometer/delaunay" in cells


def test_lane_tiers_add_no_gaps(tmp_path):
    """Inventory only — `gaps` stays keyed on the autofit promotion tiers."""
    root = _make_mature(_make_experiment(tmp_path))
    d = _digest("--lens-developer", str(root), "--inference", str(root))
    assert d["gaps"] == []


def test_absent_lane_checkouts_are_not_fatal(tmp_path):
    result = subprocess.run(
        [sys.executable, str(FACULTY / "_samplers.py"), "--json",
         "--lens-developer", str(tmp_path / "nope"),
         "--inference", str(tmp_path / "also-nope")],
        capture_output=True, text=True,
    )
    assert result.returncode == 4  # no surface, reported cleanly
    assert "Traceback" not in result.stderr


def test_never_writes(tmp_path):
    root = _make_mature(_make_experiment(tmp_path))
    before = sorted(str(p) for p in root.rglob("*"))
    _digest("--lens-developer", str(root), "--inference", str(root))
    assert sorted(str(p) for p in root.rglob("*")) == before


def test_empty_mature_surface_yields_no_cells(tmp_path):
    """The mature tier is empty until its cells are built — a surface with zero
    rows, not a crash and not a missing surface."""
    empty = tmp_path / "successor"
    empty.mkdir()
    d = _digest("--inference", str(empty))
    assert _samplers.SURFACE_INFERENCE in d["surfaces_present"]
    assert d["tiers"][_samplers.TIER_LENS_MATURE] == []
    # and again with a scripts/ tree that holds no searches cells at all
    (empty / "scripts" / "imaging" / "likelihood_runtime").mkdir(parents=True)
    (empty / "scripts" / "imaging" / "likelihood_runtime" / "mge.py").write_text("x = 1\n")
    d = _digest("--inference", str(empty))
    assert d["tiers"][_samplers.TIER_LENS_MATURE] == []


# --------------------------------------------------------------------------
# The tier-gap rule, keyed on exported class names
# --------------------------------------------------------------------------

_AUTOFIT_INIT = '''\
from .non_linear.search.abstract_search import NonLinearSearch
from .non_linear.search.mcmc.auto_correlations import AutoCorrelationsSettings
from .non_linear.search.mcmc.blackjax.nuts.search import BlackJAXNUTS
from .non_linear.search.nest.nautilus.search import Nautilus
from .non_linear.search.nest.dynesty.search.static import DynestyStatic
from .non_linear.search.mle.drawer.search import Drawer
from .non_linear.search.mle.bfgs.search import BFGS
from .non_linear.search.mle.bfgs.search import LBFGS
from .non_linear.search.mle.multi_start_gradient.search import MultiStartAdam
from .non_linear.search.mle.multi_start_gradient.search import MultiStartLion
from .non_linear.search.mle.multi_start_gradient.convergence import (
    ConvergenceSettings,
)

_LAZY_ATTRS = {
    "NSS": ("autofit.non_linear.search.nest.nss.search", "NSS"),
    "SMC": ("autofit.non_linear.search.mcmc.blackjax.smc.search", "SMC"),
    "Aggregator": ("autofit.database.aggregator", "Aggregator"),
    "db": ("autofit.database", None),
}
'''


def _make_fit_family(root: Path) -> dict:
    """Library + developer + test checkouts reproducing every live trap: one
    module dir holding several classes (bfgs, blackjax, multi_start_gradient),
    lazily exported searches, an archived search that was re-mainlined, and
    prototype stems with stacked variant suffixes."""
    autofit = root / "library"
    (autofit / "autofit").mkdir(parents=True)
    (autofit / "autofit" / "__init__.py").write_text(_AUTOFIT_INIT)
    developer = root / "developer"
    for name in ("nss", "pyswarms"):
        (developer / "searches" / name).mkdir(parents=True)
    minimal = developer / "searches_minimal"
    minimal.mkdir(parents=True)
    for stem in ("nautilus_simple", "nautilus_jax_mlp", "nautilus_profile",
                 "nautilus_sweep", "dynesty_simple", "nuts_jax",
                 "cmaes_simple"):
        (minimal / f"{stem}.py").write_text("# prototype\n")
    test = root / "test"
    searches = test / "scripts" / "searches"
    searches.mkdir(parents=True)
    for stem in ("BlackJAXNUTS", "Nautilus_jax", "DynestyStatic", "LBFGS",
                 "MultiStartAdam", "MultiStartResurrect", "NSS", "__init__"):
        (searches / f"{stem}.py").write_text("# integration\n")
    return {"autofit": autofit, "developer": developer, "test": test}


def test_promoted_tier_is_keyed_on_exported_classes(tmp_path):
    autofit = _make_fit_family(tmp_path)["autofit"]
    assert _samplers.exported_searches(autofit) == {
        "BlackJAXNUTS": "mcmc/blackjax", "SMC": "mcmc/blackjax",
        "Nautilus": "nest/nautilus", "DynestyStatic": "nest/dynesty",
        "NSS": "nest/nss", "Drawer": "mle/drawer", "BFGS": "mle/bfgs",
        "LBFGS": "mle/bfgs", "MultiStartAdam": "mle/multi_start_gradient",
        "MultiStartLion": "mle/multi_start_gradient",
    }


def test_family_of_strips_stacked_variant_suffixes():
    assert _samplers.family_of("nautilus_jax_mlp") == "nautilus"
    assert _samplers.family_of("nautilus_profile") == "nautilus"
    assert _samplers.family_of("nautilus_sweep") == "nautilus"
    assert _samplers.family_of("Nautilus_jax") == "nautilus"
    assert _samplers.family_of("MultiStartAdam") == "multistartadam"


def test_gap_rule_reports_only_true_gaps(tmp_path):
    paths = _make_fit_family(tmp_path)
    d = _digest("--autofit", str(paths["autofit"]),
                "--developer", str(paths["developer"]),
                "--test", str(paths["test"]))
    gaps = d["gaps"]
    missing = sorted(g.split("'")[1] for g in gaps
                     if "integration script" in g)
    # SMC shares mcmc/blackjax with BlackJAXNUTS and BFGS shares mle/bfgs with
    # LBFGS — a directory-keyed rule hid both. MultiStartAdam.py covers its
    # class, so the multi_start_gradient directory is no longer a false
    # positive; MultiStartLion, with no script, is a true gap.
    assert missing == ["BFGS", "Drawer", "MultiStartLion", "SMC"]
    candidates = sorted(g.split("'")[1] for g in gaps
                        if "promotion candidate" in g)
    # nautilus variants collapse onto the exported class; only the genuinely
    # unpromoted prototype remains
    assert candidates == ["cmaes"]
    # NSS was re-mainlined, so its archive copy is not a second tier entry
    assert d["tiers"]["archive (searches)"] == ["pyswarms"]
    assert sum("NSS" in g for g in gaps) == 0


# --------------------------------------------------------------------------
# The search manifest as the catalogue's source of truth
# --------------------------------------------------------------------------


def _manifest_file(root: Path, searches) -> Path:
    """A `search-manifest@1` dump; `searches` is [(name, module, anchor)]."""
    doc = {
        "schema": "search-manifest@1",
        "autofit_version": "9.9.9",
        "families": {},
        "capability_attributes": [],
        "searches": [
            {"name": name, "class_path": f"autofit.{module}.{name}",
             "family": module.split(".")[2], "integration_test": anchor}
            for name, module, anchor in searches
        ],
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(doc))
    return path


def test_manifest_keys_promoted_and_gaps(tmp_path):
    paths = _make_fit_family(tmp_path)
    manifest = _manifest_file(tmp_path, [
        ("Nautilus", "non_linear.search.nest.nautilus.search",
         "ws_test:scripts/searches/Nautilus_jax.py"),
        ("LBFGS", "non_linear.search.mle.bfgs.search",
         "ws_test:scripts/searches/LBFGS.py"),
        ("Fresh", "non_linear.search.mle.fresh.search",
         "ws_test:scripts/searches/Fresh.py"),
    ])
    d = _digest("--autofit", str(paths["autofit"]),
                "--developer", str(paths["developer"]),
                "--test", str(paths["test"]),
                "--manifest", str(manifest))
    assert d["manifest"]["autofit_version"] == "9.9.9"
    # the manifest, not the AST of __init__.py, is the promoted tier
    assert d["tiers"]["promoted (autofit exports)"] == [
        "mle/bfgs/LBFGS", "mle/fresh/Fresh", "nest/nautilus/Nautilus"]
    missing = sorted(g.split("'")[1] for g in d["gaps"]
                     if "integration script" in g)
    # coverage is the manifest anchor resolving: Nautilus is covered by the
    # file its anchor names, Fresh's anchored file does not exist
    assert missing == ["Fresh"]


def test_unreadable_manifest_falls_back_to_the_ast(tmp_path):
    paths = _make_fit_family(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "search-manifest@0", "searches": []}))
    d = _digest("--autofit", str(paths["autofit"]), "--manifest", str(bad))
    # the explicit file's failure is named, not hidden behind "not importable"
    assert d["manifest"]["source"].startswith("AST fallback (--manifest")
    assert "nest/nss/NSS" in d["tiers"]["promoted (autofit exports)"]


def test_manifest_file_alone_is_a_surface(tmp_path):
    manifest = _manifest_file(tmp_path, [
        ("Nautilus", "non_linear.search.nest.nautilus.search", None)])
    d = _digest("--manifest", str(manifest))
    assert "search manifest" in d["surfaces_present"]
    assert d["tiers"]["promoted (autofit exports)"] == ["nest/nautilus/Nautilus"]


def test_checkout_manifest_subprocess_path(tmp_path):
    """No --manifest: the manifest is printed by `python -m autofit` with the
    checkout first on PYTHONPATH, and a failing module degrades to the AST."""
    good = tmp_path / "good"
    (good / "autofit").mkdir(parents=True)
    (good / "autofit" / "__init__.py").write_text("")
    (good / "autofit" / "__main__.py").write_text(
        "import json\nprint(json.dumps({'schema': 'search-manifest@1', "
        "'autofit_version': '0.0.1', 'searches': [{'name': 'Zeta', "
        "'class_path': 'autofit.non_linear.search.mcmc.zeta.search.Zeta'}]}))\n")
    d = _digest("--autofit", str(good))
    assert d["tiers"]["promoted (autofit exports)"] == ["mcmc/zeta/Zeta"]
    assert d["manifest"]["source"].startswith("search manifest of the checkout")
    broken = tmp_path / "broken"
    (broken / "autofit").mkdir(parents=True)
    (broken / "autofit" / "__init__.py").write_text(_AUTOFIT_INIT)
    (broken / "autofit" / "__main__.py").write_text("raise SystemExit(3)\n")
    d = _digest("--autofit", str(broken))
    assert d["manifest"]["source"] == "AST fallback (autofit not importable)"


# --------------------------------------------------------------------------
# run_point_search leaves and the autofit inference surface
# --------------------------------------------------------------------------


def test_point_runner_leaf_declares_a_cell_outside_searches(tmp_path):
    root = _make_mature(tmp_path)
    leaf = root / "scripts" / "point_source" / "simple"
    leaf.mkdir(parents=True)
    (leaf / "baseline.py").write_text(
        "from searches._point_runner import run_point_search\n"
        "run_point_search(sampler=\"nautilus\", default_instrument=\"simple\")\n"
    )
    (leaf / "notes.py").write_text("# not a cell: no runner call, not searches-shaped\n")
    # a run_search helper with no model_type is not a cell (no stem default)...
    (leaf / "helper.py").write_text(
        "run_search(sampler=\"emcee\", dataset_class=\"imaging\")\n")
    # ...and a non-literal sampler is unreadable, never the runner default
    (leaf / "dynamic.py").write_text("run_point_search(sampler=SAMPLER)\n")
    cells = _digest("--inference", str(root))["tiers"][_samplers.TIER_LENS_MATURE]
    # dataset_class comes from the runner's default, model_type from the stem
    assert cells == ["nautilus/group/mge", "nautilus/imaging/mge",
                     "nautilus/point_source/baseline"]


def test_fit_inference_surface_lists_cells_and_catalogue(tmp_path):
    root = tmp_path / "fit_inference"
    _cell(root, "toy_blend", "emcee", "toy")
    (root / "catalogue").mkdir()
    (root / "catalogue" / "search_catalogue.json").write_text(json.dumps({
        "protocol_id": "toy@1", "ranking": "none",
        "manifest": {"autofit_version": "9.9.9"},
        "tasks": {
            "posterior": {"searches": {"Emcee": {"status": "measured"}}},
            "evidence": {"searches": {"NSS": {"status": "deferred"}}},
        },
    }))
    d = _digest("--fit-inference", str(root))
    assert _samplers.SURFACE_FIT_INFERENCE in d["surfaces_present"]
    assert d["tiers"][_samplers.TIER_FIT_MATURE] == ["emcee/toy_blend/toy"]
    assert d["tiers"][_samplers.TIER_FIT_CATALOGUE] == [
        "evidence/NSS: deferred", "posterior/Emcee: measured"]
    assert d["fit_inference_catalogue"]["protocol_id"] == "toy@1"
    assert d["gaps"] == []  # inventory only


def test_fit_inference_without_catalogue_is_not_fatal(tmp_path):
    root = tmp_path / "fit_inference"
    root.mkdir()
    d = _digest("--fit-inference", str(root))
    assert d["tiers"][_samplers.TIER_FIT_CATALOGUE] == []
    assert "fit_inference_catalogue" not in d


# --------------------------------------------------------------------------
# The mirrored lifecycle layout: scripts/<dataset_type>/<variant>/{samplers,validation}/
# --------------------------------------------------------------------------


def _make_lifecycle(root: Path) -> Path:
    """Two leaves under one likelihood: a sampler cell whose call names no
    RUNNERS entry (so its path is its identity) and a wall-time validation run."""
    samplers = root / "scripts" / "imaging" / "delaunay" / "samplers"
    validation = root / "scripts" / "imaging" / "delaunay" / "validation"
    samplers.mkdir(parents=True)
    validation.mkdir(parents=True)
    (samplers / "nautilus.py").write_text(
        "from experiments.run import main\n"
        "main(setup_family=(\"imaging\", \"delaunay\"), sampler=\"nautilus\")\n")
    (validation / "baseline_slam.py").write_text(
        "from slam._runner import run_slam\n"
        "run_slam(dataset_class=\"imaging\", default_instrument=\"hst\")\n")
    return root


def test_lifecycle_sampler_leaf_is_a_mature_cell(tmp_path):
    d = _digest("--inference", str(_make_lifecycle(tmp_path)))
    assert d["tiers"][_samplers.TIER_LENS_MATURE] == ["nautilus/imaging/delaunay"]


def test_lifecycle_validation_leaves_are_listed_apart(tmp_path):
    d = _digest("--inference", str(_make_lifecycle(tmp_path)))
    assert d["tiers"][_samplers.TIER_LENS_VALIDATION] == ["imaging/delaunay/baseline_slam"]
    # a validation leaf that happens to call a runner is still not a sampler cell
    leaf = tmp_path / "scripts" / "imaging" / "delaunay" / "validation" / "declared.py"
    leaf.write_text('run_search(sampler="emcee", dataset_class="imaging", model_type="x")\n')
    d = _digest("--inference", str(tmp_path))
    assert d["tiers"][_samplers.TIER_LENS_MATURE] == ["nautilus/imaging/delaunay"]


def test_lifecycle_sampler_directory_shape_and_old_shape_coexist(tmp_path):
    root = _make_mature(_make_lifecycle(tmp_path))
    nested = root / "scripts" / "interferometer" / "mge" / "samplers" / "emcee"
    nested.mkdir(parents=True)
    (nested / "seeded.py").write_text("# no runner call\n")
    cells = _digest("--inference", str(root))["tiers"][_samplers.TIER_LENS_MATURE]
    assert cells == ["emcee/interferometer/mge", "nautilus/group/mge",
                     "nautilus/imaging/delaunay", "nautilus/imaging/mge"]
