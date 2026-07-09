#!/usr/bin/env python3
"""agents/conductors/profiling/_profiling.py — core for the Profiling Agent.

The Profiling Agent is the *proprioceptive function* of PyAutoBrain — the
organism's sense of its own effort. It owns the
performance-data lifecycle of the organism, with `autolens_profiling` as its
workspace. It reasons over the campaign grid, the probe/batch tables, the
results tree and the pinned-value drift surface, and emits a structured
ProfilingDecision the human/session executes. It does NOT run sweeps itself
and never edits source — like every conductor, it decides and delegates.

Three modes (design decision recorded in the founding Mind prompt,
`issued/profiling_agent.md`, and lived in autolens_profiling#52/#54/#56):

- **campaign** — diff the campaign grid (sweep CELLS × configs) against the
  results tree (done / CPU-unusable / missing) and emit the dispatch plan for
  the requested tier, honouring the CPU-usability policy (per-run timeout,
  GPU-only markers).
- **ingest**  — find probe JSONs not yet reflected in the vram batch tables,
  and campaign results whose instruments have no pinned value, and emit the
  table-update / pinning / baseline / dashboard plan.
- **triage**  — read the profiling-drift findings from the vitals surface
  (Heart's `profiling_drift` leg — consulted via the vitals faculty's state,
  never by dispatching Heart) and classify each: stale pin → re-pin in the
  workspace; library regression → file a `bug/` prompt via intake. Never
  debug libraries inside the profiling repo (the phase-2 boundary rule).

Stdlib-only. The workspace's python modules are read via `ast` literal
parsing (importing them would drag the JAX stack into the Brain).
Exit codes: 0 decision · 4 missing input · 5 usage.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Any

PYAUTO_ROOT = Path(os.environ.get("PYAUTO_ROOT", Path.home() / "Code" / "PyAutoLabs"))
HEART_STATE_DIR = Path(os.environ.get("HEART_STATE_DIR", Path.home() / ".pyauto-heart"))

# Config axes per hardware tier. Local runs are clamped/capped by the
# CPU-usability policy; A100 rows are the production vmap numbers.
TIER_CONFIGS = {
    "local": ("local_cpu_fp64", "local_cpu_mp"),
    "a100": ("hpc_a100_fp64", "hpc_a100_mp"),
}
DEFAULT_PER_RUN_TIMEOUT = 3600


def workspace_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    return PYAUTO_ROOT / "autolens_profiling"


def _module_literal(py_path: Path, name: str):
    """Extract a module-level literal assignment via ast (no import)."""
    tree = ast.parse(py_path.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except ValueError:
                        return None
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name and node.value:
                try:
                    return ast.literal_eval(node.value)
                except ValueError:
                    return None
    return None


def load_grid(ws: Path) -> list[tuple[str, str, tuple[str, ...]]]:
    cells = _module_literal(ws / "likelihood_runtime" / "sweep.py", "CELLS")
    return cells or []


def load_tables(ws: Path) -> dict[str, Any]:
    cfg = ws / "vram" / "config.py"
    return {
        "VMAP_BATCH": _module_literal(cfg, "VMAP_BATCH") or {},
        "VMAP_BATCH_SPARSE": _module_literal(cfg, "VMAP_BATCH_SPARSE") or {},
        "PROVENANCE": _module_literal(cfg, "PROVENANCE") or {},
    }


# ---------------------------------------------------------------------------
# campaign
# ---------------------------------------------------------------------------


def campaign(ws: Path, tier: str) -> dict[str, Any]:
    if tier not in TIER_CONFIGS:
        return {"agent": "profiling", "mode": "campaign", "error": f"unknown tier {tier!r}"}
    grid = load_grid(ws)
    runtime = ws / "results" / "runtime"
    done: list[str] = []
    unusable: list[str] = []
    missing: list[str] = []

    for cls, model, instruments in grid:
        for inst in instruments or (None,):
            cell_dir = runtime / cls / model / inst if inst else runtime / cls / model
            cell_id = f"{cls}/{model}/{inst}" if inst else f"{cls}/{model}"
            for cfg in TIER_CONFIGS[tier]:
                run_id = f"{cell_id} [{cfg}]"
                if (cell_dir / f"{model}_{cfg}.json").exists():
                    done.append(run_id)
                elif (cell_dir / f"{model}_{cfg}.unusable.json").exists():
                    unusable.append(run_id)
                else:
                    missing.append(run_id)

    dispatch: list[str]
    if tier == "local":
        dispatch = [
            f"python3 likelihood_runtime/sweep.py --skip-gpu --skip-existing "
            f"--per-run-timeout {DEFAULT_PER_RUN_TIMEOUT}",
            "python3 likelihood_runtime/sweep.py --skip-gpu --skip-existing "
            f"--per-run-timeout {DEFAULT_PER_RUN_TIMEOUT} --sparse "
            "--only <imaging cells>",
            "python3 likelihood_runtime/aggregate.py",
        ]
    else:
        submits = sorted(p.name for p in (ws / "hpc" / "batch_gpu").glob("submit_*"))
        dispatch = [f"sbatch hpc/batch_gpu/{s}  (on the RAL checkout, post-pull)" for s in submits]

    return {
        "agent": "profiling",
        "mode": "campaign",
        "tier": tier,
        "grid_cells": sum(len(instruments or (1,)) for _, _, instruments in grid),
        "runs_done": len(done),
        "runs_unusable": len(unusable),
        "runs_missing": len(missing),
        "missing": missing,
        "unusable": unusable,
        "policy": (
            f"CPU-usability: per-run wall-clock cap {DEFAULT_PER_RUN_TIMEOUT}s; "
            "per-call > 60 s renders unusable; both mean GPU-only "
            "(results/notes/design_lock_in.md)"
        ),
        "dispatch_plan": dispatch,
        "next_action": (
            "all runs accounted for — proceed to ingest"
            if not missing
            else f"dispatch the {tier} plan ({len(missing)} runs outstanding)"
        ),
    }


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


def ingest(ws: Path) -> dict[str, Any]:
    tables = load_tables(ws)
    runtime = ws / "results" / "runtime"

    probes: list[dict[str, Any]] = []
    # Fresh evidence only: a probe older than the table file has already been
    # reasoned over (e.g. the 2026-05 A100 probes whose recommendations the
    # table deliberately halved after cuFFT scratch failures — resurfacing
    # them would reintroduce the failure the halving fixed).
    table_mtime = (ws / "vram" / "config.py").stat().st_mtime
    for p in sorted(runtime.rglob("vmap_probe_*.json")):
        if p.stat().st_mtime <= table_mtime:
            continue
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        key = (d.get("dataset"), d.get("model"), d.get("instrument"))
        sparse = p.stem.endswith("_sparse")
        table = tables["VMAP_BATCH_SPARSE"] if sparse else tables["VMAP_BATCH"]
        current = table.get(key)
        rec = d.get("recommended_batch_size")
        if rec is not None and rec != current:
            probes.append(
                {
                    "probe": str(p.relative_to(runtime)),
                    "cell": "/".join(str(k) for k in key),
                    "path": "sparse" if sparse else "dense",
                    "table_value": current,
                    "probe_recommends": rec,
                    "backend": d.get("backend"),
                }
            )

    unpinned: list[str] = []
    for p in sorted(runtime.rglob("*.json")):
        if p.name.endswith(".unusable.json") or p.name.startswith("vmap_probe"):
            continue
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if "pinned_expected" in d and d["pinned_expected"] is None:
            unpinned.append(str(p.relative_to(runtime)))

    return {
        "agent": "profiling",
        "mode": "ingest",
        "provenance": tables["PROVENANCE"],
        "probe_updates": probes,
        "unpinned_results": unpinned,
        "steps": [
            "apply probe_updates to vram/config.py (keep MB/replica comments) + bump PROVENANCE",
            "pin unpinned_results per-instrument (each run printed its value; "
            "the JSON carries it under the script's likelihood/evidence key)",
            "python3 scripts/build_baseline.py --name <BaselineName>",
            "python3 scripts/build_readme.py && commit",
        ],
        "next_action": (
            "nothing to ingest"
            if not probes and not unpinned
            else f"{len(probes)} table update(s), {len(unpinned)} unpinned result(s) — apply steps"
        ),
    }


# ---------------------------------------------------------------------------
# triage
# ---------------------------------------------------------------------------


def triage(ws: Path) -> dict[str, Any]:
    drift_path = HEART_STATE_DIR / "profiling_drift.json"
    if not drift_path.is_file():
        return {
            "agent": "profiling",
            "mode": "triage",
            "observed": False,
            "findings": [],
            "next_action": (
                "no profiling_drift surface — run a Heart tick (the vitals "
                "faculty reads the verdict; this mode reads the drift leg's state)"
            ),
        }
    try:
        drift = json.loads(drift_path.read_text())
    except (OSError, ValueError):
        drift = {}
    findings = []
    for f in drift.get("findings") or []:
        findings.append(
            {
                "path": f.get("path"),
                "instrument": f.get("instrument"),
                "labels": [d.get("label") for d in (f.get("drift") or [])],
                "classify": (
                    "stale pin → re-pin in autolens_profiling if the change is "
                    "understood/expected; else library regression → file bug/ "
                    "via intake (never debug the library in the profiling repo)"
                ),
            }
        )
    return {
        "agent": "profiling",
        "mode": "triage",
        "observed": bool(drift.get("observed")),
        "files_scanned": drift.get("files_scanned", 0),
        "findings": findings,
        "next_action": (
            "no drift — baselines comparable"
            if not findings
            else f"{len(findings)} drifted result(s) — classify each per the rule"
        ),
    }


# ---------------------------------------------------------------------------
# emit + main
# ---------------------------------------------------------------------------


def emit_human(d: dict[str, Any]) -> None:
    print(f"== ProfilingDecision ({d['mode']}) ==")
    if d.get("error"):
        print(f"ERROR: {d['error']}")
        return
    if d["mode"] == "campaign":
        print(f"Tier:                 {d['tier']}")
        print(
            f"Runs:                 {d['runs_done']} done · "
            f"{d['runs_unusable']} CPU-unusable (GPU-only) · {d['runs_missing']} missing"
        )
        for r in d["missing"][:10]:
            print(f"  missing: {r}")
        if len(d["missing"]) > 10:
            print(f"  ... +{len(d['missing']) - 10} more")
        print(f"Policy:               {d['policy']}")
        print("Dispatch plan:")
        for s in d["dispatch_plan"]:
            print(f"  - {s}")
    elif d["mode"] == "ingest":
        print(f"Provenance:           {d['provenance']}")
        print(f"Probe updates:        {len(d['probe_updates'])}")
        for u in d["probe_updates"][:10]:
            print(
                f"  {u['cell']} [{u['path']}]: table {u['table_value']} → "
                f"probe {u['probe_recommends']} ({u['backend']})"
            )
        print(f"Unpinned results:     {len(d['unpinned_results'])}")
        for u in d["unpinned_results"][:10]:
            print(f"  {u}")
        print("Steps:")
        for s in d["steps"]:
            print(f"  - {s}")
    elif d["mode"] == "triage":
        print(f"Observed:             {d.get('observed')}")
        print(f"Findings:             {len(d['findings'])}")
        for f in d["findings"]:
            print(f"  {f['path']} [{', '.join(map(str, f['labels']))}]")
            print(f"    → {f['classify']}")
    print(f"Next action:          {d['next_action']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="profiling")
    ap.add_argument("mode", nargs="?", default="campaign", choices=["campaign", "ingest", "triage"])
    ap.add_argument("--tier", default="local", help="campaign tier: local | a100")
    ap.add_argument("--workspace", default=None, help="override the autolens_profiling path")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)

    ws = workspace_root(a.workspace)
    if not ws.is_dir():
        print(f"profiling: workspace not found: {ws}", file=sys.stderr)
        return 4

    if a.mode == "campaign":
        d = campaign(ws, a.tier)
    elif a.mode == "ingest":
        d = ingest(ws)
    else:
        d = triage(ws)

    print(json.dumps(d, indent=2)) if a.as_json else emit_human(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
