#!/usr/bin/env python3
"""_hygiene_profile.py — rank the slowest dev-loop functions from a cProfile
stats file, for the hygiene conductor's `perf --profile` action.

Stdlib only (pstats + json) — this NEVER imports the science stack. It is handed
a stats file that the hygiene conductor produced by running the target script
under `cProfile` in a subprocess (so the science/JAX stack lives only in that
child, never here).

**Scope is BROAD by default.** This profiles the whole universe of dev-loop
functions — simulation, data prep, model composition, plotting, the aggregator,
config/serialization, and general utilities (including ones called *during* a
fit, e.g. array/grid helpers). The ONE hard boundary is the **likelihood
function itself**: the log-likelihood / figure-of-merit computation (and its JAX
compilation) is `/profiling`'s domain, not hygiene's. Everything else is fair
game — hygiene surfaces it and the human/refactor agent judges.

Two tiers of exclusion, both validated against a real profiled modeling script:

  1. THE LIKELIHOOD BOUNDARY — the likelihood *entry points* + JAX/XLA compile.
     These wrap the whole fit, so ranking by SELF time (`tottime`) already drops
     the entry points (huge cumulative, ~0 self); the names + JAX compile frames
     make the boundary explicit. This is the only *domain* exclusion.
  2. NON-REFACTORABLE NOISE — no-source built-ins and import/loader startup. You
     cannot `/refactor` a C builtin, so it is never a candidate — this is not a
     scope choice, just signal hygiene.

A TRANSPARENT HEURISTIC, not a perfect separator: a surfaced hotspot that turns
out to live inside the likelihood compute is `/profiling`'s — a judgement made
by the human/refactor agent, surfaced not enforced. To profile even more broadly
(e.g. include the JAX/likelihood frames), pass HYGIENE_PROFILE_EXCLUDE (a
comma-separated substring list) to replace the domain tier entirely.
"""

from __future__ import annotations

import json
import os
import pstats
import sys

# Tier 1 — the likelihood-function boundary (/profiling's domain, not hygiene's).
LIKELIHOOD_BOUNDARY = [
    "log_likelihood", "figure_of_merit", "fitness",   # likelihood entry points
    "jax", "jaxlib", "/xla", "_src/compiler", "pjrt", "mlir",  # JAX/XLA compile+backend
]
# Tier 2 — non-refactorable noise (not a scope choice; you can't /refactor these).
NOISE = ["dlopen", "marshal", "create_dynamic", "_imp", "frozen importlib"]

DEFAULT_EXCLUDE = LIKELIHOOD_BOUNDARY + NOISE


def load_exclude() -> list[str]:
    override = os.environ.get("HYGIENE_PROFILE_EXCLUDE")
    if override:
        return [p.strip().lower() for p in override.split(",") if p.strip()]
    return DEFAULT_EXCLUDE


def is_excluded(name: str, filename: str, patterns: list[str]) -> bool:
    # Structurally drop frames with no refactorable Python source: C builtins
    # (filename "~") and synthetic frames ("<string>", "<frozen ...>"). You
    # cannot /refactor a built-in method, so it is never a hygiene candidate.
    if filename == "~" or filename.startswith("<") or name == "<module>":
        return True
    hay = f"{name} {filename}".lower()
    return any(p in hay for p in patterns)


def candidates(stats_path: str, top_n: int = 15) -> list[dict]:
    """Return the top_n non-likelihood functions by self time."""
    patterns = load_exclude()
    stats = pstats.Stats(stats_path)
    rows: list[dict] = []
    for func, (cc, nc, tt, ct, callers) in stats.stats.items():
        filename, lineno, name = func
        if is_excluded(name, filename, patterns):
            continue
        rows.append({
            "function": name,
            "location": f"{filename}:{lineno}",
            "self_seconds": round(tt, 3),
            "cumulative_seconds": round(ct, 3),
            "ncalls": nc,
        })
    rows.sort(key=lambda r: -r["self_seconds"])
    return rows[:top_n]


def main(argv: list[str]) -> int:
    args = argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    top_n = 15
    if "--top" in args:
        i = args.index("--top")
        top_n = int(args[i + 1]); del args[i:i + 2]
    if not args:
        print("usage: _hygiene_profile.py <stats-file> [--top N] [--json]", file=sys.stderr)
        return 2
    stats_path = args[0]
    try:
        rows = candidates(stats_path, top_n)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"_hygiene_profile: could not read stats: {exc}", file=sys.stderr)
        return 3

    if as_json:
        print(json.dumps({"decision": "HygieneDecision", "mode": "perf-profile",
                          "candidates": rows, "delegate": "/refactor"}))
        return 0

    if not rows:
        print("  (no non-likelihood hotspots above the exclusion filter)")
        return 0
    for r in rows:
        loc = "/".join(r["location"].split("/")[-2:])
        print(f"  {r['self_seconds']:6.2f}s self  {r['ncalls']:>8} calls  "
              f"{r['function']}  ({loc})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
