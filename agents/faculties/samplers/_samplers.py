#!/usr/bin/env python3
"""agents/faculties/samplers/_samplers.py — the SamplerSurface digest.

The **samplers faculty** is a read-only opinion sink: it inventories the
organism's non-linear-search machinery — the three script tiers (minimal
prototypes, the removed-sampler archive, the workspace_test integration
scripts) and the PyAutoFit search catalogue — plus the latest minimal-tier
benchmark outputs, and flags tier gaps (prototyped but never promoted,
promoted but never integration-tested). The consulting agent reads the digest
and reasons with AGENTS.md's judgment tables; this script never writes,
never runs a sampler, and never edits anything.

Exit codes: 0 digest · 4 no surface found · 5 usage.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Map script/module basenames to a canonical sampler family so tiers can be
# compared. Suffixes like _jax/_jit/_grad/_simple are variants, not families.
VARIANT_SUFFIXES = ("_simple", "_jax", "_jit", "_grad")
ALIASES = {
    "nuts": "nuts", "blackjaxnuts": "nuts", "blackjax": "nuts",
    "dynestystatic": "dynesty", "dynestydynamic": "dynesty",
    "bfgs": "lbfgs",
}


def family_of(name: str) -> str:
    base = name.lower()
    for suf in VARIANT_SUFFIXES:
        base = base.removesuffix(suf)
    return ALIASES.get(base, base)


def _py_stems(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.py")
                  if not p.stem.startswith("_"))


def tier_minimal(developer: Path) -> list[str]:
    return _py_stems(developer / "searches_minimal")


def tier_archive(developer: Path) -> list[str]:
    root = developer / "searches"
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir()
                  if d.is_dir() and not d.name.startswith(("_", ".")))


def tier_integration(test: Path) -> list[str]:
    return _py_stems(test / "scripts" / "searches")


def tier_promoted(autofit: Path) -> list[str]:
    """Package inventory: autofit/non_linear/search/<group>/<sampler>/."""
    root = autofit / "autofit" / "non_linear" / "search"
    if not root.is_dir():
        return []
    out = []
    for group in sorted(root.iterdir()):
        if not group.is_dir() or group.name.startswith("_"):
            continue
        for pkg in sorted(group.iterdir()):
            if pkg.is_dir() and not pkg.name.startswith("_"):
                out.append(f"{group.name}/{pkg.name}")
    return out


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


def gaps(minimal, integration, promoted) -> list[str]:
    """Tier-mismatch findings, phrased for the consulting conductor."""
    min_fams = {family_of(n) for n in minimal}
    int_fams = {family_of(n) for n in integration}
    pro_fams = {family_of(n.split("/", 1)[1]) for n in promoted}
    out = []
    for fam in sorted(min_fams - pro_fams):
        out.append(f"'{fam}' is prototyped in searches_minimal but has no "
                   f"PyAutoFit implementation — promotion candidate")
    for fam in sorted(pro_fams - int_fams):
        out.append(f"promoted search '{fam}' has no "
                   f"autofit_workspace_test/scripts/searches integration "
                   f"script")
    return out


def digest(autofit, developer, test) -> dict:
    d = {
        "surfaces_present": [],
        "tiers": {},
        "benchmarks": {},
        "gaps": [],
        "instruction": "reason with agents/faculties/samplers/AGENTS.md "
                       "(sampler<->likelihood match, gradients/JAX, "
                       "initialization chaining); the science lives in "
                       "PyAutoMemory/methods_wiki — internal use only, "
                       "citations never reach public output",
    }
    minimal = integration = []
    promoted = []
    if developer and developer.is_dir():
        d["surfaces_present"].append("autofit_workspace_developer")
        minimal = tier_minimal(developer)
        d["tiers"]["minimal (searches_minimal)"] = minimal
        d["tiers"]["archive (searches)"] = tier_archive(developer)
        d["benchmarks"] = benchmarks(developer)
    if test and test.is_dir():
        d["surfaces_present"].append("autofit_workspace_test")
        integration = tier_integration(test)
        d["tiers"]["integration (scripts/searches)"] = integration
    if autofit and autofit.is_dir():
        d["surfaces_present"].append("PyAutoFit")
        promoted = tier_promoted(autofit)
        d["tiers"]["promoted (autofit/non_linear/search)"] = promoted
    if minimal or promoted:
        d["gaps"] = gaps(minimal, integration, promoted)
    return d


def emit_human(d: dict) -> None:
    print("== SamplerSurface (read-only) ==")
    print(f"surfaces present: {', '.join(d['surfaces_present']) or 'NONE'}")
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
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)
    autofit = Path(a.autofit) if a.autofit else None
    developer = Path(a.developer) if a.developer else None
    test = Path(a.test) if a.test else None
    d = digest(autofit, developer, test)
    if not d["surfaces_present"]:
        print("samplers: no sampler surface found (PyAutoFit / "
              "autofit_workspace_developer / autofit_workspace_test absent)",
              file=sys.stderr)
        return 4
    print(json.dumps(d, indent=2)) if a.as_json else emit_human(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
