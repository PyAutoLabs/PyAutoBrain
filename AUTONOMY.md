# The autonomy contract

The **one canonical page** for how much human checkpointing a workflow run
needs. Mind prompts carry `Autonomy: safe | supervised | human-required` in
their header (written at conception by the Intake Agent via the sizing
faculty — `PyAutoMind/README.md` "Prompt file format"); this page defines what
those levels *do* at each checkpoint. Every workflow skill links here instead
of restating checkpoint rules — if you are editing autonomy prose anywhere
else, stop and edit this file.

Levels are consumed **only as defined here**. A level is an input to a gate,
never a bypass of one.

## The checkpoints

Where the dev workflow stops for a human today:

| # | Checkpoint | Lives in |
|---|------------|----------|
| 1 | **Plan approval** — present the plan, wait for explicit approval before any edit | `start_dev` (Plan Mode) |
| 2 | **Ship PR sign-off** — review of `## API Changes` / `## Scripts Changed` before commit/push/PR | `ship_library` / `ship_workspace` |
| 3 | **Heart YELLOW acknowledgement** — warnings surfaced, proceed only on explicit go-ahead | ship gate (`skills/WORKFLOW.md` "Heart readiness gate") |
| 4 | **Merge / issue close** — offered after shipping, never automatic | post-ship |
| 5 | **Version ask** — the minor-version choice | `pre_build` |
| 6 | **Post-merge cleanup confirmation** — worktree removal, branch deletion, registry moves | `ship_*` cleanup |

## Levels × checkpoints

| Checkpoint | `safe` | `supervised` | `human-required` |
|------------|--------|--------------|------------------|
| Plan approval | write plan to the issue, proceed | write plan to the issue, proceed | present + wait |
| Ship PR sign-off | proceed through the autonomous-ship gate; end at PR-open | park (`awaiting-input`), question to the issue, continue elsewhere | present + wait |
| Heart YELLOW | park — human checkpoint at **every** level | park | present + wait |
| Heart RED | stop, report | stop, report | stop, report |
| Merge / close | human, always | human, always | human, always |
| Version ask | n/a — release is always `human-required` | n/a | ask |
| Cleanup | proceed + log | proceed + log | confirm |

The difference between `safe` and `supervised` is the ship step and judgment
gates: `safe` runs end-to-end to an open PR; `supervised` proceeds wherever the
path is mechanical but converts each judgment gate into a batched question on
the issue and moves on (**checkpoint-and-continue** — the question is written
with enough context to answer cold, the task parks as `awaiting-input` in
`active.md`, and the session advances to the next independent step or task
rather than blocking).

## Per-work-type caps

A prompt's header never exceeds its work-type cap. The **effective level** is
`min(header, cap)`; a missing header means `human-required`.

| Work-type | Cap | Why |
|-----------|-----|-----|
| `refactor`, `test`, `maintenance` | `safe` | behaviour-preserving by definition; tests + review are a near-complete gate |
| `feature`, `bug`, `docs` | `supervised` | until the calibration log justifies raising |
| `research`, `experiment` | `supervised` | output is judgment-shaped |
| `release` | `human-required` | always; no autonomy level ships a release |

Raising a cap is a doctrine edit to this page and must cite calibration-log
evidence.

## Activation

- Levels bind **only** when the human launches with an explicit `--auto`.
  Default invocations behave exactly as before this page existed —
  present-and-wait at every checkpoint.
- Opt-in per invocation, never ambient: no config flag, no environment
  variable, no "remembered" mode.

## The autonomous-ship gate

An unattended ship (checkpoint 2 at `safe`) requires **all four**, no
substitutions:

1. worktree pytest on the affected repos (full suite),
2. the curated smoke-test subset,
3. review-faculty verdict **CLEAN**,
4. Heart **GREEN**.

The gate's audit and precise composition are `PyAutoMind/feature/autonomy/`
task 3; the review faculty is task 2. **Until both land, no run ships
unattended** — `--auto` ends at ship sign-off regardless of level. A failed
gate downgrades the run to a human checkpoint: state written to the issue,
nothing force-shipped.

## Calibration log

`PyAutoMind/autonomy_log.md` — append-only. Every `--auto` run appends a row
at PR-open (or on parking):

```markdown
| date | task | effective level | gates (tests/smoke/review/heart) | outcome |
```

Outcome ∈ `merged-unchanged` / `amended` / `rejected` / `parked`. This is the
evidence base for raising or lowering caps — autonomy grows by demonstrated
calibration, not by optimism.

## Hard invariants (every level, no exceptions)

- **Merge and issue-close are human acts.** An explicit future flag may extend
  autonomy to merge; it does not exist and must not be assumed.
- **Autonomous runs end at PR-open**, with the PR body carrying the plan, the
  review verdict, test/smoke counts, and a validation checklist.
- **Never modify code to make tests or smoke tests pass.**
- **Heart YELLOW/RED is never acknowledged autonomously.**
- **Never rewrite history** (`AGENTS.md` rules apply verbatim to autonomous
  runs).
- The `Autonomy:` header is a model's own estimate. The caps, the explicit
  `--auto` launch, and the calibration log are what make consuming it
  defensible — none of the three is optional.

## Consumers

Today: **none** — this page is doctrine ahead of implementation, by design.
Consumption lands with the `PyAutoMind/feature/autonomy/` series: task 4
(`--auto` through `start_dev → ship_*`), task 5 (checkpoint-and-continue),
task 7 (queue runner). Skills must link here rather than copying the tables.
