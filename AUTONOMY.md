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
| 4 | **Merge / issue close** — by the declared `Consequence:` tier: `notify` / `glance` merged in-turn by the shipping session on green CI; `judge` or undeclared offered after shipping, never automatic ("Merge authority follows Consequence", 2026-10-02) | post-ship / `/prm` |
| 5 | **Version ask** — the minor-version choice | `pre_build` |
| 6 | **Post-merge cleanup confirmation** — worktree removal, branch deletion, registry moves | `ship_*` cleanup |

## Levels × checkpoints

| Checkpoint | `safe` | `supervised` | `human-required` |
|------------|--------|--------------|------------------|
| Plan approval | write plan to the issue, proceed | write plan to the issue, proceed | present + wait |
| Ship PR sign-off | proceed through the autonomous-ship gate; end at PR-open | park (`awaiting-input`), question to the issue, continue elsewhere — except under an explicit `--auto` launch, where it resolves to decide-and-flag (below; 2026-09-07) | present + wait |
| Heart YELLOW | park, unless the reason set was human-acknowledged at launch (see the autonomous-ship gate) | same as `safe` | present + wait |
| Heart RED | stop, report | stop, report | stop, report — a live human may separately invoke the development override or corrective-PR exception below; neither is an autonomy level |
| Merge / close | by declared `Consequence:` (2026-10-02 section) | by declared `Consequence:` | by declared `Consequence:` |
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
| `research` | `supervised` | output is judgment-shaped |
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
  (any stop/red/anomaly notifies), and reviewing the Brain board digest of what
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

