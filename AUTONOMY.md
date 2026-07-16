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
| Heart YELLOW | park, unless the reason set was human-acknowledged at launch (see the autonomous-ship gate) | same as `safe` | present + wait |
| Heart RED | stop, report | stop, report | stop, report — a human may separately invoke the corrective-PR exception (below), which is not an autonomy level |
| Merge / close | human, always | human, always | human, always |
| Version ask | n/a — release stays `human-required` (sole exception: the scheduled-nightly standing grant, dated below) | n/a | ask |
| Cleanup | proceed + log | proceed + log | confirm |

The difference between `safe` and `supervised` is the ship step and judgment
gates: `safe` runs end-to-end to an open PR; `supervised` proceeds wherever the
path is mechanical but converts each judgment gate into a batched question on
the issue and moves on — **checkpoint-and-continue**, defined in its own
section below.

## Per-work-type caps

A prompt's header never exceeds its work-type cap. The **effective level** is
`min(header, cap)`; a missing header means `human-required`.

| Work-type | Cap | Why |
|-----------|-----|-----|
| `refactor`, `test`, `maintenance` | `safe` | behaviour-preserving by definition; tests + review are a near-complete gate |
| `feature`, `docs` | `safe` at Difficulty ≤ `medium`; `supervised` at `large` and above | raised 2026-07-09 on calibration evidence (see "Calibration review — 2026-07-09") |
| `bug` | `supervised` | the log holds too few bug rows to justify raising (graduation rule below) |
| `research`, `experiment` | `supervised` | output is judgment-shaped |
| `release` | `human-required` | always, for manual and agent-initiated releases; the **sole** exception is the scheduled-nightly standing grant below (2026-07-09) |

Raising a cap is a doctrine edit to this page and must cite calibration-log
evidence.

### Graduation and demotion

A cap may rise one level only when the calibration log holds **≥ 10 clean
rows** for that work-type since the last doctrine edit — *clean* means outcome
`merged-unchanged`, or `amended` where the amendment was a human-directed
scope addition rather than a correction of the run's own work — and **zero
`rejected`** rows over the same window. Any `rejected` row demotes that
work-type's cap one level immediately, pending a review that cites the row.
Both directions are dated doctrine edits to the table above, citing rows.

### The scheduled-nightly standing grant — 2026-07-09

