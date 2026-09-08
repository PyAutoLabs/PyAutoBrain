# /ci_speedup — find the slowest parts of CI and make them faster

A **maintenance door** (see `PyAutoBrain/skills/COMMANDS.md` §5): the Hygiene
Agent reasons about CI cost and *ranks*; this skill *executes*, one item at a
time, through the ordinary dev flow. It is the CI-time counterpart of
`/repo_cleanup` (git debris) and `/issue_cleanup` (tracker debris).

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

**Where the numbers come from.** PyAutoHeart measures CI and publishes the
⏱ surface as the `performance` block of its board (`board.json`, schema v3):
per-script smoke timings per python leg, the slowest unit tests, and every
workflow's wall-clock distribution. Nothing here re-times CI and nothing here
scrapes a job log — a number that is not on the board is not a finding.

**Boundary.** This is the *developer loop's* cost — how long a gate keeps a
contributor waiting. The modelling/likelihood speed of the product is
`/profiling`; a hotspot inside `log_likelihood_function` / the JAX compile of a
fit is that agent's, and a speed-up that would change what a script *asserts*
is not a speed-up — it is a coverage cut, and it needs a human.

## Do

### 1. Rank

```bash
bin/pyauto-brain hygiene ci                    # top 3 per lane, all three lanes
bin/pyauto-brain hygiene ci --top 5 --lane scripts
bin/pyauto-brain hygiene ci --json             # the HygieneDecision, machine-readable
```

Reads the published board (Pages), or `HYGIENE_HEART_BOARD=<path|url>`, or a
local Heart checkout's `board/board.json`. One candidate per script — the
python legs are folded and the **slowest leg is the cost**, because the legs
run in parallel and the gate waits for the slower. Each item carries its
evidence (seconds, share of that leg's total, `cache_jax` state, run URL) and,
when the script is checked out under `PYAUTO_ROOT`, the **levers** read from
its text (`env_knob`, `simulates`, `jax_jit`, `full_datasets`, `real_search`,
`subprocess`, `plots`). Pick the item you were handed, or the top one.

Read the board's caveats before believing a number: a `cache_jax: miss` leg
paid every compile in full, a cold dataset cache paid the simulator inside
the script's own timing, and `verdict: stale` means the Heart has not looked
recently. The `slowed` rows and hang `events` are separate signals — a
*slowdown* routes to `/bug` (something changed), a hang to the kill-timer
prompt the board already carries. This skill is for the standing cost.

### 2. Name the cost (measure locally, under the smoke profile)

Reproduce the CI number before touching anything — a fix to a cost you have
not seen is a guess. Run the script exactly as CI does: the repo's
`config/build/profile_smoke.yaml` defaults plus the script's own `__Env__`
declaration (`ENV: jax full_datasets` releases `PYAUTO_DISABLE_JAX` and
`PYAUTO_SMALL_DATASETS`; `real_search` releases `PYAUTO_TEST_MODE`), the
libraries on `PYTHONPATH` from source, a **cold** `JAX_COMPILATION_CACHE_DIR`
for the first run and a warm one for the second. Then:

- `python -m cProfile -o run.prof <script>` and rank by cumulative time —
  `pyauto-brain hygiene perf --profile <script>` does this and applies the
  likelihood-exclusion filter for you.
- Vary the levers the ranker named (`DELAUNAY_NN_CAP_RANDOM_SAMPLES=10`, a
  pre-simulated dataset, a warm cache) and time each. The delta *is* the cost.

Write the split down: **compile / simulate / search / repeated construction /
plots / assertions**. A fix that does not name which of these it removes is
not ready.

### 3. Choose the lever (smallest change that keeps the assertion)

| Cost | Lever | Where the change lives |
|------|-------|------------------------|
| A sizing knob the script already reads (`os.environ.get`) | `set:` it lower in `profile_smoke.yaml` under a `pattern:` for that script | workspace `config/build/profile_smoke.yaml` (validator keys: `pattern`, `set`, `unset`) |
| Simulation inside the timing (`should_simulate` + subprocess) | keep the dataset cache warm (`pyauto-datasets-*` key), or make the simulator cheap under `PYAUTO_TEST_MODE` | Heart `smoke-tests.yml` cache keys; the simulator script |
| Compile paid in full (`cache_jax: miss`) | fix the cache key/restore, or cut *distinct* compiles (same shapes → one trace; one `jit` per shape, not per call) | Heart `smoke-tests.yml`; the script |
| Same expensive object built N times (datasets, image meshes, factor graphs) | build once, reuse — `functools.lru_cache` on the builder, or hoist out of the loop | the script |
| The search really runs (`real_search`) | cap iterations / live points for smoke via the profile, or declare `real_search` only where the assertion needs it | the script's `__Env__` / profile |
| A whole leg is slow, no single script stands out | look at `setup_s` (fixed overhead) and the per-leg `total_s` on the board; the fix is the workflow, not a script | Heart `smoke-tests.yml` |
| A unit test (`--lane tests`) | smaller fixture, fewer iterations, `pytest.mark.slow` **only** if the suite already has the marker gate — never skip | the library's tests |

**Never**: skip, disable, quarantine or demote a smoke script or test to get
the number down (the `no_run.yaml` / `smoke_tests.txt` route is a coverage
decision a human makes, with the reason written where the entry is); change
what an assertion checks; raise a cap so a slow thing hides; "fix" a
`mode=smoke`-only failure in the script when release passes (that is
`/hygiene extras`, a CI install problem).

### 4. Ship it through the dev flow

The change is ordinary development. Route it:

```bash
# a workspace script or its profile_smoke.yaml
/start_dev  → /start_workspace → edit → re-time (step 2, cold + warm) → /ship_workspace
# a library test
/start_dev  → /start_library   → edit → pytest the file → /ship_library
# a Heart workflow / cache key
/start_dev  → PyAutoHeart branch → /ship_library
```

In a remote session with no worktree, file the item instead: `/intake` the
📋 line with the measured split and the chosen lever as a
`draft/refactor/<target>/` prompt — the ranking plus the measurement is the
deliverable; the fix is the next session's `/start_dev`.

Before pushing: the script still passes under the smoke profile **and** the
release profile where it applies (`ENV:` tokens are honoured by both), the
assertion text is unchanged, and the new local timing is in the commit
message (before → after, cold and warm).

### 5. Report

One line per item: `repo/entry  before → after (cold/warm)  lever  PR/prompt`.
Then stop. The next Heart tick re-measures; the board is the record, and the
`slowed`/`ok` state on the next render is the verification — do not arm a
watcher for it.

## Boundaries

- **vs hygiene** — hygiene ranks and routes (`hygiene ci`); this door executes.
  Hygiene never edits source; this skill does, through `start_dev`/`ship_*`.
- **vs profiling** — profiling owns the science-grid likelihood, GPU tiers and
  baselines. If the cost is inside the likelihood compute, hand it over.
- **vs health** — Heart observes and verdicts; a red gate is `/health`'s. This
  door only touches gates that are *green and slow*.
- **vs bug** — a *slowdown* (the board's `slowed` rows: this run ≥ 1.5× the
  previous, ≥ the min delta) is a regression, so it is `/bug`'s; this door owns
  the standing cost that was always there.
