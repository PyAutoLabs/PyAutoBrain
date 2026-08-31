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

### Multi-repo autonomy experiment — 2026-08-30

`infer_autonomy` (the conception heuristic in
`agents/conductors/intake/_intake.py`) returned `supervised` whenever a prompt
named more than one repo. Repo count is *blast radius*, and blast radius is
already priced — `estimate_difficulty` adds 2 points per repo beyond the first.
This field is supposed to encode whether a **human's judgement** is required, and
a change touching four repos mechanically needs no more judgement than the same
change touching one. The trigger is removed.

**This is an experiment, not a graduation, and it is deliberately not justified
by the calibration log.** The tempting argument — 238 rows, zero `rejected` —
does not survive reading: the rows run densely 2026-07-08 → 08-01 and then stop
(about seven cover all of August, against 332 completion records), so the base is
human-in-session work rather than the unattended regime this would license; the
human was in the loop for nearly every row, so failures were corrected before
they could become rows; `rejected` is structurally unreachable (a withdrawn
five-PR mechanism was logged `reverted`, a human rejecting a run's
recommendation `amended`, and two rows say verbatim "NOT a clean row for
graduation purposes"); and most of all, the 2026-07-09 review raised the
work-type caps **because** this heuristic stayed conservative about multi-repo
work. Every clean row was produced with the guard switched on. Evidence
collected under a safety device cannot license removing the device.

**Measured effect** (all 153 `draft/` prompts, re-derived, nothing written):
`safe` 30 → 55, `supervised` 117 → 92, `human-required` unchanged at 6.
`repo_count > 1` is the *sole* supervised trigger for **25** prompts — the
largest single one, ahead of `large`-or-above (20) and architectural risk (17).

Note what that also refutes: the multi-repo rule was **not** the cause of the
backlog reading 120-of-137 `supervised`. Those levels are declared, written by
earlier intake runs, and the triggers overlap heavily. Removing this one is
worth doing on its merits and frees 25 prompts; it is not the unblocking of the
backlog it was first taken for, and phase 3's ship-sign-off change is where that
actually lives.

**A first draft of this change also added `human_judgement` as a supervised
trigger in `repo_count`'s place. It was measured and reverted**: `safe` fell to
24, because the ambiguity keywords fire on 63% of prompts and catch well-written
ones indiscriminately. It was the same mistake as the rule it replaced — a loose
proxy standing in for a judgement it does not measure. Recorded here so nobody
re-proposes it.

**Terms of the experiment:**

- **20 unattended launches** under the new rule.
- The **independent-model adversarial review leg** is mandatory for them. Until
  that leg exists (batch epic phase 3), the experiment **does not start** — the
  rule change ships, but no launch counts toward the window.
- Calibration rows written **per work-type**, since the graduation rule is
  per-work-type and the figure usually cited is an aggregate.
- A new outcome value, **`rejected-at-review`**, stamped by the **human** in
  their review slot. Without it the demotion trigger cannot fire, and an
  experiment that cannot fail is not evidence.
- **Revert condition:** any `rejected-at-review` row, or a window that closes
  with fewer than 20 launches and no clean read, reverts this edit and restores
  the `repo_count > 1` trigger.

### The scheduled-nightly standing grant — 2026-07-09

The human decided (2026-07-09, recorded in
[PyAutoBuild#127](https://github.com/PyAutoLabs/PyAutoBuild/issues/127)) that
the **scheduled nightly release path** is human-pre-authorised as a standing
grant: once armed, nightly runs perform full live PyPI releases unattended,
with no per-release human approval. This is a deliberate, dated, scoped
exception to the release cap above — not a weakening of it.

**Scope — the grant attaches to the schedule, not to the pipeline:**

- It covers exactly the scheduled nightly driver defined in
  `PyAutoHands/docs/nightly_release_design.md`: activity-gated (quiet nights
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

### What a batch launch is — 2026-08-30

A batch dispatches work into a shift that outlasts the human's session, and
waves of it may start hours after they left. Read against the rule above, a wave
firing at 4am under an approval given at 17:00 is a **stored grant** — the exact
shape the corrective-PR section voids ("a stored, reused or 'standing'
authorization does not count — it must be for this RED, **now**"). So the term
is defined here rather than left for an implementation to settle by accident:

**A batch dispatch is ONE launch.** Specifically:

- Its **membership is fixed at approval**, in the slot, by the human. A task not
  on the approved list is not launched, however ready it looks and however much
  budget is left.
- Its **grant expires at the end of the shift.** A member not dispatched within
  it returns to the queue and needs the next slot's approval.
- Its **terms are written down** — members, the acknowledged Heart reason set,
  the effective level per member — in `batches/<date>-<am|pm>.md`, where they can
  be read afterwards against what actually happened.
- **The human performs the dispatch.** A scheduler may build the review packet
  and may wake a session, but the act that starts work on the approved list is
  theirs. This is the line that keeps "never ambient" true: the schedule carries
  the *timing*, never the *authority*.

What this deliberately does **not** grant: a standing batch, a recurring
approval, or a config flag that makes the next batch launch itself. Each shift
is approved in its own slot, or it does not run.

**Amendment 2026-08-31 — the shift is declared, not scheduled.** The text above
leaves "the end of the shift" to be settled by whatever rhythm the workflow
happens to run on. It is settled here instead, by the human: at dispatch they
state **`review-at:`** — an ISO timestamp for when they expect to be back — and
**the shift is the interval dispatch → `review-at:`**. It is written into
`batches/<date>-<am|pm>.md` beside `dispatched:`, and the grant expires there,
whether or not they actually return. A slot is whenever the human comes in;
there is no daily baseline and no second-slot assumption, so the horizon cannot
be inferred and must be stated. A batch dispatched with no `review-at:` in its
record has no defined expiry, which is the stored grant this section exists to
forbid — so it is not dispatched until the human says when.

*Revert condition:* if a batch is ever found to have launched work its approval
list did not name, batching returns to per-task `--auto` until the cause is
found.

## Checkpoint-and-continue (`supervised`)

The operational mechanics of the levels-table behaviour: a run writes a
clear question and stops at a judgment gate, and auto-advances between tasks
otherwise.

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
  up per the prompt's fallback clause and the task parks as blocked; it never
  becomes a question for the human to answer.

Ship sign-off and merge park the *task*, never bypass the gate —
checkpoint-and-continue frees the human's session, not the checkpoint.

### Decide-and-flag (batch launches only) — 2026-08-30

Park-and-ask is the right behaviour when a human is one message away. In a shift
it costs the whole shift: the run stops, the question waits until the slot, and
the task needs a second batch. So a run under a **batch launch** may, at a
judgement gate, take the more reversible option and record it instead of parking.

**Narrowly**, because the agent deciding is the poorest available judge of its
own decision's scope. The base rate is measured, not feared: **68 of 332
completion records in 2026-08 (20%) carry a correction or a retraction**,
including one whose own claim was later marked "FALSE when this record was
written". And *reversible* is the wrong axis on its own — an API-philosophy fork
decided on behalf of an external reporter is trivially reversible in git and
irreversible in public.

The limits, all of them:

- **At most ONE flagged decision per PR.** A second judgement gate parks the run
  exactly as today. One is a note a reviewer can hold in their head; three is a
  design review they did not agree to do.
- The PR body must state the **rejected alternative** and the **one-command
  revert**. *If the run cannot write the revert, the decision was not reversible*
  — park.
- **Never** where the decision touches a public API, a default value, an error
  contract, or a file named in an external reporter's issue.
- **Never** for a `judge`-tier task (`Consequence:` — REFERENCE.md "The
  review-cost model"). A tier that costs a PI's quarter-hour is one where the PI
  makes the call.
- The PR carries a `decision-taken` label so the review surface sorts it above
  clean work, and the calibration row names it.

This moves review debt from the issue tracker into the diff, which is a real
cost — the diff is where an overloaded reviewer is least able to interrogate a
choice. The cap, the revert line and the tier exclusion are what keep that cost
to one bounded item per PR rather than an unmarked scatter.

*Revert condition:* two flagged decisions the human would not have taken retires
this section; it returns to park-and-ask.

## The autonomous-ship gate

An unattended ship (checkpoint 2 at `safe`) requires **all four legs**, no
substitutions — **plus leg 5 under a batch launch**, where no human is reachable
and the review leg's independence stops being optional. Audited 2026-07-08
(issue #38); each leg carries an applicability rule so "n/a" is a stated fact,
never an assumption:

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
   park to a human checkpoint; BLOCKED → park. When the surface lifted any
   `claims to falsify`, CLEAN carries one disposition line per claim
   (basis-cited / idle / finding — faculty AGENTS.md step 2a); a bare CLEAN
   over a non-empty claims surface is malformed evidence, not CLEAN.
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

5. **Independent adversary** — **added 2026-08-30, required for a BATCH
   launch** (below) and for any run counting toward the multi-repo autonomy
   experiment; optional elsewhere. A second reading of the same diff by a
   **different model from the one that wrote it**, whose job is not to review
   the change but to **falsify its claims — the `Witness:` first**. Run it as
   `pyauto-brain review --task <name> --witness "<the prompt's Witness:>"
   --adversary`.

   Why it exists, and why leg 3 does not already cover it:
   `complete/2026/08/falsified-by-checkpoint-efficacy-review.md` found that the
   review leg on autonomous ships was in practice **the branch's own author**,
   that "a healthy pass and a rote one write the identical ledger row", and that
   the one confirmed-wrong load-bearing claim of its window lived *outside* the
   surface the stage reads — "the stage could not have caught the one escape
   that actually happened". The catches that did happen came from an independent
   model reading the same diff.

   **A self-run adversary leg is an absent leg, not a weak one**, and recording
   it as run is a false ledger row. The verdict is recorded in the calibration
   row alongside the other four.

   *Revert condition:* if the leg produces no finding across 30 runs it is
   ceremony, and this clause is removed rather than left as theatre.

A failed leg downgrades the run to a human checkpoint: state written to the
issue, nothing force-shipped, never modify code to make a leg pass.

### Leg 4 under a batch launch — 2026-08-30

Leg 4 as written assumes a human is reachable: YELLOW passes only where the
reason set is the one acknowledged *at launch*, and any new reason parks the
run. Overnight nobody can acknowledge anything, so a fifteen-hour shift would
ride on that set staying frozen. **It does not stay frozen for an afternoon.**
The log shows a drift count growing 2 → 4 → 6 across a single day, re-asked at
each ship; and a *benign new* reason appearing mid-session from a run's own
sibling merge ("release validation stale: source moved since rehearsal") — which
in a batch means **wave 1 can manufacture the reason that parks waves 2 and 3**.
The 2026-07-09 review records that Heart never read GREEN: every shipped run
went out on an acked YELLOW. The base rate says this leg blocks by default.

That pressure has already produced a violation rather than a park:
`complete/2026/08/cmap-magma-default.md` shipped under a **standing** ack, which
the corrective-PR section below explicitly voids. Doctrine moving deliberately is
the alternative to doctrine bending under load.

So, **for a batch launch only**:

- At slot time the human acknowledges a **named reason set for the shift**,
  written verbatim into `batches/<date>.md` and into each member's `active.md`
  `- heart-ack:` block.
- A run parks on a new **RED**, or on a new **YELLOW reason whose repo
  intersects the run's own repos**. A new YELLOW elsewhere in the organism does
  not park it — the reason is out of the branch's blast radius, and legs 1-3 and
  5 gate the branch itself.
- A reason **generated by an earlier member of the same batch** is named as such
  in the batch record and does not park later members.
- The grant **expires with the shift** — that is, at the `review-at:` the human
  stated at dispatch (see the 2026-08-31 amendment above). It is not standing,
  not ambient, and not carried into the next batch.

Unchanged: RED still parks at every level; YELLOW is still never acknowledged
*autonomously* — the acknowledgement is a human act performed in the slot, and
this section only defines how far it reaches.

*Revert condition:* one escape traceable to a YELLOW reason this section let
through restores the exact-set rule for batches.

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
| date | task | effective level | gates (tests/smoke/review/heart[/adversary]) | outcome |
```

Outcome ∈ `merged-unchanged` / `amended` / `rejected` / `rejected-at-review` /
`parked` / `corrective` (`corrective` records a use of the human-authorized
corrective-PR exception above — not an `--auto` run, but logged so the
exception's use is auditable alongside the autonomy rows). This is the evidence
base for raising or lowering caps — autonomy grows by demonstrated calibration,
not by optimism.

**`rejected-at-review` — added 2026-08-30.** Stamped by the **human**, in their
review slot, when they would not have merged what the run produced. It exists
because `rejected` has never once been used in 238 rows, and reading why shows
the category was being routed around rather than earned: a human rejecting a
run's recommendation was logged `amended`, and an entire shipped mechanism
withdrawn on reflection — five PRs closed, branches deleted — was logged
`reverted`. A demotion trigger nothing can pull is not a safety device, and a
zero-`rejected` record produced that way is not evidence of anything. Use the
human-stamped value for any judgement about whether autonomy should rise.

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
- **The Brain reads no network except one opt-in flag.** Every conductor and
  faculty is stdlib-only and offline. The sole exception is
  `intake reconcile --repo <target>` (PyAutoBrain#223), which makes a cached
  shallow clone of the named repo to check whether identifiers a prompt names
  already exist upstream. It is **read-only, opt-in and non-default**: without
  the flag no clone, socket or subprocess is used, and a test detonates on any
  attempt. It ranks prompts for human review in a `needs-review` band and never
  emits a shipped verdict, so it retires nothing on its own. Any *further*
  network surface in the Brain is a new decision, not covered by this line.
- The `Autonomy:` header is a model's own estimate. The caps, the explicit
  `--auto` launch, and the calibration log are what make consuming it
  defensible — none of the three is optional.

## Consumers

- `start_dev` — `--auto` usage, effective-level computation, plan-to-issue
  for `safe`, launch-acknowledgement recording (its "--auto mode" section).
- `ship_library` / `ship_workspace` — the four-leg gate at step 4 (five under a
  batch launch), stop at
  PR-open, validation checklist, calibration append; the RED-handling step
  points here for the human-authorized corrective-PR exception.

Skills must link here rather than copying the tables.