An interactive `supervised` run parks at ship sign-off exactly as above —
the human is one message away, so the round-trip is free. Under an explicit
`--auto` launch the ship checkpoint instead resolves to **decide-and-flag**
(next section, extended to it 2026-09-07): the run ships to an open PR and the
decision is flagged there. A `decision-taken` PR is never auto-merged — its
merge stays a human act whatever its tier ("Merge authority follows
Consequence"), and no run ever bypasses the gate — checkpoint-and-continue frees the human's session, not the
checkpoint.

### Decide-and-flag (`--auto` launches) — 2026-08-30, extended 2026-09-07

Park-and-ask is the right behaviour when a human is one message away. Under an
unattended launch it costs the whole run: the run stops, the question waits until
the human next comes in, and the task needs a second dispatch. So a run under an
explicit **`--auto` launch** — a batch launch included — may, at a judgement
gate, take the more reversible option and record it instead of parking.

**Extended 2026-09-07 to every explicit `--auto` launch, and to the ship
checkpoint of an effective-`supervised` run.** The human's direction
(2026-08-31): *"I dont really want these parked at ship judgements, ideally we
send off a batch and then dont think about it again, the parked thing is an
annoying middle ground which requires human time."* The argument: every
autonomous run already ends at PR-open with merge left to the human, so **the PR
review IS the approval the `supervised` level exists to provide**. A mid-run park
at ship sign-off is a redundant *second* checkpoint — it costs a GitHub-issue
round-trip before a PR even exists, and then asks the human for the same
judgement again at merge. The evidence, 2026-08-31: two supervised-capped
`--auto` runs took decide-and-flag (PyAutoFit#1554, PyAutoMemory#76) and gave
exactly one review surface; three took the park branch (PyAutoHands#272,
PyAutoFit#1552, euclid#47) and each needed a separate human judgement before a PR
existed. The scope is **explicit `--auto` launches only** — an interactive
`supervised` run keeps park-and-ask, because there the human is one message away
and the round-trip is free. `human-required`, `Unattended: never` and
`Blocked-by:` are unchanged and never run unattended. Every limit below is
unchanged, **including "never for a `judge`-tier task"**: a `supervised` run that
reaches a judge-tier gate other than ship sign-off still parks.

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
this section; it returns to park-and-ask. Or one `supervised` `--auto` run
opening a PR the human would have wanted stopped before it existed — the ship
checkpoint returns to park-and-ask (2026-09-07).

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
4. **Heart** — the **scoped development-ship verdict** (changed 2026-11-12,
   PyAutoHeart#340; ruling M2.1 in "M2 rulings — 2026-11-12" below):
   `pyauto-heart readiness --dev --repos A,B --json`, with the repos taken
   from the task's `repos:` in `PyAutoMind/active.md`
   (`consult_vitals_verdict --repos "$(active_task_repos <task>)"`). Only CI
   on `main` of the touched repos and their dependants blocks; every other
   reason comes back in `shown_reasons` and is listed in the PR body without
   blocking. A touched repo on Heart's `not_heart_gated:` list (profiling,
   inference, assistants, visualization, Scientist, Broca, Cortex; ruling
   2026-11-13, PyAutoHeart#343) is *gate-deferred*: shown, never STALE, and
   its PR checks decide at merge — at least one completed check, all green,
   or the merge is the human's. Only **GREEN** passes. **STALE** — in-scope evidence missing,
   unfinished, or older than 6 h — **never passes**: re-check, or park. With
   **no Heart CLI** (a web session) the one fallback is the *published*
   organism-wide feed: GREEN and under 6 h old passes, because it is at least
   as strict as any scope; anything else parks. Any other scoped read that
   cannot be made (an empty `repos:`, a Heart without the gate, an unknown
   repo name) is "unknown" and parks. Until this change the leg
   read the whole-organism verdict and let STALE pass; the scoped verdict has
   no YELLOW tier, so the YELLOW acknowledgement below (bound to the *exact
   reason list* at launch, for that launch only) applies only if a YELLOW
   verdict is ever returned. Releases are unaffected — they ask the unscoped
   verdict and always require GREEN.

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
- A reason **generated by an earlier member of the same batch** does not park
  later members — but that classification is not the run's to make
  (2026-08-31): it is valid **only where the new YELLOW reason matches an
  `expected-effects:` line the human wrote into the batch record at
  dispatch** ("member X merges into PyAutoArray and may stale release
  validation"). A run attributing a new reason to its sibling on its own
  authority is an autonomous acknowledgement, which the hard invariants
  forbid — the party with the incentive to ship does not get to write its own
  licence. No matching line, the run parks.
- The grant **expires with the shift** — that is, at the `review-at:` the human
  stated at dispatch (see the 2026-08-31 amendment above). It is not standing,
  not ambient, and not carried into the next batch.

Unchanged: RED still parks at every level; YELLOW is still never acknowledged
*autonomously* — the acknowledgement is a human act performed in the slot, and
this section only defines how far it reaches.

**How a member learns the shift's grant — 2026-08-31.** Dispatch hands a member
only `/start_dev <path> --auto`; nothing in the invocation names a shift. So the
mechanism is the record: **at its leg-4 check a member session reads
`PyAutoMind/batches/<date>-<slot>.md`**, and the `heart-ack:` block there is the
shift's acknowledgement — verbatim, human-written, scoped to that shift. **A
member that finds no batch record treats itself as a solo `--auto` launch**: the
exact-set rule applies, and any new YELLOW parks it. Without this line the leg-4
relaxation above never operates and every batch returns parked questions.

*Revert condition:* one escape traceable to a YELLOW reason this section let
through restores the exact-set rule for batches.

**Which record — 2026-09-02.** A member reads **its own organ's** batch record:
`PyAutoMind/batches/<slot>.md` for a dev member, `PyAutoCortex/batches/<slot>.md`
for a science one (`batch plan --kind cortex` writes it). The two surfaces hold
separate records with separate `review-at:`s, so a member that read the other
organ's would be reading another shift's grant. The "no record → solo `--auto`"
rule above is unchanged for dev members and **inapplicable to a cortex member**:
a science member is never `--auto` — a run is submitted only on the human's
ask and the human rules on it, so there is no autonomous acknowledgement for a
grant to license. A Cortex record therefore carries no `heart-ack:` and no
`expected-effects:` at all (the Cortex's
own `batches/AGENTS.md` drops both: the Heart gates releases, not runs), and
**their absence there is never read as an unacknowledged RED** — the fields are
not missing, they do not exist on that schema.

## Merge authority follows Consequence — 2026-10-02

**Who merges is decided by the task's declared `Consequence:` tier**
(`PyAutoMind/REFERENCE.md` "The review-cost model"), not by its autonomy level.
Approved by the human 2026-10-02; this section is that dated doctrine edit.

| Declared `Consequence:` | Who merges | What the human reads |
|---|---|---|
| `notify` | the **shipping session**: it waits for CI inside its turn, merges on green, then runs the `/prm` close-out itself | the close-out ledger |
| `glance` | the shipping session, exactly as `notify` — **only if the `Witness:` check passed** | a **post-merge summary**; each auto-merge appends one Shadow-window row (below) |
| `judge` | the human, by `/prm` — unchanged | the PR |
| *no header* | the human, by `/prm` — unchanged | the PR |

**Declared means written in the prompt.** A tier the sizing faculty would infer
for a header-less prompt never carries merge authority — a missing header is
`judge` for this purpose, whatever `bin/pyauto-brain sizing` says.

**The evidence** (cited for the grant, as "Graduation and demotion" requires):

- ~200 recent merged PRs across 8 repos carried **0 reviews**, and most merged
  **under an hour** after opening with 1–2 commits — the human merge on this
  organism's own low-consequence work is a click, not a review.
- `PyAutoMind/autonomy_log.md`, first table: **120 `merged-unchanged` / 12
  `amended` / 2 `rejected` / 2 `reverted`**.
- The tier-`notify` Shadow window stood at **13/40, all clean**. The human
  grants `notify` early by this edit rather than waiting out the window, and
  **re-scopes the window to `glance`**.

**The authorization is given at plan time, never assumed later.**

- **Plan approval at `start_dev` is the merge authorization.** The plan must
  state the declared tier and the **merge mode** (`auto-merge on green` or
  `human /prm`); approving that plan authorizes that merge. A plan that does not
  state them authorizes no merge.
- Under **`--auto`** or a **batch**, the launch / slot approval is the
  authorization, bounded exactly as the launch is ("What a batch launch is").
- **Multi-phase epics chain**: a phase that auto-merged hands to the next phase
  without re-asking, and the chain **stops** at a `judge`-tier phase, any
  failure, Heart RED, or scope the approved plan did not name.

**The in-turn wait.** After PR-open, the shipping session waits for CI **inside
its own turn**: one background `gh pr checks <n> --watch` capped at **~60 min**
(the Bash call's own timeout). That is a process of this session, not a timer:
no `send_later`, `ScheduleWakeup`, cron, routine or `subscribe_pr_activity`
(`PyAutoMind/policy/end_at_deliverable.md` stands as written). When it returns,
CI is judged exactly as `/prm` step 2 judges it — every run, every leg — and on
green the merge and close-out run per `skills/prm/` in full. Cap reached, or a
surface with no authenticated `gh` (mobile, web): judge once, merge only if
already green, otherwise report and end; the human runs `/prm`.

**Never auto-merged, at any tier:**

- a PR carrying the **`decision-taken`** label (decide-and-flag);
- a ship under the **Heart RED development override** or the **corrective-PR
  exception** — both keep their own separate human merge command;
- **red, pending or conflicting** CI, or a non-`CLEAN` merge state;
- a **SKIPPED** test leg — skipped is not green.

The `/prm` guards apply verbatim: the **library-first** gate, the
**sibling-branch** proof (every claimed branch merged before close-out) and the
**data-worktree** question. **`gh pr merge` is a bare, unchained Bash call**
(no `&&`, no `;`, no pipe) so the permission layer sees exactly one merge; if
it is denied, stop and report — never retry it another way. On MCP the merge
is the single `merge_pull_request` call, with the same rule.

**The `glance` Shadow window.** Each auto-merged `glance` PR appends one row to
`PyAutoMind/autonomy_log.md` "Shadow window" at close-out, recorded
`merged-unchanged` at merge (`lifecycle.py close … --tier glance --actor
<class>`, "Merge actor and random audit — 2026-11-12"). The human
reads the post-merge summary and **amends the row** if they find something
substantive (`merged-after-substantive-change`), or marks it `reverted`.
`glance` is **confirmed at 20 clean rows**. **Any revert demotes that tier back
to a human `/prm`** immediately, by dated doctrine edit citing the row — and a
reverted `notify` merge demotes `notify` the same way.

**Later step, not now:** GitHub's native `--auto` merge (`gh pr merge --auto`,
`enable_pr_auto_merge`) would let the wait outlive the turn without a timer.
It is not adopted here; it needs its own doctrine edit.

*Revert condition:* any reverted auto-merge demotes its tier (above); an
auto-merge found to have bypassed one of the never-auto-merge rules retires this
section and returns every merge to `/prm`.

## The `glance` Shadow-window ruling — 2026-11-04

**`glance` is confirmed, narrowed.** Ruled by the human 2026-11-04 under the
pre-registered rule (`PyAutoMind/complete/2026/09/prm-shadow-row-notify-tier.md`,
"The decision rule, pre-registered"): grant if no
`merged-after-substantive-change` or `not-merged` row; grant narrowed if every
case falls in one identifiable sub-class; refuse otherwise. This section is
that dated doctrine edit.

**The evidence.** The window stood at **69 counted rows (target 20), all
`merged-unchanged`, all stage 1**, about 21 with no independent review, most
under a non-GREEN Heart. A **spot audit** of 8 rows picked across every risk
class — witness missing or partial, Heart RED override, large library changes
with no independent review, a new public helper and API — returned **8 of 8
`ok`** (audit page
`Science/scratch/shadow_window_audit_2026-11-03/audit.md`). No row was amended.

**What the grant covers.** `glance` auto-merge by the **shipping session,
in-turn** — the 2026-10-02 table, unchanged — subject to one narrowing:

- **A `Witness:` that did not PASS means a human `/prm`.** None, `n/a`,
  partial and waived all count as not PASS. Four audited rows merged on such a
  witness; the 2026-10-02 table already required a pass, and this makes the
  forms explicit.

**Not adopted:** a rule that anything touching a public API, a default or a
library return value is `judge` whatever its declared tier. It was conditional
on the audit finding tier drift; the human marked the three rows that would
have shown it (a new public helper, a new public API surface, a library
return-value change) `ok`. The declared `Consequence:` stays the authority.

**Unattended `glance` opens a stage-2 sub-window.** Merges started by the
watcher ("Shift briefs and unattended `glance`", "Unattended `glance` merges")
are counted apart from the stage-1 rows, in their own table in
`PyAutoMind/autonomy_log.md`. **Each of the first 10 needs the independent
different-model adversary leg actually run** — not "where one is available".
The sub-rule is confirmed or refused on those 10 by the same pre-registered
decision rule; until then, an unattended merge without that leg is not
licensed.

**Ledger accuracy.** The window counts only merges the organism made itself. A
row whose merge was a human-typed `/prm` is re-marked and left out of the
count. Row `fixed-model-json` (PyAutoFit#1708) was checked and stays counted:
the human did not recall typing that `/prm`.

*Revert condition:* any `reverted` row demotes `glance` back to a human `/prm`
immediately, by dated doctrine edit citing the row — stage 1 or stage 2 alike.

## Stage-2 adversary amendment — 2026-11-04

Amends "The `glance` Shadow-window ruling — 2026-11-04" above, the same day,
by the human, at the phase-4b plan of the autonomous-orchestrators epic. This
section is that dated doctrine edit.

**The adversary leg of an unattended `glance` merge may be the same model as
the author** — Opus 5.5 for both, on cost: the alternatives were a more
expensive model (Fable) or a weaker one (Sonnet). What makes it the leg is
**independence, not the model**: a **fresh close-out session** the watcher
starts after CI lands, which did not write the PR, shares none of the worker's
context, **runs the `Witness:` itself** and reviews the diff adversarially
before it merges or refuses (`agents/conductors/batch/closeout_template.md`).
It applies to the first 10 rows of the stage-2 sub-window exactly as the ruling
says; only "different-model" is replaced.

**Why the ruling asked for a different model, and what is given up.** Two
runs of one model share blind spots, so a subtle error the author made is more
likely to pass a same-model reader. Independence of context still catches what
the leg is mostly for — a skipped or overclaimed witness, an unread label, an
ignored Heart state. The stage-2 window is how this is checked.

*Revert condition:* any stage-2 row `reverted`, or amended to
`merged-after-substantive-change`, restores the different-model requirement for
unattended merges at once, by dated doctrine edit citing the row.

## Merge actor and random audit — 2026-11-12

Amends "The `glance` Shadow-window ruling — 2026-11-04" above: it puts that
ruling's "Ledger accuracy" rule into code and replaces hand-picked audits.
Decided by the human 2026-11-12 in the programme session (task M1.4,
PyAutoBrain#606, finding FLOW-2 of the 2026-11-10 ecosystem review): "All three
as recommended". This section is that dated doctrine edit. The ruling itself,
its narrowing and the stage-2 adversary rules are unchanged.

The three decisions, verbatim:

1. **Merge-actor column**, tool-written, classes `human-/prm` |
   `in-turn-human-commanded` | `in-turn-autonomous` | `unattended-watcher` |
   `unknown`; the count **leaves out** `human-/prm` and
   `in-turn-human-commanded`.
2. **Audits** of the glance window are a **seeded 1-in-5 random sample**,
   audited within a week, instead of hand-picked rows.
3. A **`read-by-human` date column** is recorded but does **not** gate the
   count yet (gating is a judge question after the recount).

The stage-1 recount is printed only; if it changes what the 11-04 glance
ruling rests on, that is a separate judge question for the human.

**How it runs.** Both tables in `PyAutoMind/autonomy_log.md` (stage 1 and the
stage-2 sub-window) end in `merge actor` and `read by human`. The class comes
from the writer's explicit flag — `lifecycle.py close … --actor <class>` or
`shadow-row --actor <class>` at `/prm` close-out, and `unattended-watcher` from
the shift watcher — because how a merge started is known only to the session
that started it. The flag is **required** whenever a row is written — a
missing one refuses, so a forgotten flag can never land as a counted
`unknown`: a human-typed `/prm` → `human-/prm`; an in-turn merge on the
human's explicit merge command → `in-turn-human-commanded`; an in-turn tiered
merge with no human command → `in-turn-autonomous`; `unknown` only when passed
explicitly. `gh pr view --json mergedBy,mergedAt` adds the evidence,
`<class> (mergedBy <login>)`, never the class. Rows written before this edit
stop at `stage` and read as `unknown`, which still counts; they are not
rewritten. `lifecycle.py shadow-recount` prints the window by actor and the
historical rows classified from their completion records by a printed keyword
rule; `lifecycle.py audit-sample --seed <n>` draws the audit sample.

**The recount, as printed on 2026-11-12** (completion records, not re-marked):
of the 69 rows the 2026-11-04 ruling rested on, 31 human `/prm`, 10 automatic
or in-turn, 28 not stated. The three rows of 2026-11-12 —
`shift-watcher-state-gaps`, `prompt-sync-explicit-paths`,
`prompt-sync-detached-push`, merged in-turn on the human's explicit merge
command under a Heart RED override — are recorded `in-turn-human-commanded`
and left out of the count.

*Revert condition:* an audit that finds a tool-written merge actor wrong on any
row suspends the actor rule — the count goes back to every in-window row, with
"Ledger accuracy" applied by hand — until the writer is fixed, by dated
doctrine edit citing the row. A `reverted` row still demotes `glance` as the
ruling says.

## M2 rulings — 2026-11-12

Ruled by the human 2026-11-12 at the M1→M2 gate of the autonomous-orchestrators
programme, one ruling per M2 decision sheet; this section is the dated doctrine
record of all six. Each quotes, verbatim, the recommendation the human adopted
from the sheets' index, then names the build issue or the human act it awaits,
and the condition that reverts it. It records the rulings; the doctrine text
each one changes elsewhere in this file is edited by its own build, not here.

**M2.1 Heart branch scope.** *"Yes: enforce library CI for touched repos and
their dependants; show the rest. Feed: 6 h maximum age plus event triggers,
built first. Rule that an over-age feed re-checks or parks, never passes."* A
STALE feed never passes a development ship: over the maximum age the door
re-reads the touched repos' `main` CI at ship time, and an unattended run that
cannot parks. The override row stays, with its reason machine-readable.
Build: PyAutoHeart#340. *Revert condition:* any ship passed by the branch scope
that breaks `main` of a touched repo or a dependant, where the organism-wide RED
would have stopped it — return to the full verdict by dated doctrine edit.

**M2.2 Server-side merge gate.** *"Yes, staged: libraries and tested organs
first, workspaces after a week, Mind after M4.3. Require status checks, not
reviews. `--auto` for notify and glance only. A separate worker identity at
M4."* `judge` stays a human merge; the ban under the corrective-RED path stays.
Awaits a human act: the rulesets are applied by the human with their admin
credential. *Revert condition:* a ruleset that blocks a release, or leaves PRs
pending with no failing check more than twice in a week — set that repo's
ruleset to `disabled` and fix the check list; an auto-merge found to have
passed a never-auto-merge rule withdraws `--auto` by doctrine edit.

**M2.3 Lane fails closed; queue.md is the ranked list.** *"Fail closed in
unattended and cloud sessions only. Keep `queue.md` as a short ranked list,
validated; an empty list stops a shift; sort priority before review-minutes."*
As built: every plan `pyauto-brain batch plan` composes, and every watcher
tick, is unattended, and excludes a backlog draft with no valid `Lane:`, saying
so in the plan and the digest; `batch plan --attended` (a human picking for
their own session) reads an absent Lane as `any`. A brief's named tasks are the
human's own pick and are not gated. Intake refuses to file a new draft whose
lane is neither declared (a `Lane:` header, or the filer's `--lane`) nor
inferred from a resource signal, and says how to declare one. `lifecycle.py check`
fails on a `queue.md` prompt ref that resolves to no draft or active prompt
(`lifecycle.py close` retires a completed task's entry to the footer); an
empty or absent `queue.md` stops an unattended shift's backlog dip (named tasks
still run); below the queue the planner sorts priority, then review-minutes.
Build: PyAutoBrain#614. *Revert condition:* if fail-closed excludes more than a
handful of valid drafts in a week for a missing header, re-run
`bin/lane_backfill.py`; if that does not fix it, return to `any` for attended
filing. If `queue.md` goes two weeks without an edit, replace it with a
per-draft rank header set in a weekly review.

**M2.4 Release builds the rehearsed SHAs.** *"Yes: release the rehearsed
commits even if `main` moved; move the Colab bump off `main`."* The release log
prints the rehearsed commit, the released commit and `identical`. Build:
PyAutoHands#337. *Revert condition:* a release whose tag does not match the
rehearsed commit, or a Colab notebook that installs the wrong version because
the bump is off `main` — return to `ref: main` plus the freeze flag until fixed.

**M2.5 Always-apply rules.** *"Split the safety rules into a short file
imported by the home `CLAUDE.md`; set a size budget for the memory index
(21.8 KB today)."*
Awaits a human act: these are the human's home-folder files — a session may
draft the edits, the human applies them. *Revert condition:* if a new session's
loaded-file list does not show the rules file, or sessions lose the routing
they need, restore the previous files and fall back to importing the whole
workspace guidance file from the home `CLAUDE.md`.

**Quarantine (side ruling).** *"Yes: one retry; quarantine needs a bug task,
expires in 7 days, at most 3, shows YELLOW."* The nightly may retry a failing
script once. A script may be quarantined only with a filed bug task, for at
most 7 days, at most 3 entries at once, never a unit test or an install check;
while any entry is live the release shows Heart YELLOW and the digest lists
them. Build: to build. *Revert condition:* a release that ships with a
quarantined script hiding a real user-facing break — quarantine returns to
human-only.

## Shift briefs and unattended `glance` — 2026-11-03

Approved by the human 2026-11-03 as the rulings of the autonomous-orchestrators
epic (`PyAutoMind/draft/feature/pyautobrain/autonomous_orchestrators_epic.md`,
"Human decisions"). This section is that dated doctrine edit. It widens two
earlier sections — "What a batch launch is" and "Merge authority follows
Consequence" — and narrows nothing else. The record format is
`PyAutoMind/batches/AGENTS.md` "Shift brief"; the one process allowed to keep
time is `PyAutoMind/policy/shift_watcher.md`.

### Shift brief = launch — 2026-11-03

A human-written **shift brief** — a `brief:` block with `review-at:` in
`PyAutoMind/batches/<slot>.md` — **is the launch act** "What a batch launch is"
requires. The human performs the dispatch by writing it. The grant covers the
brief's named tasks, then its backlog-dip policy (`none` | `fill-idle` |
`scoped:` plus `exclude:`), and nothing else, until `review-at:`. Inside that
grant only, it replaces "never dispatch on a schedule": the deterministic
watcher may start sessions for work the brief covers. A watcher tick with **no
open brief dispatches nothing**, and a brief whose `review-at:` has passed is
not open.

*Revert condition:* one dispatch found outside a brief's scope returns batching
to per-task `--auto` until the cause is found.

### Unattended `glance` merges — 2026-11-03

This extends the 2026-10-02 table. For a declared `glance` task under an open
brief, **the in-turn wait may be replaced by a watcher-started close-out after
CI lands**, only when every one of these holds:

1. an **independent session** ran the `Witness:` — not the author; a different
   model where one is available, as leg 5 already requires of the adversary;
2. Heart is **not RED**, and any YELLOW reason not in the brief's `heart-ack:`
   matches one of its `expected-effects:` lines (leg 4 under a batch launch,
   applied per shift);
3. the brief's **`merge-cap:`** is not yet reached this shift;
4. the `glance` **Shadow window row is appended** at close-out, as today;
5. the task is `glance` — **never `judge`**, never a `decision-taken` PR, never
   a release, and never anything the "Never auto-merged" list above excludes.

Every `/prm` guard applies to that close-out verbatim. These merges count in
their own **stage-2 sub-window**, and each of the first 10 needs the adversary
leg actually run ("The `glance` Shadow-window ruling — 2026-11-04"). The
leg may be same-model when it is a fresh independent close-out session ("Stage-2
adversary amendment — 2026-11-04").

*Revert condition:* a `reverted` row demotes the tier exactly as the 2026-10-02
section says; one merge past a brief's cap retires this sub-rule.

### One Mind writer per shift — 2026-11-03

During a shift, **only the orchestrator commits to PyAutoMind**, from its own
temporary worktree (cherry-pick onto `origin/main`, never the canonical
checkout). Workers never touch Mind: they write their ledger lines — the
`active.md` claim, the close-out — as files in the lease directory, and the
orchestrator commits them. The reason is three losses on the shared checkout:
an unconditional `reset --hard` that wiped another session's edit
(2026-09-30), `pull --rebase --autostash` committing conflict markers into
`state.json` (2026-10-07), and `prompt_sync_push` sweeping another session's
dirty files into its own commit.

*Revert condition:* one lost Mind edit traced to a worker commit during a shift
returns that orchestrator to human-dispatched batches until the path is closed.

### Goal decomposition files drafts only — 2026-11-03

When the orchestrator breaks a brief's goal into tasks, each task is **filed as
a draft** with a proposed `Witness:`, `Consequence:` and `Lane:`, and approved
in bulk at check-in. Only already-formalised prompts run; a draft it filed this
shift never runs this shift.

*Revert condition:* never loosened before the `glance` Shadow window is
confirmed and the pilot's overrule rate says so — loosening is its own dated
edit.

### The push-notification test — 2026-11-03

A push to the human's phone is sent only when **waiting until `review-at:`
would cause harm or waste the shift**. Four classes qualify:

- data loss, or a destructive action at risk;
- a breach of the RAL rules, or runaway usage;
- the whole shift blocked on one human decision;
- a credential or security problem.

Everything else goes in the digest. The budget is **about one push per shift**,
and a second push in one shift is itself a digest finding.

*Revert condition:* two pushes in one shift that the human judged unnecessary
retire push for that orchestrator.

## The watcher's network surface — 2026-11-03

Approved by the human 2026-11-03 with the phase-3a plan of the
autonomous-orchestrators epic. The hard invariant below says any further
network surface in the Brain is a new decision; this is that decision for the
shift watcher (`bin/orchestrator_watch.py`, `agents/conductors/batch/_orchestrator.py`;
the exemption it runs under is `PyAutoMind/policy/shift_watcher.md`).

- **What it may reach, and nothing else:** read-only `gh pr checks` for PRs its
  own leases name; read-only `claude agents --json` for the workers it started;
  and **one comment per shift** on the brief's `issue:` (the digest, phase 3d).
  It starts worker sessions (`claude --bg`, phase 3b) — that is dispatch, ruled
  by "Shift briefs and unattended `glance`", not a network read.
- **Opt-in and laptop-only.** It runs only from a systemd user timer the human
  installs, only while a brief is open, and never while `STOP` exists. No
  conductor, faculty or skill calls it; no session arms it.
- **Never:** a merge, a push, a label, a PR, a review, a second comment in the
  same shift, or any write to a repository. Merges stay with the `/prm`
  close-out the section above grants.

*Revert condition:* one network call outside the three named above — or a
second issue comment in one shift — retires the watcher to fake mode until the
cause is found and this section is re-approved.

**Amendment — 2026-11-12 (PyAutoBrain#610, #611).** The human ruled the
channel for a blocked worker on 2026-11-12: a GitHub @mention in a comment on
the shift's digest issue (GitHub mobile pushes it; no new credentials). The
watcher's comments on the brief's `issue:` are now, and only:

- **the digest**, once per shift;
- **one mention per worker per state that needs the human** — a worker
  `blocked` on a person past the stall grace (parked), or one that parked on
  its issue with a question — @-mentioning the login set by
  `PYAUTO_SHIFT_MENTION` or `config/policy.yaml` `shift_watcher:
  mention_login:` (never written in code). Each counts as a push under "The
  push-notification test" and in the digest's `pushes` counter; a crash, a
  refusal, an obsolete premise or a finished worker waits for the digest;
- **one correction comment per shift**, when a worker arrives after
  `review-at:` and the record and pilot row are amended.

Each comment's marker is created exclusively **before** its post, so a crash
leaves no comment rather than two. A post `gh` says failed is retried on a
later tick, at most three tries in all; one that timed out may have landed and
is never retried. The watcher also reads `gh pr view --json
state,mergedAt,mergedBy` for the PRs its own workers named — the close-out's
merge truth (#603) and, once at `review-at:`, the digest's `merges` (#610).
It also makes one read-only `gh api user` per shift, under the posting token,
to warn when it equals the mention login (#611) — as the App, one `GET /app`
with its JWT instead, naming it `<slug>[bot]` (#630).
The revert condition now reads: one network call outside these, or a comment
beyond these (a second digest, a second mention for the same worker and
state, a second correction), retires the watcher to fake mode. **Posting identity, ruled
by the human 2026-11-12 (PyAutoLabs/PyAutoBrain#611):** the watcher's GitHub
writes use the watcher's App installation token (PyAutoBrain#630), minted by
one `POST /app/installations/<id>/access_tokens` call on each tick that makes
a watcher GitHub call and held in memory for that tick only. Without the App,
a separate account's static token, `PYAUTO_SHIFT_GH_TOKEN` (fine-grained,
PyAutoMind issues:write only), is the fallback. With neither set, the writes
post as the human's account and the digest warns that the mention will not
notify.

**Amendment — 2026-11-13 (PyAutoBrain#622), authorized by the human.** The
human approved the live shift view as drafted on 2026-11-13: a running shift
they can watch and steer from its digest issue. The watcher's network surface
gains, and only:

- **one status comment per shift** on the brief's `issue:`, created once and
  from then on only **edited** in place: at most one edit a tick, when the
  shift's state changes or every 10 minutes, and one last edit at
  `review-at:` marking it closed. It shows the picks and workers with their
  state, tokens against the budget, blocks and parks, refusals, time to
  `review-at:` and every command with its acknowledgement. It never
  @-mentions anyone, so an edit notifies nobody. Its marker is claimed
  exclusively before the create, as above. A create `gh` said failed is made
  again next tick. A create that timed out, or a claim whose tick died, is
  never made again: the comments read adopts it by its hidden tag if it
  landed, and only one written by the posting identity (`gh api user`, once
  per shift) — that read runs for adoption even when no login is set. A
  failed edit is retried next tick, and the tick carries on;
- **one read a tick of that issue's comments** (`gh api
  repos/<owner>/<repo>/issues/<n>/comments`, one page, under the posting
  token), for the steering commands;
- **the command set**, enacted from that read: `/pause` (spawns,
  re-dispatches and new close-outs are held until `/resume`; reaps and
  mentions continue), `/resume`, `/drop <task>` (a task of this shift only,
  else "no such task in this shift"; a pick not yet spawned is never picked;
  a running worker is not killed by the watcher: it is shown "dropped, still
  running", never re-dispatched and its PR never merged unattended, and
  stopping it stays the human's act, by hand; a close-out already running is
  told to refuse by a `<task>.dropped` marker it checks just before merging,
  and a merge that lands anyway is recorded as merged outside the close-out,
  never counted and with no stage-2 row) and `/stop` (writes the `STOP`
  kill-switch file, with exactly its effect: that tick commits nothing to
  Mind, and its one status edit is the acknowledgement). A command
  counts only when it is the first line of a comment by the login in
  `PYAUTO_SHIFT_MENTION` or `config/policy.yaml` `shift_watcher:
  mention_login:`, made after the brief's `dispatched:`. The status comment
  is skipped by its tag and its id, so the watcher never reads its own text
  as a command. Each comment is enacted once, by id, and acknowledged once, as
  a line of the status comment, with no extra comment or reaction.

The dashboard shows the same status as a `- live:` line in the brief record,
written through the one Mind writer when the shift's state changes. That adds
no network act beyond the Mind push the writer already makes. The revert
condition now also covers a second status comment in one shift, more than
one comments read or one status write in a tick, and a command enacted from
any other login or enacted twice: any of these retires the watcher to fake
mode.

## Human override for Heart RED (development only)

Heart RED still parks every autonomous run and blocks every release. After the
agent has parked and reported — or at the equivalent gate in supervised or
human-required development — a **live human** may authorize a non-corrective
development branch to pass the RED gate. This is a development-shipping
override, not an acknowledgement that Heart is healthy, not an autonomy level,
and not evidence that the branch repairs Heart.

- **Evidence before the ask** — the agent surfaces every exact RED reason
  string from Heart's current verdict and shows that the branch has passed all
  applicable tests, smoke, and review. A failed branch test, smoke leg, or
  review cannot be overridden.
- **Authorization** — the live human names the specific task or issue and
  authorizes that branch contemporaneously. It is recorded verbatim, or
  faithfully quoted, on the issue. A standing, stored, batch, ambient, or
  earlier-session grant does not count.
- **Permitted development actions** — commit, push, and opening the task's
  pending-release PR.
- **Merge remains separate and checked** — merge requires a separate explicit
  human merge command and every required GitHub check green. One live message
  may explicitly authorize both development shipping and merge, but if the
  turn ends before the checks are green, the merge grant expires: do not arm
  auto-merge or a waiter; the human must invoke `/prm` again.
- **Forbidden** — release, release rehearsal, bypassing a failed test, smoke,
  review, required GitHub check or branch protection, force merge, and any
  claim that the branch fixes Heart. Heart remains RED for release purposes.
- **Recorded in four sinks** — the authorization, exact current RED reasons,
  and passed branch gates are recorded on the **GitHub issue**; in the **PR
  body**; in the task's **`PyAutoMind/active.md`** entry as a
  `- heart-red-override:` block; and in the **first** table of
  **`PyAutoMind/autonomy_log.md`** with outcome `red-override`.

This override is never inferred or exercised by `--auto`: RED parks the run
first, and only the live human act above can resume development shipping.

## Corrective-PR exception for Heart RED (human-authorized)

Heart RED forbids commit, push and PR-open at every autonomy level (the levels
table). But Heart cannot clear a RED until the fixing source reaches `main`,
fresh wheels are built, and release-integration validation passes — so a source
fix that directly repairs the exact defect named by the RED reason cannot be
shipped, and recovery is impossible without violating policy. This section is
the **narrow causal-fix path**, alongside the development-only human override
above, through that deadlock. It is a **human act**, not an autonomy level: it
never fires under `--auto` (the hard invariant "Heart
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
`parked` / `corrective` / `red-override`. `corrective` records the causal-fix
exception; `red-override` records the development-only human override. Neither
is an `--auto` run, but both are logged in this first table so their use is
auditable alongside the autonomy rows. This is the evidence base for raising or
lowering caps — autonomy grows by demonstrated calibration, not by optimism.

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

## Scheduler actions — 2026-10-31

A cluster queue is shared, and one CPU array on the wrong partition has idled
all eight RAL A100s (2026-09-30). So the queue changes in one place, the
project's own `hpc/sync`, and every change leaves a record (hpc-campaign phase
5, ruling F12). **`hpc/sync act` is the only way a campaign's jobs start or
change.**

| Verb | Effect | Who may run it |
|------|--------|----------------|
| `hpc/sync act submit <campaign.yaml> [--stage S] [--indices SPEC] [--dry-run]` | starts a campaign's jobs — a pilot is `--indices` with the pilot's slice — logged | an agent, only when the human asked for that run (a pilot, then the full campaign, each on its own go) |
| `hpc/sync act <resubmit \| hold \| release \| throttle \| update-pending \| cancel> <campaign> <arg …>` | changes a campaign's queued or running jobs, logged | an agent, only on the human's ask; never another campaign's jobs without their OK |
| `hpc/sync cancel <job>` | the older spelling of `act cancel`, logged the same way | as `act` |
| `hpc/sync submit \| push-submit [gpu\|cpu] <script> [sbatch arg …]` | sbatches one hand-written script, outside any campaign | an agent, only when the human asked for that run in the session |
| `hpc/sync status \| plan \| pilot \| resubmit \| report <campaign.yaml>`, `jobs`, `sacct`, `pull`; `squeue`, `sacct`, `sinfo`, `scontrol show` | read, or write a proposal that submits nothing | anyone, any time |

`act resubmit` takes a proposal file the human has approved; `hpc/sync
resubmit` only writes the proposal, and `hpc/sync pilot` only chooses a slice.
`update-pending` changes only the fields the template allows (never a
partition).

**The audit log.** Every `act` first checks that
`<project_root>/campaign/<name>/actions.log` on the cluster can be written, and
stops without acting if it cannot; then it acts, appends one JSON line, and
prints it:

```json
{"utc": "2026-10-31T09:00:00Z", "user": "<cluster user>", "campaign": "<name>", "action": "hold", "args": ["413011"], "exit": 0}
```

`exit` is the action's own exit code, so a refused action is recorded too.
`hpc/sync status <campaign.yaml>` pulls the log back with the digest, into
`hpc/campaign/<name>/`. It is append-only: nothing rewrites or trims it.

**What enforces it.** A raw `sbatch`, `scancel`, `srun`, `salloc`, mutating `scontrol` (any
subcommand but `show`, `ping`, `version`, `help`) or `python -m
autofit.campaign submit` (but `--dry-run`) is refused by
`bin/scheduler_action_guard.py`, a PreToolUse(Bash) hook for Claude and Codex —
typed directly, over `ssh`, in `bash -c`/`eval`, behind env assignments or
wrappers (`xargs`, `parallel`, `find -exec` …), chained, substituted, or in a
heredoc fed to a shell. Help, usage, version and `sbatch --test-only` only read
and are allowed, as is `scontrol show`,
which stays allowed because recording a run as GPU needs `gres/gpu` from
`scontrol show job`. `srun`/`salloc` are refused too (human ruling 2026-10-31):
they start work outside any log; only the command an agent types is judged, so
`srun` inside a batch script is untouched. A mention (a commit message, `grep sbatch`) is not a call. The hook
is textual: a scheduler call inside a script or a Python `subprocess` is not
seen, and this table is what governs it. Human-directed exception (kept by human ruling 2026-10-31):
`PYAUTO_SKIP_SCHEDULER_GUARD=1` in the environment or as the leading assignment
of the command it excuses — a mention elsewhere excuses nothing. Registration
(human-approved 2026-10-31) follows this source's merge: the workspace-root
`.claude/settings.json` Bash hooks and `PyAutoMind/scripts/repos_sync.py`'s
Codex hook list.

## Hard invariants (every level, no exceptions)

- **Merge and issue-close are human acts, except as "Merge authority follows
  Consequence" (2026-10-02) and "Shift briefs and unattended `glance`"
  (2026-11-03) grant them** — a declared `notify` or witnessed `glance` task,
  authorized at plan or launch approval, merged in-turn on green CI, or a
  `glance` task merged by a watcher-started close-out under an open shift brief. Nothing else extends autonomy to merge; GitHub native auto-merge is not
  adopted and must not be assumed.
- **Releases are human acts, with one dated exception.** The scheduled-nightly
  standing grant (2026-07-09, above) is the only path that ships a release
  without a per-release human; it is activity-gated, Heart-GREEN-gated and
  kill-switchable. Every other release is `human-required`.
- **Autonomous runs end at PR-open**, with the PR body carrying the plan, the
  review verdict, test/smoke counts, and a validation checklist — or, for a
  declared `notify` / witnessed `glance` task, at the in-turn merge and
  close-out that section grants.
- **Never modify code to make tests or smoke tests pass.**
- **Heart YELLOW/RED is never acknowledged autonomously.** A launch-time
  human acknowledgement of a named reason set is a human acknowledgement — it
  binds to that exact set, for that launch, and never extends to new reasons.
- **The development-only human override for Heart RED is a live human act**
  after an autonomous run parks, never an autonomous acknowledgement. It can
  open a development PR and, only with a separate current human merge command
  plus green required checks, merge it; Heart remains RED for release.
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
  emits a shipped verdict, so it retires nothing on its own.

  A second exception, added 2026-09-02: `batch collect --integration` fetches
  and merges locally, and `--integration --push` publishes each
  `integration/<slot>` to `origin`. Both are **opt-in, non-default and
  laptop-only** (a remote session's credential cannot write a ref —
  `skills/GITHUB_ACCESS.md`). The push writes throwaway review refs under
  `integration/*` and nothing else: never `main`, never a release ref, never a
  pull request, never a base for one. It is **never forced** — a branch that is
  not a fast-forward of what is already published is pushed under a new `-N`
  name instead — and every pushed ref carries a `sweep-after:` date on the
  batch record, after which `bin/branch_sweep.sh` may delete it.

  A third exception, added 2026-11-03: the **shift watcher** — read-only
  `gh pr checks` and `claude agents --json`, and one issue comment per shift —
  opt-in through a human-installed timer and laptop-only; the full terms and
  their revert condition are "The watcher's network surface — 2026-11-03"
  above.

  Any *further* network surface in the Brain is a new decision, not covered by
  this line.
- The `Autonomy:` header is a model's own estimate. The caps, the explicit
  `--auto` launch, and the calibration log are what make consuming it
  defensible — none of the three is optional.

## Consumers

- `start_dev` — `--auto` usage, effective-level computation, plan-to-issue
  for `safe`, launch-acknowledgement recording (its "--auto mode" section);
  the plan's tier + merge-mode line.
- `prm` — the CI judgment, merge guards and close-out every merge runs,
  human-typed or tiered.
- `ship_library` / `ship_workspace` — the four-leg gate at step 4 (five under a
  batch launch), stop at
  PR-open (or the tiered in-turn merge), validation checklist, calibration append; the RED-handling step
  points here for both the development-only human override and the narrower
  corrective-PR exception.
- `batch`, `start_dev`, `prm` — "Shift briefs and unattended `glance`"
  (2026-11-03): the brief as the launch act, the backlog-dip scope, the
  unattended `glance` close-out guards and the merge cap, one Mind writer per
  shift, drafts-only decomposition, the push test.
- `prm`, `ship_library` / `ship_workspace`, `batch` — "The `glance`
  Shadow-window ruling" (2026-11-04): a witness that did not PASS is a human
  `/prm`; unattended merges count in a stage-2 sub-window whose first 10 each
  need the adversary leg.
- `batch` (the close-out session) — "Stage-2 adversary amendment" (2026-11-04):
  the independent close-out session is the adversary leg, same model allowed.
- `batch` (the watcher) — "The watcher's network surface" (2026-11-03): what
  the watcher may reach, and that it is opt-in, laptop-only and never writes;
  amended 2026-11-12 (mentions, #611) and 2026-11-13 (the live status comment
  and the steering commands, #622).

Skills must link here rather than copying the tables.