The human decided (2026-07-09, recorded in
[PyAutoBuild#127](https://github.com/PyAutoLabs/PyAutoBuild/issues/127)) that
the **scheduled nightly release path** is human-pre-authorised as a standing
grant: once armed, nightly runs perform full live PyPI releases unattended,
with no per-release human approval. This is a deliberate, dated, scoped
exception to the release cap above — not a weakening of it.

**Scope — the grant attaches to the schedule, not to the pipeline:**

- It covers exactly the scheduled nightly driver defined in
  `PyAutoBuild/docs/nightly_release_design.md`: activity-gated (quiet nights
  skip, loudly), Heart-GREEN-gated (STALE/YELLOW/RED stop the run — on this
  path YELLOW is never acknowledged by anyone; there is no force input), and
  kill-switchable (the `NIGHTLY_RELEASES` repo var).
- **Manual and agent-initiated releases remain `human-required`, unchanged.**
  No agent may dispatch or invoke the nightly path to route a release around
  a human — a release wanted *now* is a manual release and takes the human
  gate.
- `pre_build`'s minor-version ask is automated on this path only (the date
  scheme derives it, `YYYY.M.D.1`); the interactive ask is unchanged for
  manual releases.
- The human's role on this path: the kill switch, responding to pages
  (any stop/red/anomaly notifies), and reviewing the `/wake_up` digest of what
  shipped.

Revoking the grant is one act (unset `NIGHTLY_RELEASES`) and needs no
doctrine edit; removing this section is the doctrine edit that retires it.

## Activation

- Levels bind **only** when the human launches with an explicit `--auto`.
  Default invocations behave exactly as before this page existed —
  present-and-wait at every checkpoint.
- Opt-in per invocation, never ambient: no config flag, no environment
  variable, no "remembered" mode.

## Checkpoint-and-continue (`supervised`)

The operational mechanics of the levels-table behaviour, generalised from
`register_and_iterate`'s proven contract (its "writes a clear question and
stops … auto-advances between tasks"):

- **Trigger** — any judgment gate the levels table marks as a question for
  `supervised`: ship sign-off, a scope/design fork the plan didn't settle, an
  ambiguous classification, a FINDINGS verdict the run cannot resolve
  mechanically. Mechanical stretches never pause.
- **The question** — one batched comment per pause on the task's GitHub
  issue, written to be answerable cold: what was being done, the fork and the
  options, the run's recommendation, and what happens on each answer. Never a
  trickle of one-liners (match the conversational issue-update style).
- **Parking** — set the task's `active.md` entry to `status: awaiting-input`
  and add `- question: <issue-comment-url>`; push Mind. `active.md` is the
  shared cross-environment state — no new store, no daemon.
- **Continue policy** — in order: the next *independent* step of the same
  task (one whose outcome no pending answer can invalidate); else the next
  queued task; else end the run cleanly with a summary of every parked
  question.
- **Resume** — the human answers on the issue (or relaunches); any
  environment reads `active.md`, finds `awaiting-input` + the question
  pointer, and continues from the recorded state.
- **Hard blockers** are not questions — a thing that cannot work is written
  up per the prompt's fallback clause and the task parks as blocked, exactly
  as `register_and_iterate` does today.

Ship sign-off and merge park the *task*, never bypass the gate —
checkpoint-and-continue frees the human's session, not the checkpoint.

## The autonomous-ship gate

An unattended ship (checkpoint 2 at `safe`) requires **all four legs**, no
substitutions. Audited 2026-07-08 (issue #38); each leg carries an
applicability rule so "n/a" is a stated fact, never an assumption:

1. **Tests** — worktree pytest (full suite, `-x`) on every **shipped** repo,
   *plus* every downstream library repo when the diff touches public API
   (review-surface `python-source` flag with Removed/Renamed/Changed-Signature
   entries). The audit found the shipped-repos-only contract papers over
   downstream breakage with human PR review — an autonomous run doesn't have
   that reviewer, so it runs the dependents' suites too. Repos with no test
   dir (organism/doc repos): leg is n/a, stated in the PR body.
2. **Smoke** — the curated `smoke_tests.txt` subsets (Heart's `smoke_test`
   skill, all six workspaces by default) run with the task worktree's
   `activate.sh` sourced, so they exercise the branch. Applies where the
   changed repo has a downstream script surface; organism/doc-only changes:
   n/a, stated in the PR body. Never grow the curated lists to make this leg
   feel stronger.
3. **Review** — review-faculty verdict **CLEAN**
   (`agents/faculties/review/AGENTS.md`). FINDINGS → resolve and re-review, or
   park to a human checkpoint; BLOCKED → park.
4. **Heart** — verdict **GREEN** or **STALE**, or **YELLOW whose reason set is
   contained in the set the human acknowledged at launch**. Heart observes
   organism state, not the branch (the audit confirmed its legs never see
   feature branches). **STALE** is Heart's freshness tier (evidence missing or
   expired, nothing known-bad — `PyAutoHeart/heart/readiness.py`): it passes
   this leg because an evidence gap is organism-scope, not branch-scope, and
   legs 1–3 gate the branch itself; the PR body lists the stale reasons.
   Releases are unaffected — they always require GREEN. A verdict from a Heart
   without the tier behaves as before. For YELLOW, the acknowledgement binds
   to the *exact reason list* at launch, for that launch only — any new
   reason, or RED, parks the run. Never ambient, never carried across
   sessions.

A failed leg downgrades the run to a human checkpoint: state written to the
issue, nothing force-shipped, never modify code to make a leg pass.

## Corrective-PR exception for Heart RED (human-authorized)

Heart RED forbids commit, push and PR-open at every autonomy level (the levels
table). But Heart cannot clear a RED until the fixing source reaches `main`,
fresh wheels are built, and release-integration validation passes — so a source
fix that directly repairs the exact defect named by the RED reason cannot be
shipped, and recovery is impossible without violating policy. This section is
the **one** authorized way through that deadlock, and it is a **human act**, not
an autonomy level: it never fires under `--auto` (the hard invariant "Heart
YELLOW/RED is never acknowledged autonomously" stands verbatim — an unattended
`--auto` run on RED still stops and reports). A human invokes it, live, per
incident.

- **Trigger** — Heart is RED, and a source fix directly repairs a defect named
  by a RED reason.
- **Authorization** — explicit, contemporaneous human authorization that
  (a) quotes the exact RED reason string and (b) approves the specific
  corrective issue. It is recorded as a human comment on that issue; a stored,
  reused or "standing" authorization does not count — it must be for this RED,
  now. **The agent provides the quote.** When the circumstance arises, the agent
  surfaces the exact RED reason string(s) **verbatim from Heart's current
  verdict** (`pyauto-heart readiness`) together with the specific corrective
  request it is asking the human to approve — so the human authorizes what the
  agent put in front of them, never a string reconstructed from memory. It is the
  human's judgement, on the agent-surfaced reason, that authorizes.
- **Permitted, and nothing else** — commit, push, and opening **one**
  pending-release feature PR whose issue, plan and diff all map to the named
  reason.
- **Forbidden** — automatic merge, issue close, release, release rehearsal, and
  any unrelated scope. Merge stays a separate human act; **every release stays
  blocked while Heart is RED**.
- **Recorded in four sinks** — the authorization, the exact RED reason, the
  causal mapping (reason → issue → plan → diff), the tests, and the validation
  plan are written to: the **GitHub issue**; the **PR body**; the corrective
  task's **`PyAutoMind/active.md`** entry (a `- corrective-red:` block naming
  the reason and pointing at the authorization comment); and a
  **`autonomy_log.md`** row whose outcome is tagged `corrective` (it is not an
  `--auto` run, but the calibration log still records that the exception was
  used).
