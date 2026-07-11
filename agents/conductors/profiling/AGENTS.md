# Profiling agent

> **Tier: conductor** — a front-door agent you *drive*. The *proprioceptive
> function* — the organism's sense of its own effort: it owns the
> performance-data lifecycle, with
> `autolens_profiling` as its workspace. It consults the read-only vitals
> faculty like every conductor and reads Heart's `profiling_drift` leg state;
> it never dispatches Heart and never edits source — it reasons and emits a
> `ProfilingDecision` the human/session executes.

Grown from demonstrated need: the PreOptimizationTimes polish series
(autolens_profiling#52/#54/#56) ran campaign dispatch, vram-first validation,
probe ingest, pin maintenance, baseline snapshots and drift pairing through
the generic dev-flow with heavy manual orchestration at every judgment point.
Design decision (conductor vs faculty, boundaries) recorded in the founding
prompt, PyAutoMind `issued/profiling_agent.md`.

## Modes

| Mode | Question | Emits |
|------|----------|-------|
| `campaign` | Which grid runs are done / CPU-unusable / missing on this tier, and how do I dispatch the rest? | dispatch plan (local sweep flags incl. the per-run timeout; A100 submit list) |
| `ingest` | Which probe JSONs aren't in the vram tables yet, and which results have no pin? | table-update rows, pin list, baseline + dashboard steps |
| `triage` | What do the pinned-drift findings mean? | per-finding classification: stale pin → re-pin here; library regression → `bug/` via intake |

```
pyauto-brain profiling                       # campaign, local tier
pyauto-brain profiling campaign --tier a100  # RAL dispatch plan
pyauto-brain profiling ingest
pyauto-brain profiling triage
pyauto-brain profiling <mode> --json
```

## Fundamental principles

- **The classification is the result** for CPU-unusable cells (the usability
  policy in `autolens_profiling/results/notes/design_lock_in.md`): per-run
  wall-clock cap or per-call > 1 min ⇒ GPU-only; full timings belong to the
  A100 rows.
- **Profiling records and flags; it never adjudicates library correctness** —
  that is autolens_workspace_test's remit. Triage classifies and routes; it
  never plans a library debug inside the profiling repo.
- Stdlib-only: the workspace's grid and tables are read via `ast` literal
  parsing, never imported (importing would drag the JAX stack into the Brain).

## Boundaries

- **vs health** — Heart observes and verdicts (including the
  `profiling_drift` leg, PyAutoHeart#38); this agent runs the measurement
  lifecycle. Heart never dispatches campaigns; this agent never issues health
  verdicts.
- **vs hygiene** — split by *what is measured*: profiling owns the product's
  modelling / compute speed (likelihood on the science grid, GPU tiers, A100);
  the **hygiene conductor** (`agents/conductors/hygiene/`) owns the developer
  loop's cost (unit-test time, `PYAUTO_TEST_MODE` / `PYAUTO_SMALL_DATASETS`
  scripts, import time) and repo tidiness. Hunting generally-slow functions
  flagged by integration tests is hygiene's `perf` mode, not profiling's.
- **vs build** — campaigns are not releases; `profile.yml`'s on-release runs
  stay CI/Build territory.

## Future modes (staged in the founding prompt)

JAX compilation-time profiling of likelihood functions. (Hunting
generally-slow functions flagged by integration tests moved to the hygiene
conductor's `perf` mode — that is developer-loop cost, not modelling speed.)
A read-only profiling *faculty* (opine on regressions / optimization targets)
splits out only on demonstrated consult demand.
