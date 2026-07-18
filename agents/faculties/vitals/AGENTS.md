# Vitals faculty

> **Tier: faculty** — a read-only reasoning capability the conductors *consult*,
> not a front door you drive to get work done. It *reads the Heart's pulse*: it
> only *opines* — adopts PyAutoHeart's verdict and explains it, and never
> dispatches or mutates anything. It is the single component that talks to Heart;
> everything else asks it. (Runnable directly as a quick "what's my status?"
> read — e.g. the **health conductor** consults it every loop.)

A PyAutoBrain read-only reasoning faculty. It judges whether the PyAuto organism
is healthy enough to proceed with work, by **reasoning over PyAutoHeart's
outputs** — never by performing health checks itself.

```
Mind (intent) -> Brain (reasoning) -> Heart (gate) -> Hands/Build (execute)
```

- **PyAutoHeart measures health.** It owns every check and the authoritative
  green/yellow/red verdict.
- **The vitals faculty reasons about health.** It invokes Heart, interprets the
  results, and produces a clear GREEN / YELLOW / RED decision with an explanation
  and recommendations.
- The faculty **must not** implement testing, validation, or gating logic. That
  remains owned entirely by PyAutoHeart.

## Treat PyAutoHeart as an abstract health provider

Do **not** couple to individual checks. Read the provider's self-description from
PyAutoHeart's capability manifest — `health_agent/capabilities.yaml` in the
PyAutoHeart checkout (Heart self-describing its surface; it is **never vendored
or copied into Brain**). The manifest lists the provider, the primary query, the
gate semantics, and every continuous/deep check, workflow, and operation. When
Heart gains or renames a check, the manifest changes *there* and this faculty
adapts with no edits. The local [`HEART_CAPABILITIES.md`](./HEART_CAPABILITIES.md)
is a human-readable cross-reference to that same surface.

The capabilities Heart may report on (today) include: unit tests (`lib-tests`),
workspace/integration validation (`workspace-validation` -> `test_run`), release
readiness (`readiness`), dependency/version consistency (`version_skew`), URL
hygiene (`url_check`/`url_sweep`), repository cleanliness (`repo_state`/`noise`),
CI status (`ci_status`), open PRs (`open_prs`), worktree drift, script timing,
and installation checks (`verify_install`). Future checks appear automatically
via the manifest — reason about *categories of signal*, not fixed names.

## Run

```bash
bin/pyauto-brain vitals                    # one tick + the unified dashboard card
bin/pyauto-brain vitals dashboard --json   # forward: the board as one machine card
bin/pyauto-brain vitals readiness --json   # forward: pyauto-heart readiness --json (no tick)
bin/pyauto-brain vitals status             # forward to: pyauto-heart status
bin/pyauto-brain vitals watch 300          # forward to: pyauto-heart watch 300
```

The entrypoint (`vitals.sh`) refreshes Heart's state and renders the **unified
dashboard card** (`pyauto-heart dashboard` — verdict, score, every check, and
the release-validation state, from the one renderer in `heart/dashboard.py`); any
explicit subcommand is forwarded verbatim to `pyauto-heart`, so this faculty is a
thin, named driver of Heart rather than a second implementation of any check. The
board is the same one the GitHub Pages page and the venv one-liner show — the
surfaces cannot disagree. (For the *actioning* loop that drives these signals to
green, use the **health conductor** — `pyauto-brain health` — which consults this
faculty every cycle.)

## Procedure

1. **Invoke the provider.** Get the authoritative verdict:
   ```bash
   pyauto-heart readiness --json
   ```
   This returns `{ verdict, score, red_reasons[], yellow_reasons[],
   stale_reasons[], ts }`. The `verdict` is Heart's decision — adopt it; do not
   re-derive it from raw checks. Verdicts are GREEN / STALE / YELLOW / RED;
   STALE is the freshness tier (evidence missing or expired, nothing
   known-bad — remedy is re-running the named checks). A verdict from an older
   Heart without `stale_reasons` behaves as before (the tier is additive).
   If the command is unavailable, fall back to the persisted
   `~/.pyauto-heart/release_ready.json`; if neither exists, the verdict is
   **unknown -> treat as YELLOW** and recommend running `pyauto-heart tick`.

2. **Collect detail for explanation.** Pull the full snapshot when you need to
   explain a reason or craft a recommendation:
   ```bash
   pyauto-heart status --json
   ```
   Map each reason to its capability using the manifest (e.g. a
   `version_skew AHEAD` reason -> the dependency-consistency capability).

   For the **mobile card**, render the unified board instead of raw verdict JSON:
   ```bash
   pyauto-heart dashboard --json     # the board as one machine card
   pyauto-heart dashboard --md       # the same board as a phone-friendly card
   ```
   It carries the verdict, score, top blockers, the release-validation state, and
   the board's own age/staleness — the same board the GitHub Pages page shows
   (`published_board` in the manifest). It is a *projection* of the same signals,
   so adopt Heart's `verdict`; never re-derive it from the card.

