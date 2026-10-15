#!/usr/bin/env python3
"""agents/faculties/samplers/_samplers.py — the SamplerSurface digest.

The **samplers faculty** is a read-only opinion sink: it inventories the
organism's non-linear-search machinery — the three script tiers (minimal
prototypes, the removed-sampler archive, the workspace_test integration
scripts) and the PyAutoFit search catalogue — read from the versioned search
manifest (`python -m autofit search-manifest --json`, schema
`search-manifest@1`) of the PyAutoFit checkout, with an AST parse of
`autofit/__init__.py` as the fallback when it cannot be imported — plus the latest minimal-tier
benchmark outputs, and flags tier gaps (prototyped but never promoted,
promoted but never integration-tested). It also inventories the **findings
maturation lane** (AGENTS.md "Judgment: the maturation lane"): the experiment
tier's probes and findings docs, and the mature tiers' (sampler x
dataset_class x model_type) cell matrices — the lens leaves and the autofit
toy-likelihood leaves, the latter with their search catalogue's verdict
cells. The consulting agent
reads the digest and reasons with AGENTS.md's judgment tables; this script
never writes, never runs a sampler, and never edits anything.

Exit codes: 0 digest · 4 no surface found · 5 usage.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

# Script basenames carry variant suffixes that are not part of the sampler's
# name: `nautilus_jax_mlp` is a Nautilus prototype, `Nautilus_jax` a Nautilus
# integration script. Stripped repeatedly from the right, so stacked variants
# (`_jax_mlp`) collapse to the family.
VARIANT_SUFFIXES = ("_simple", "_jax", "_jit", "_grad", "_mlp", "_profile",
                    "_sweep")
# A prototype stem that names a family rather than one exported class. Every
# other stem matches an exported class by case-insensitive equality.
PROTOTYPE_ALIASES = {
    "dynesty": ("DynestyStatic", "DynestyDynamic"),
    "nuts": ("BlackJAXNUTS",),
}


def family_of(name: str) -> str:
    """Lower-cased stem with every trailing variant suffix removed."""
    base = name.lower()
    while True:
        for suf in VARIANT_SUFFIXES:
            if base.endswith(suf) and len(base) > len(suf):
                base = base[: -len(suf)]
                break
        else:
            return base


def _py_stems(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.py")
                  if not p.stem.startswith("_"))


def tier_minimal(developer: Path) -> list[str]:
    return _py_stems(developer / "searches_minimal")


def tier_archive(developer: Path, promoted_classes=()) -> list[str]:
    """Removed-sampler archive directories, minus any that are promoted.

    A search can be archived and later re-mainlined; its archive copy is then
    superseded, and listing it here would count one search in two tiers.
    """
    root = developer / "searches"
    if not root.is_dir():
        return []
    live = {c.lower() for c in promoted_classes}
    return sorted(d.name for d in root.iterdir()
                  if d.is_dir() and not d.name.startswith(("_", "."))
                  and d.name.lower() not in live)


def tier_integration(test: Path) -> list[str]:
    return _py_stems(test / "scripts" / "searches")


_SEARCH_PKG = "non_linear.search."


def _search_location(module: str) -> str | None:
    """`<group>/<pkg>` for a concrete search module, else None.

    A concrete search lives at `non_linear.search.<group>.<pkg>[...].search[...]`
    (e.g. `mcmc.blackjax.nuts.search`, `nest.dynesty.search.static`). Helpers in
    the same tree (`abstract_search`, `mcmc.auto_correlations`,
    `mle.multi_start_gradient.convergence`) have no `search` segment below the
    group and are not searches.
    """
    module = module.removeprefix("autofit.")
    if not module.startswith(_SEARCH_PKG):
        return None
    parts = module[len(_SEARCH_PKG):].split(".")
    if len(parts) < 3 or "search" not in parts[2:]:
        return None
    return f"{parts[0]}/{parts[1]}"


def exported_searches(autofit: Path) -> dict[str, str]:
    """{class name: `<group>/<pkg>`} for every search `autofit` exports.

    Parsed (never imported) from `autofit/__init__.py`: the eager
    `from .non_linear.search... import X` lines plus the `_LAZY_ATTRS` table,
    which is how optional-dependency searches (NSS, SMC) are exported. Keyed on
    the exported class, not the module directory, because one directory can
    hold several searches (`mle/bfgs`: BFGS + LBFGS; `mcmc/blackjax`:
    BlackJAXNUTS + SMC; `mle/multi_start_gradient`: four MultiStart*).
    """
    init = autofit / "autofit" / "__init__.py"
    if not init.is_file():
        return {}
    try:
        tree = ast.parse(init.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return {}
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            loc = _search_location(node.module)
            if loc:
                for alias in node.names:
                    out[alias.asname or alias.name] = loc
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if "_LAZY_ATTRS" in targets and isinstance(node.value, ast.Dict):
            for key, val in zip(node.value.keys, node.value.values):
                if not (isinstance(key, ast.Constant)
                        and isinstance(val, ast.Tuple) and val.elts
                        and isinstance(val.elts[0], ast.Constant)
                        and isinstance(val.elts[0].value, str)):
                    continue
                loc = _search_location(val.elts[0].value)
                if loc:
                    out[key.value] = loc
    return out


def tier_promoted(autofit: Path) -> list[str]:
    """Exported search classes as `<group>/<pkg>/<Class>` (AST fallback)."""
    return sorted(f"{loc}/{cls}"
                  for cls, loc in exported_searches(autofit).items())


MANIFEST_SCHEMA = "search-manifest@1"


def load_manifest(autofit: Path | None = None,
                  manifest_file: Path | None = None) -> dict | None:
    """The search manifest, or None when it cannot be had.

    `manifest_file` reads a saved `--json` dump. Otherwise the manifest is
    printed by `python -m autofit search-manifest --json` with the `autofit`
    checkout first on PYTHONPATH — the registry of the very checkout this
    digest inventories. Any failure (no checkout, the science stack not
    importable, an older schema) returns None and the caller falls back to the
    AST parse; the faculty never fails for want of a manifest.
    """
    try:
        if manifest_file:
            text = Path(manifest_file).read_text(encoding="utf-8")
        else:
            if not (autofit and (autofit / "autofit" / "__init__.py").is_file()):
                return None
            env = dict(os.environ)
            env["PYTHONPATH"] = str(autofit.resolve()) + (
                os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            proc = subprocess.run(
                [sys.executable, "-m", "autofit", "search-manifest", "--json"],
                capture_output=True, text=True, env=env, timeout=60)
            if proc.returncode != 0:
                return None
            text = proc.stdout
        manifest = json.loads(text)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        return None
    return manifest


def manifest_promoted(manifest: dict) -> list[str]:
    """Manifest searches as `<group>/<pkg>/<Name>` — the same row shape as the
    AST tier, so the two sources are interchangeable downstream."""
    rows = []
    for s in manifest.get("searches", []):
        module = s.get("class_path", "").rpartition(".")[0]
        loc = _search_location(module) or s.get("family", "?")
        rows.append(f"{loc}/{s['name']}")
    return sorted(rows)


def manifest_integration(manifest: dict, test: Path | None) -> dict[str, bool]:
    """{search name: does its manifest `integration_test` anchor exist}.

    The anchor is `<repo>:<path>`; the path is resolved against the
    integration-test checkout. A search with no anchor maps to False.
    """
    out = {}
    for s in manifest.get("searches", []):
        anchor = s.get("integration_test") or ""
        path = anchor.partition(":")[2].partition("#")[0]
        out[s["name"]] = bool(path and test and (test / path).is_file())
    return out


# --------------------------------------------------------------------------
# The findings maturation lane (AGENTS.md "Judgment: the maturation lane")
# --------------------------------------------------------------------------
#
# Distinct from sampler promotion (minimal -> PyAutoFit), this lane validates an
# already-promoted search on a new likelihood class: experiment tier (hand-rolled
# probes + findings docs) -> mature tier (first-class `af` search cells). Named
# as module constants so callers and tests can refer to a tier without
# re-spelling an instance fact.
SURFACE_LENS_DEVELOPER = "autolens_workspace_developer"
SURFACE_INFERENCE = "autolens_inference"
SURFACE_FIT_INFERENCE = "autofit_inference"
TIER_LENS_PROBES = "experiment probes (autolens searches_minimal)"
TIER_LENS_FINDINGS = "experiment findings (autolens searches_minimal)"
TIER_LENS_MATURE = "mature (autolens_inference searches cells)"
TIER_FIT_MATURE = "mature (autofit_inference searches cells)"
TIER_FIT_CATALOGUE = "mature (autofit_inference search catalogue)"
FIT_CATALOGUE = Path("catalogue") / "search_catalogue.json"

# The runner entrypoints whose call declares a mature cell, with the defaults
# each one supplies for a keyword its leaves may omit. `run_point_search` (the
# point-source runner) takes no `model_type`; the leaf's stem stands in for it.
RUNNERS = {
    "run_search": {},
    "run_point_search": {"sampler": "nautilus", "dataset_class": "point_source"},
}
# Runners whose leaves name no model_type: the leaf's stem stands in for it.
STEM_MODEL_TYPE = {"run_point_search"}


def tier_lens_probes(lens_developer: Path) -> list[str]:
    """Experiment tier: the runnable probes, same flat shape as the autofit
    minimal tier (so `_py_stems` — which already drops `_`-prefixed helpers —
    is reused verbatim)."""
    return _py_stems(lens_developer / "searches_minimal")


def _first_heading(path: Path) -> str:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def tier_lens_findings(lens_developer: Path) -> list[str]:
    """Experiment tier: the campaign findings docs as `name — first heading`.

    The heading carries the verdict ("... YES — on every mesh, once the
    regularization axis is handled"), which is the whole reason a conductor
    consults this tier; a doc with no heading degrades to its bare name.
    """
    root = lens_developer / "searches_minimal"
    if not root.is_dir():
        return []
    out = []
    for doc in sorted(root.glob("*_findings.md")):
        heading = _first_heading(doc)
        out.append(f"{doc.stem} — {heading}" if heading else doc.stem)
    return out


def _declared_cell(leaf: Path) -> tuple[str, str, str] | None:
    """Read the `run_search(sampler=, dataset_class=, model_type=)` declaration
    (or `run_point_search(...)`, see RUNNERS).

    The declaration — NOT the path — is the cell's identity. The two genuinely
    disagree on the live tree: every `cluster/searches/*/mge.py` leaf declares
    `dataset_class="group"` while its siblings declare `"cluster"`, and `group`
    is a legitimate dataset class (each such leaf passes an explicit
    `default_instrument`). Parsing the path would silently mislabel them.
    """
    try:
        tree = ast.parse(leaf.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name not in RUNNERS:
            continue
        given = {k.arg: k.value for k in node.keywords if k.arg}
        if any(not (isinstance(v, ast.Constant) and isinstance(v.value, str))
               for k, v in given.items()
               if k in ("sampler", "dataset_class", "model_type")):
            # A declaration keyword that is not a string literal cannot be read
            # statically; falling back to a runner default would mislabel it.
            return None
        kw = dict(RUNNERS[name])
        kw.update({k: v.value for k, v in given.items()
                   if isinstance(v, ast.Constant) and isinstance(v.value, str)})
        if name in STEM_MODEL_TYPE:
            kw.setdefault("model_type", leaf.stem)
        if {"sampler", "dataset_class", "model_type"} <= kw.keys():
            return kw["sampler"], kw["dataset_class"], kw["model_type"]
    return None


def tier_mature(inference: Path) -> list[str]:
    """Mature tier: the (sampler x dataset_class x model_type) cell matrix.

    Walks every `scripts/**/*.py` leaf under an inference checkout, skipping
    the `misc/` framework directory and `_`-prefixed helpers, and keeps the
    leaves that declare a cell through a RUNNERS call — wherever they live
    (the point-source leaves sit at `scripts/point_source/<instrument>/`, not
    under a `searches/` directory). A `scripts/<dataset>/searches/<sampler>/
    <model_type>.py` leaf with no parsable declaration falls back to its path
    shape rather than vanishing.

    The tier is EMPTY until autolens-inference phase 3 builds these cells
    (autolens_profiling#245 removed the retired inference programme's copies,
    and this walk was repointed here rather than left pointing at a tree that
    no longer exists). An absent or empty `scripts/` returns `[]` — never
    raises — so an un-cloned or still-empty successor repo is reported as a
    surface with no cells rather than a crash.
    """
    scripts = inference / "scripts"
    if not scripts.is_dir():
        return []
    cells = set()
    for leaf in scripts.rglob("*.py"):
        rel = leaf.relative_to(scripts).parts
        if leaf.stem.startswith("_") or rel[0] == "misc":
            continue
        declared = _declared_cell(leaf)
        if declared is None:
            if len(rel) == 4 and rel[1] == "searches":
                declared = (rel[2], rel[0], leaf.stem)
            else:
                continue
        cells.add("/".join(declared))
    return sorted(cells)


tier_lens_mature = tier_mature  # the lens surface's name for the shared walk


def fit_catalogue(fit_inference: Path) -> tuple[list[str], dict | None]:
    """The autofit inference search catalogue's verdict cells.

    Rows are `<task>/<Search>: <status>` (`measured`, `deferred`,
    `unsupported`, ...), one per search per requested task — the catalogue
    groups by task and never ranks across tasks, so neither does this row
    list. Returns ([], None) when the catalogue is absent or unreadable.
    """
    path = fit_inference / FIT_CATALOGUE
    try:
        cat = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], None
    rows = []
    for task, body in (cat.get("tasks") or {}).items():
        for search, cell in (body.get("searches") or {}).items():
            rows.append(f"{task}/{search}: {cell.get('status', '?')}")
    meta = {
        "path": str(path),
        "protocol_id": cat.get("protocol_id"),
        "ranking": cat.get("ranking"),
        "manifest_autofit_version": (cat.get("manifest") or {}).get("autofit_version"),
    }
    return sorted(rows), meta


def benchmarks(developer: Path) -> dict:
    out_dir = developer / "searches_minimal" / "output"
    result = {"comparison": None, "summaries": []}
    comp = out_dir / "comparison.txt"
    if comp.is_file():
        lines = comp.read_text(encoding="utf-8",
                               errors="replace").splitlines()
        table = [l for l in lines if l.startswith("|")]
        result["comparison"] = {"path": str(comp), "table": table}
    if out_dir.is_dir():
        result["summaries"] = sorted(p.name
                                     for p in out_dir.glob("*_summary.txt"))
    return result


def gaps(minimal, integration, promoted, integration_by_manifest=None) -> list[str]:
    """Tier-mismatch findings, phrased for the consulting conductor.

    `promoted` holds `<group>/<pkg>/<Class>` rows (or bare class names); every
    comparison is against the exported class. With a manifest,
    `integration_by_manifest` maps each search name to whether its manifest
    `integration_test` anchor exists, and that is the coverage rule. Without
    one, an integration script covers a class when its stem, `_jax` and other
    variants stripped, equals the class name (case-insensitive). Either way a
    prototype is promoted when its family equals an exported class or a
    PROTOTYPE_ALIASES entry names one.
    """
    classes = {row.rsplit("/", 1)[-1] for row in promoted}
    by_lower = {c.lower(): c for c in classes}
    if integration_by_manifest is not None:
        covered = {n.lower() for n, ok in integration_by_manifest.items() if ok}
    else:
        covered = {family_of(n) for n in integration}
    out = []
    for fam in sorted({family_of(n) for n in minimal}):
        names = PROTOTYPE_ALIASES.get(fam, (fam,))
        if not any(n.lower() in by_lower for n in names):
            out.append(f"'{fam}' is prototyped in searches_minimal but has no "
                       f"PyAutoFit implementation — promotion candidate")
    for cls in sorted(classes):
        if cls.lower() not in covered:
            out.append(f"promoted search '{cls}' has no "
                       f"autofit_workspace_test/scripts/searches integration "
                       f"script")
    return out


def digest(autofit, developer, test, lens_developer=None, inference=None,
           fit_inference=None, manifest_file=None) -> dict:
    d = {
        "surfaces_present": [],
        "tiers": {},
        "benchmarks": {},
        "gaps": [],
        "instruction": "reason with agents/faculties/samplers/AGENTS.md "
                       "(sampler<->likelihood match, gradients/JAX, "
                       "initialization chaining); the science lives in "
                       "PyAutoMemory/wiki/methods — internal use only, "
                       "citations never reach public output",
    }
    minimal = integration = []
    promoted = []
    manifest = None
    if developer and developer.is_dir():
        d["surfaces_present"].append("autofit_workspace_developer")
        minimal = tier_minimal(developer)
        d["tiers"]["minimal (searches_minimal)"] = minimal
        d["tiers"]["archive (searches)"] = []  # filled once promoted is known
        d["benchmarks"] = benchmarks(developer)
    if test and test.is_dir():
        d["surfaces_present"].append("autofit_workspace_test")
        integration = tier_integration(test)
        d["tiers"]["integration (scripts/searches)"] = integration
    if manifest_file or (autofit and autofit.is_dir()):
        manifest = load_manifest(autofit, manifest_file)
    if autofit and autofit.is_dir():
        d["surfaces_present"].append("PyAutoFit")
    elif manifest is not None:
        d["surfaces_present"].append("search manifest")
    if manifest is not None:
        promoted = manifest_promoted(manifest)
        d["tiers"]["promoted (autofit exports)"] = promoted
        # A checkout's __version__ string is not a release; name the checkout.
        d["manifest"] = {"source": f"file {manifest_file}" if manifest_file
                         else f"search manifest of the checkout {autofit}",
                         "schema": manifest["schema"],
                         "autofit_version": manifest.get("autofit_version")}
    elif autofit and autofit.is_dir():
        promoted = tier_promoted(autofit)
        d["tiers"]["promoted (autofit exports)"] = promoted
        d["manifest"] = {"source": (f"AST fallback (--manifest {manifest_file} "
                                    f"unreadable or not {MANIFEST_SCHEMA})")
                         if manifest_file else
                         "AST fallback (autofit not importable)"}
    elif manifest_file:
        d["manifest"] = {"source": f"unusable: --manifest {manifest_file} "
                                   f"unreadable or not {MANIFEST_SCHEMA}"}
    if "archive (searches)" in d["tiers"]:
        d["tiers"]["archive (searches)"] = tier_archive(
            developer, [row.rsplit("/", 1)[-1] for row in promoted])
    if lens_developer and lens_developer.is_dir():
        d["surfaces_present"].append(SURFACE_LENS_DEVELOPER)
        d["tiers"][TIER_LENS_PROBES] = tier_lens_probes(lens_developer)
        d["tiers"][TIER_LENS_FINDINGS] = tier_lens_findings(lens_developer)
    if inference and inference.is_dir():
        d["surfaces_present"].append(SURFACE_INFERENCE)
        d["tiers"][TIER_LENS_MATURE] = tier_mature(inference)
    if fit_inference and fit_inference.is_dir():
        d["surfaces_present"].append(SURFACE_FIT_INFERENCE)
        d["tiers"][TIER_FIT_MATURE] = tier_mature(fit_inference)
        rows, meta = fit_catalogue(fit_inference)
        d["tiers"][TIER_FIT_CATALOGUE] = rows
        if meta:
            d["fit_inference_catalogue"] = meta
    # The lane tiers are inventory only: `gaps` stays keyed on the autofit
    # promotion tiers, so adding them introduces no new judgment.
    if minimal or promoted:
        by_manifest = (manifest_integration(manifest, test)
                       if manifest is not None and test and test.is_dir() else None)
        d["gaps"] = gaps(minimal, integration, promoted, by_manifest)
    return d


def emit_human(d: dict) -> None:
    print("== SamplerSurface (read-only) ==")
    print(f"surfaces present: {', '.join(d['surfaces_present']) or 'NONE'}")
    if d.get("manifest"):
        m = d["manifest"]
        version = (f" (reports __version__ {m['autofit_version']})"
                   if m.get("autofit_version") else "")
        print(f"search catalogue from: {m['source']}{version}")
    if d.get("fit_inference_catalogue"):
        c = d["fit_inference_catalogue"]
        print(f"fit inference catalogue: protocol {c['protocol_id']}, "
              f"ranking {c['ranking']}")
    for tier, names in d["tiers"].items():
        print(f"\n-- {tier}: {len(names)}")
        for n in names:
            print(f"   {n}")
    comp = d["benchmarks"].get("comparison")
    if comp:
        print(f"\n-- benchmark comparison ({comp['path']})")
        for line in comp["table"]:
            print(f"   {line}")
    if d["benchmarks"].get("summaries"):
        print(f"\n-- per-sampler summaries: "
              f"{', '.join(d['benchmarks']['summaries'])}")
    if d["gaps"]:
        print("\n-- tier gaps")
        for g in d["gaps"]:
            print(f"   ! {g}")
    print(f"\n{d['instruction']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="samplers")
    ap.add_argument("--autofit", default="", help="PyAutoFit checkout")
    ap.add_argument("--developer", default="",
                    help="autofit_workspace_developer checkout")
    ap.add_argument("--test", default="",
                    help="autofit_workspace_test checkout")
    ap.add_argument("--lens-developer", default="", dest="lens_developer",
                    help="autolens_workspace_developer checkout "
                         "(lane experiment tier)")
    ap.add_argument("--inference", default="",
                    help="autolens_inference checkout (lane mature tier)")
    ap.add_argument("--fit-inference", default="", dest="fit_inference",
                    help="autofit_inference checkout (mature cells + search "
                         "catalogue)")
    ap.add_argument("--manifest", default="",
                    help="saved `python -m autofit search-manifest --json` "
                         "dump (default: print it from the --autofit checkout)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)
    autofit = Path(a.autofit) if a.autofit else None
    developer = Path(a.developer) if a.developer else None
    test = Path(a.test) if a.test else None
    lens_developer = Path(a.lens_developer) if a.lens_developer else None
    inference = Path(a.inference) if a.inference else None
    fit_inference = Path(a.fit_inference) if a.fit_inference else None
    manifest_file = Path(a.manifest) if a.manifest else None
    d = digest(autofit, developer, test, lens_developer, inference,
               fit_inference, manifest_file)
    if not d["surfaces_present"]:
        print("samplers: no sampler surface found (PyAutoFit / "
              "autofit_workspace_developer / autofit_workspace_test / "
              "autolens_workspace_developer / autolens_inference / "
              "autofit_inference absent)",
              file=sys.stderr)
        return 4
    print(json.dumps(d, indent=2)) if a.as_json else emit_human(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
