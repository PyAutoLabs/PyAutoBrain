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
| `ingest --axis compile` | Which warm compile rows are unpinned, and which have drifted from their pin? | drifted rows (with pinned vs observed), unpinned keys, confirm/classify/re-pin steps |
| `triage` | What do the pinned-drift findings mean? | per-finding classification: stale pin → re-pin here; library regression → `bug/` via intake |
| `triage --axis compile` | What does the compile drift MEAN, and who owns it? | per-finding classification: cache / autotune / host-load / library regression, expected-recompile, new-machine, new-cell |

```
pyauto-brain profiling                       # campaign, local tier
pyauto-brain profiling campaign --tier a100  # RAL dispatch plan
pyauto-brain profiling ingest
pyauto-brain profiling triage
pyauto-brain profiling <mode> --json
```

### The measurement axes

`--axis runtime` (the default) is steady-state per-call cost, filed under
`results/runtime/` and bucketed by sweep **config** name (`local_cpu_fp64`,
`local_cpu_mp`, …). `--axis compile` is the one-off cost — trace, XLA compile,
first call — filed under `scripts/misc/jax_compile/results/<hardware>/` and
bucketed by **hardware**, with `mixed_precision` a separate field. The two
vocabularies do not interchange, so the compile axis maps tiers itself rather
than reusing `TIER_CONFIGS`.

`--axis compile` serves all three modes: `campaign` (coverage), `ingest`
(warm-pin drift) and `triage` (what the drift means).

**Drift is deliberately hard to trigger.** A row counts only if it is *newer*
than its pin, at least `2.0x` the pinned value, **and** at least `1.0 s` above it
in absolute terms. Rows predating the pin are the history the pin was chosen
over — flagging them would report the improvement that set the pin as a
regression. The ratio alone screams about sub-second cells where 100 ms of
jitter is 3x; the absolute floor alone misses a cheap cell degrading by an order
of magnitude. Both gates, generous, because host load alone has produced 7x
errors in this corpus and an alarm that cries wolf gets ignored.

Pins live in the workspace (`jax_compile/pins.json`) and are **sticky** — the
workspace's `update_pins.py` will not move an existing pin without `--repin`. If
pins auto-followed the newest measurement, re-deriving them after a cache
regression would bake the regression in and the surveillance would report
all-clear forever.

**Compile timings are host-load-sensitive** — the first measurements in
`jax_compile/README.md` were wrong by up to **7×** (851 s vs 117 s for the same
compile) purely from host load, because XLA compiles on the host cores. Rows are
comparable only within `(hardware, jax_version, mixed_precision, cache state)`.
`campaign --axis compile` therefore reports **coverage only** and never compares
two timings; comparison waits on the pins.

Records whose cell is not in the sweep grid (`knn`, `delaunay_matern`, the
`datacube_img*` multi-band classes) are reported in an **off-grid** bucket, and
non-tier hardware in an **other-hardware** bucket. Both are real measurements —
neither counts as grid coverage, and neither is silently dropped.

`jax_compile/` also hosts sibling instruments (`export_probe.py`,
`trace_profile.py`) that append their own schema into the same
`results/<hardware>/` tree. Records missing the whole `(hardware, dataset_class,
instrument)` identity triple are reported as **sibling-instrument** records, not
as malformed — only a record missing *some* of its key fields is corruption.

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
- **release-validation script cost is NOT ours.** The compile axis was
  originally proposed (PyAutoMind, 2026-07-14) to cover the release-validation
  heavy scripts blowing the 300 s cap. That was declined on the hygiene boundary
  above — script-suite cost is the developer loop, and it had already been moved
  out of this agent's staged future modes once. Recorded here so the question is
  not re-opened a third time.

### Classifying compile drift

`triage --axis compile` answers *who owns this*, which is the whole reason the
axis exists — the persistent compilation cache and `--xla_gpu_autotune_level=0`
are **settings**, so they can stop applying with nothing failing.

| classification | signal | actionable |
|---|---|---|
| `cache-regression` | warm compile has returned to its own **cold** scale | yes — config/stack, never the library |
| `autotune-regression` | GPU compile up ≥10× with no cold-scale match | yes — check the flag actually reaches XLA |
| `host-load` | the measuring host's 1m load average was high | no — re-measure idle first |
| `library-regression` | growth on an unchanged key with no other explanation | yes — route to `bug/` via intake |
| `expected-recompile` | the key differs from a pin only by `jax_version` | no — cache keys include the version, so one recompile is by design |
| `new-machine` / `new-precision` / `new-cell` | the key is simply unpinned | no — pin it |

The cold-scale comparison is what makes `cache-regression` a *measurement*
rather than a guess: 25 of 32 cell/transform keys in the corpus carry both a
warm and a cold row, so the yardstick is real data from the same machine.

Two categories the design deliberately does NOT have: drift caused by a
`jax_version` bump or a changed host never reaches `triage` at all, because
those are different comparability keys and `ingest` reports them as *unpinned*
rather than drifted. They are classified here as bookkeeping so nothing
vanishes, but they are never regressions.

## Future modes (staged in the founding prompt)

A read-only profiling *faculty* (opine on regressions / optimization targets)
splits out only on demonstrated consult demand.

(Two things that were once staged here have moved. Hunting generally-slow
functions flagged by integration tests is the hygiene conductor's `perf` mode —
developer-loop cost, not modelling speed. JAX compilation-time profiling of
likelihood functions is **built**, and is the `--axis compile` surface above.)