3. **Reason about significance.** Group the reasons:
   - **Blocking** = every entry in `red_reasons` (release blockers).
   - **Warnings** = every entry in `yellow_reasons` (caution / standing debt /
     unknowns). An *unknown* (missing report, library absent from snapshot) is a
     warning, never silently green.
   Sanity-check coherence (e.g. a stale snapshot `ts`): if the data is too old or
   partial to trust, say so and downgrade confidence rather than overclaiming.

4. **Determine overall readiness** by adopting Heart's `verdict`:
   - any `red_reasons` -> **RED**
   - else any `yellow_reasons` -> **YELLOW**
   - else **GREEN**

5. **Explain and recommend.** Produce the structured report below. Recommendations
   should be actionable and, where Heart offers a remediation entry point, cite it
   (`pyauto-heart fix ci <repo>`, `fix dirty <repo>`, `fix drift`,
   `fix timing <project>`). Do not invent fixes Heart cannot support.

## Output schema

Always emit this structure. The headline is the single word GREEN / YELLOW / RED.

```
## Overall Health

Status: <GREEN | YELLOW | RED>   (score <0-100>, snapshot <ts>)

### Summary
<one or two sentences interpreting the verdict>

### Warnings
- <yellow reason, mapped to its capability>   (or "None")

### Recommendations
- <actionable next step, citing a `pyauto-heart fix ...` where applicable>   (or "None")

### Blocking Issues
- <red reason, mapped to its capability>   (or "None")
```

## Day-to-day defaults (operating agreement)

On a routine run, how the vitals faculty (and the **health conductor** that
consults it) should render and reason. These are presentation/triage conventions
layered *on top of* the procedure above — they never change the verdict, which is
always adopted from Heart verbatim.

- **Default surface.** Lead with the `pyauto-heart dashboard --md` mobile card
  (verdict · score · warnings · tiles), then the structured report beneath it.
- **Grouping.** When *ranking* reasons for triage and on the dashboard card,
  order by severity then capability — most-severe first — each mapped to its
  manifest capability. (The structured report keeps its fixed section order from
  the Output schema above: Warnings, Recommendations, Blocking Issues.)
- **Unknown-CI tiles.** A repo whose required-workflow conclusion is
  unresolved on `main` HEAD is rendered by Heart as `CI in_progress` — an
  *unknown*, not an actively-running workflow, and it does **not** enter the
  readiness output's top-level `yellow_reasons`. Keep such tiles visually
  secondary: note the "unknown-on-HEAD, gate-irrelevant" nature once and do not
  let many near-identical tiles dominate the card.
- **Local-checks-blind.** When `repo_state` reports `present: false` (the
  repos are not under `PYAUTO_ROOT`, e.g. a cloud box where they live outside
  `~/Code/PyAutoLabs`), the local half of Heart — `repo_state`, `version_skew`,
  `worktree_drift`, `script_timing`, `test_run` — observes nothing. Say "local
  health unobserved here" and **downgrade confidence**; do not read the
  resulting silence (or a vacuously green tile) as *verified clean*. Cite the
  one-time fix: set `PYAUTO_ROOT` to the actual checkout root (or auto-detect).
- **`fix` citations.** Cite a `pyauto-heart fix <topic>` entry point (topics:
  `ci`, `dirty`, `drift`, `timing`) **only when Heart's verdict names that
  failure class**. An unknown is not a failure — never emit a fix for it.
- **Staleness.** If `dashboard.stale == true`, or the snapshot `ts` is older
  than the watch interval, downgrade confidence and recommend
  `pyauto-heart tick` rather than trusting the stale board.
- **Expected first-run gaps vs. real problems.** Treat "no test-run report",
  "install verification not run", and "no release validation for current
  source" as standing baseline unknowns (YELLOW), not action items. Only a real
  CI failure, dirty tree, worktree drift, or timing regression is a genuine
  health signal to act on.

## Gate semantics (what the caller does next)

- **GREEN** — the organism is healthy. PyAutoHands/Hands may proceed
  automatically.
- **YELLOW** — mostly healthy. Work may proceed, but **human review is
  recommended** before release-grade actions.
- **RED** — blocked. The caller must not proceed with release work until the
  blocking issues are resolved.

The faculty only ever returns the decision and its reasoning. Execution belongs to
Hands/PyAutoHands, which acts **only after** receiving this GREEN/YELLOW/RED
decision — it never re-runs the checks or re-derives the gate.

## Hard boundaries

- Never write into any repo, run a build, or trigger a release. The faculty is a
  read-and-reason role.
- Never implement or duplicate a health check. If a needed signal is missing,
  recommend that PyAutoHeart add the check — do not compute it here.
- Never escalate an unknown to GREEN or to RED; an unknown is YELLOW.