- **Multiple RED reasons** — the authorization names exactly one. The PR body
  states which reason the diff clears and that any sibling RED reasons remain,
  so Heart stays RED and release stays blocked until every reason is cleared by
  its own corrective PR. A corrective PR never claims to clear a reason it does
  not address.

**Failure behaviour — park without shipping** (set the `active.md` entry to
`status: blocked` or `awaiting-input`, write why on the issue, open no PR):

- **Mixed-scope diff** — the diff touches anything beyond the named reason's
  fix. The narrow permission covers only the causal fix; bundle nothing with it.
- **Stale or changed RED reason** — re-read Heart's verdict at ship time; if the
  named reason string has changed, split, or cleared, the authorization no
  longer matches the world. Park and re-authorize against the current verdict.
- **Missing evidence** — no causal mapping, no tests, or no validation plan.
- **Review finds the patch is not causal** — the review faculty (or a human
  reviewer) judges the diff does not actually repair the named reason.

**Recovery sequence** — the exception opens a PR; it does not resume release
work. That resumes only along this path:

1. A **human merges** the corrective PR (a separate human act — the exception
   never merges).
2. **Fresh post-merge wheels are built** and **release-integration validation**
   is re-run on `main`.
3. Heart emits a **new verdict** over that fresh evidence.
4. Release work resumes only on that new verdict, and release stays
   `human-required` throughout (the release cap is untouched by this section).

## Calibration log

`PyAutoMind/autonomy_log.md` — append-only. Every `--auto` run appends a row
at PR-open (or on parking):

```markdown
| date | task | effective level | gates (tests/smoke/review/heart) | outcome |
```

Outcome ∈ `merged-unchanged` / `amended` / `rejected` / `parked` / `corrective`
(the last records a use of the human-authorized corrective-PR exception above —
not an `--auto` run, but logged so the exception's use is auditable alongside the
autonomy rows). This is the evidence base for raising or lowering caps — autonomy
grows by demonstrated calibration, not by optimism.

### Calibration review — 2026-07-09

First review, over 59 rows (2026-07-08 → 2026-07-09): **zero `rejected`**;
26 runs reached merge — 23 `merged-unchanged`, 3 `amended`, and all three
amendments were human-directed scope additions mid-run, not corrections of the
run's own work. All 3 `safe`-level rows (refactors) merged unchanged through
the four-leg gate. Human ship sign-off added no delta in 23 of 26 merged
supervised runs — exactly the evidence the caps table anticipated.

Result: `feature` and `docs` raised to `safe` at Difficulty ≤ `medium`. The
conception heuristic (`infer_autonomy`) already marks large, multi-repo and
architecturally risky prompts `supervised`, so the work-type cap was the
binding clamp for small/medium single-repo work; raising it makes the
already-conservative header effective. `bug` stays `supervised` — the window
holds almost no pure bug rows.

One constant across all 59 rows: Heart never read GREEN — every shipped run
went out on an acked YELLOW. That is ack-fatigue risk, addressed by making
Heart's verdict distinguish stale evidence from bad evidence (the freshness
tier), never by weakening leg 4.

## Hard invariants (every level, no exceptions)

- **Merge and issue-close are human acts.** An explicit future flag may extend
  autonomy to merge; it does not exist and must not be assumed.
- **Releases are human acts, with one dated exception.** The scheduled-nightly
  standing grant (2026-07-09, above) is the only path that ships a release
  without a per-release human; it is activity-gated, Heart-GREEN-gated and
  kill-switchable. Every other release is `human-required`.
- **Autonomous runs end at PR-open**, with the PR body carrying the plan, the
  review verdict, test/smoke counts, and a validation checklist.
- **Never modify code to make tests or smoke tests pass.**
- **Heart YELLOW/RED is never acknowledged autonomously.** A launch-time
  human acknowledgement of a named reason set is a human acknowledgement — it
  binds to that exact set, for that launch, and never extends to new reasons.
- **The corrective-PR exception for Heart RED is a contemporaneous human act**
  (the section above), never reachable under `--auto`. It permits only commit,
  push and opening one pending-release PR that repairs the named RED reason —
  never merge, close, release or unrelated scope; every release stays blocked
  while Heart is RED.
- **Never rewrite history** (`AGENTS.md` rules apply verbatim to autonomous
  runs).
- The `Autonomy:` header is a model's own estimate. The caps, the explicit
  `--auto` launch, and the calibration log are what make consuming it
  defensible — none of the three is optional.

## Consumers

- `start_dev` — `--auto` usage, effective-level computation, plan-to-issue
  for `safe`, launch-acknowledgement recording (its "--auto mode" section).
- `ship_library` / `ship_workspace` — the four-leg gate at step 4, stop at
  PR-open, validation checklist, calibration append; the RED-handling step
  points here for the human-authorized corrective-PR exception.
- `run_queue` — the generic queue loop: launching it is the batch's `--auto`
  activation; per-entry effective-level dispatch, `PARKED` checkpointing, RED
  stops the run.
- `register_and_iterate` — the pytree instance of `run_queue`, and the origin
  of checkpoint-and-continue; its gates reference the general sections here.

Skills must link here rather than copying the tables.
