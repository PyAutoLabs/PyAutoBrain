# Batch Agent

> **Tier: conductor** — a front-door agent a human *drives*. It *composes one
> unattended shift*: given the queue, the backlog and the review-queue state, it
> emits a **BatchDecision** — the members, what they will cost the human to
> review, and what it rejected and why. It **proposes; it never dispatches.**
> Approving the proposal in a slot is what launches a batch, and the human says
> at dispatch when they expect to be back (`review-at:`) — that horizon is the
> shift.

## What it is for

The organism has no throughput problem. August 2026 shipped **332 completion
records, about eleven a day**. The scarce resource is the human's judgement, and
a batch layer that plans by task count spends it faster rather than slower.

So the composition rule is a budget in **review-minutes**, not a count:

> Σ `Review-minutes:` over `glance` and `judge` members ≤ the slot's budget
> (default 45 — a slot also has to queue the next batch).

The budget is **the human's to set per slot**: they know whether the next one is
a quick morning check or a long afternoon, and the number follows the nature of
the work and their schedule rather than a rhythm. Read against the ledger, an
honest hour holds about three library-touching tasks. Planning by count
over-promises capacity roughly threefold, and the overflow lands on the human at
6am.

Everything above that budget is the **fill**: work costing zero review-minutes
(`notify`-tier work, slicing, witness authoring, backlog re-grading, deeper
verification of work that already passed). The fill is sized by the remaining
token allowance rather than by the human's hour, which is what lets the organism
spend its whole weekly budget without growing the review queue. **Research and
experiments are never fill** — they produce verdicts, and a verdict is the most
expensive review there is.

## What it consults, and what it owns

It owns **membership**, which is an act. Every *judgement* it uses — consequence
tier, review-minutes, readiness, difficulty — comes from the **sizing faculty**,
because `ORGANISM.md` makes faculties the opinion sinks and forbids a conductor
consulting a conductor. If a rule here starts needing to *judge* rather than
*select*, it belongs in the faculty.

## The constraints, and why each exists

| Constraint | Why |
|---|---|
| **Review-minute budget** | the human's hour is the binding resource; see above |
| **One member per *library* repo per shift** | concurrent members do not collide at dispatch (separate worktrees) — they collide at **merge**, because the first `/prm` moves `main` and invalidates the others' test and smoke evidence. Workspace, docs and organ repos are exempt: two docs changes in one shift cost nothing. Work concentrates in four repos (PyAutoFit 118/332 August records, PyAutoArray 98, PyAutoGalaxy 82, PyAutoLens 78), so effective parallelism is two or three, not six. |
| **One slice per epic per batch** | epic phases are ordered, so two members could not run in parallel anyway — and this is what interleaves small pieces of long programmes with standalone work |
| **`Unattended: ready` only** | `needs-slicing` goes to the decomposition pass (`batch slice`); `never` never enters a batch |
| **Lane match** | a session detects its own lane and plans only that one |
| **No Lane, no unattended pick** | a backlog draft with no valid `Lane:` is excluded from every unattended plan (the default, and the watcher) and the plan says so; `--attended` reads it as `any`. A lane-less draft that needs the laptop, RAL or private data would otherwise reach a cloud worker (M2.3, `AUTONOMY.md` "M2 rulings — 2026-11-12") |
| **Empty queue, no dip** | an empty or absent `queue.md` stops an unattended shift's backlog dip; a brief's named tasks still run (M2.3) |
| **Not `looks-shipped`** | a draft the close-out guard (`intake looks-shipped`) flagged with strong evidence that its work already shipped waits until a human closes it or lists it in `PyAutoMind/looks_shipped_dismissed.md`; the flags are read from `PyAutoMind/looks_shipped.json` at plan time, so a dismissal takes effect at once. The 2026-11-05-am batch proposed two shipped drafts. |
| **Backpressure** | see below |
| **Brief scope** | under a shift brief, only its named tasks and the backlog its dip policy covers run; anything else is a dispatch outside the launch, which "What a batch launch is" forbids (`AUTONOMY.md`, 2026-11-03) |
| **Merge cap** | unattended `glance` merges stop at the brief's `merge-cap:`; each merge moves `main` and stales the next member's evidence, and the cap bounds what one unread shift can change |
| **One integration root per slot, and it is local** | `integration/<slot>` is cut fresh from `origin/main` on every run and never pushed, so a re-run is a re-preview rather than a rewrite; a dirty integration worktree is skipped, never reset. The one-member-per-library-repo rule above is what keeps within-repo conflicts rare — the common case is one member with organ PRs across five repos. |
| **Publishing that root is a separate act, typed by the human** | `--push` is the only remote write the batch makes, and no record can ask for it — `- integration: yes` requests the *local* preview. What it writes is a throwaway `integration/*` review ref and nothing else: never a pull request, never a base for one, never forced. A refresh that is not a fast-forward publishes `-2` rather than moving what is already there, and the ref expires at the record's `sweep-after:`. |

Everything rejected says so, with its reason. A planner that silently drops work
teaches the human to distrust the number it reports.

## Backpressure ramps; it never deadlocks

Counted in **tasks awaiting review**, never in PRs — 94 of 332 August records
named two or more PRs, so a PR-count cap trips on a single healthy batch.

**Derived, not asked for.** The count is read from `PyAutoMind/active.md`: a
task counts when its row names an open PR (`library-pr:` / `workspace-pr:` —
the PR ledger, `PyAutoMind/REFERENCE.md` "The PR keys") or its `status:` says
`awaiting-merge` / `PR open` in words, which is how rows written before that
schema spelled it. `--awaiting-review <n>` still overrides, including `0` — a
human asserting the queue is empty outranks the derivation. Until 2026-09-03
the flag defaulted to `0` and nothing derived it, so every plan composed a
shift as though nothing were waiting: the one input that can SHRINK a batch
could only arrive by hand, and never did.

No `gh` call, here or anywhere in `plan`. `active.md` is the ledger and GitHub
is the truth about mergeability; a shift must be plannable offline
(`mind_post_cortex_epic.md`: no live PR state in Mind).

## The queue is the order

`PyAutoMind/queue.md` is the one file the human maintains by hand, and the only
statement of *importance* the planner has — everything else it reads is a
property of the work, not a preference about it. **Order is priority**: moving
an entry up *is* the act of prioritising it.

`plan` reads exactly three things, and nothing live:

1. `queue.md` — the `kind: prompt` entries, in file order;
2. the `draft/` backlog, graded through the sizing faculty;
3. the review-queue depth, derived from `active.md` as above.

A queued prompt outranks an unqueued one; among queued ones the file's order
wins; below the queue a declared `Priority:` comes first and cheapest review
second (M2.3, 2026-11-12 — cheapest-first let the cheapest review win and broke
ties by filename). An unattended plan with an **empty or absent** `queue.md`
dips into no backlog at all: only a brief's named tasks run, and the plan and
the digest say so. `lifecycle.py check` (Mind) fails on a `kind: prompt` ref
that resolves to no draft or active prompt, so the list stays honest. A
queue entry written against `draft/…` still matches its prompt after it moves
to `active/` (matched on the basename), so an entry never silently loses its
priority. `retired`, `epic-slice` and `theme-sweep` entries are skipped rather
than resolved: resolving one is a decision (which phase? which chip?), and the
reader does not decide.

`plan` also reports what the **previous slot carried**: the members its
`outcomes:` block marks `carried` are read first, because they are already
costing the human review-minutes in the slot being planned and a batch composed
as though they were not is over-sold by exactly that much.

- clear → the full budget;
- above half the cap → the review-bearing half is **halved** (the fill is not:
  it does not touch the queue);
- at the cap → the batch is **fill only**: zero-cost work still composes, and
  the human still dispatches it.

Backpressure is about review-queue **depth**, never about timing — timing is the
human's, declared as `review-at:` at dispatch, and if they do not come back
nothing new is dispatched at all. (The **floor** — a fill-only batch that
dispatched whether or not the human turned up — was **closed 2026-08-31** and
never built.) An **empty fill-only batch is a finding, not a deadlock** — it
means nothing in the backlog costs zero review-minutes, which is exactly what
the `notify` tier and the `Witness:` field exist to change, and the decision
says so in those words.

## Lane detection

`local-dev` or `web-github`, probed from the environment rather than declared,
and from the signal the organism already uses: a remote session has no `gh`
(measured; `skills/GITHUB_ACCESS.md`). No flag and no environment variable
decides it — a session that could lie about where it is could plan `local-dev`
work it cannot run. A session reports the other lane's ready count rather than
hiding it, by resource: *"4 laptop-lane task(s) are ready (3 ral, 1 local-dev) — run
`batch plan` from the laptop."* A task's `Lane:` is `any`, `local-dev`, or one
of the resource lanes `ral` / `gpu` / `wsl-data`, each of which implies
`local-dev` (`lane_is_local` in the sizing faculty is the one test). A draft
with **no** valid `Lane:` fails closed in an unattended plan
(`lane_absent_why`) and reads as `any` only under `batch plan --attended`;
intake refuses to file a draft whose lane is neither declared (`Lane:` header
or `--lane`) nor inferred.

## The premise check (`premise`) — before a run is spent

In the first live shift that worked (2026-11-06-pm), 2 of 3 dispatched tasks
were obsolete on `main`: one named a harness deleted five weeks earlier, the
other a smoke-cap overrun the timing record had not shown for days. The
close-out guard (`looks-shipped`) looks for work that *arrived*; it cannot see
a premise that has *gone away*. `batch premise <draft>` can (PyAutoBrain#608,
programme M1.3, `_premise.py`):

- On a fresh `main` of every repo the draft names (`git fetch`; `--no-fetch`
  reads the cached ref; `--at <ISO>` replays main as it stood), it checks the
  backticked paths and `name()` functions the draft names, reads the state of
  its `Repo#N` issues and PRs (`--offline` skips `gh`), and compares a title
  that claims a smoke duration with the Heart's timing record
  (`timings/scripts/<repo>.jsonl`, decisive only when fresh).
- It returns **`ok | obsolete | unknown`** with evidence: `obsolete` when the
  timing record contradicts the title, a file or function the title or
  `Witness:` names is gone (the deleting commit is the evidence), or every
  named path is gone; renames and newly-gitignored paths are *moved*, not
  gone, and a path with no history is work to create, never evidence. A
  function counts as gone only if no library or organ checkout still defines
  it and it was removed after the draft's `Filed:` date. For a bug it also
  prints what a worker must reproduce. Exit 1 on `obsolete` only: a check
  that crashes prints `unknown (check failed: …)` and exits 0.
- `--write-verified` stamps `Verified: <date> <sha> (<repo>)` on an `ok`
  draft — inside a shift as a `set-header` ledger op the orchestrator
  commits (one Mind writer), outside one in place, uncommitted. A stamp for
  a draft that has left `main` since is skipped with a note, never raised.
- It is the **first step of every dispatched worker** (`worker_template.md`):
  on `obsolete` the worker writes its proof packet and an `obsolete <why>`
  `.done`, and stops; the digest shows it as `obsolete (premise check): <why>`.
  On `unknown` it goes on and says so in its proof packet. And it runs at
  **brief time**: `batch brief --check` adds a warning for each named task
  whose premise is obsolete (`--no-premise` skips the leg).

Mechanical by design — git reads and at most a few `gh api` calls, no LLM.
Replayed on the two obsolete tasks above it returns `obsolete` for both
(`tests/test_premise_check.py`).

## It proposes; the human launches

`AUTONOMY.md` ("What a batch launch is") defines a batch dispatch as **one
launch**: membership fixed at approval, the grant expiring with the shift — the
interval from dispatch to the `review-at:` the human states at dispatch — the
terms written into `PyAutoMind/batches/<date>-<am|pm>.md`, and the human
performing the dispatch. A scheduler may build the review packet and wake a
session; the act that starts work on the approved list is the human's. That is
the line that keeps "never ambient" true — the schedule carries the *timing*,
never the *authority*. A shift brief written with `review-at:` is that act in
writing (2026-11-03): the human dispatches by writing it, and its scope is the
whole grant (`AUTONOMY.md`, "Shift briefs and unattended `glance`").

`batch brief --new <YYYY-MM-DD-am|pm> --review-at <ISO>` composes that writing:
a skeleton brief whose `goals:` are `PyAutoMind/goals.md`'s, in order, with
`backlog: scoped` to their `epics:`/`tags:` (else `fill-idle`) and
`merge-cap: 0`. It prints to stdout (`--out FILE` writes it) and never writes a
record into `batches/` — saving it there is the human's dispatch.
A goal whose line was last written by a `Via: mind-dashboard` commit (git
blame) is web-page text, so it is emitted commented out — "from dashboard,
last edited <date>" — and never reaches a worker unless the human adopts it;
`--new` also prints on stderr how the goals changed since the newest brief.
`brief --check` warns when `goals.md`'s goal 1 is missing from a brief, unless
goal 1 came from the dashboard (PyAutoMind#565; readers in `_steer.py`).

## The keep-Heart-green lane (`_green.py`, PyAutoBrain#625)

The human, 2026-11-13: "having the autonomous agent constantly trying to
ensure its green (without having it be overly eager doing releases)". So
`brief --new` reads Heart's release verdict first: the local
`pyauto-heart readiness --json` (it carries per-repo keys), else the published
feed, under `heart_feed.py`'s 6 h rule (a fresher feed wins over an over-age
snapshot). It runs at brief time, never in the watcher's tick, whose network
surface does not grow.

Every RED, YELLOW and STALE reason is sorted by the `RULES` table in
`_green.py` (first match wins; Heart's `repository_reasons` key wins over the
text; no match is `human-only`, fail closed):

| Class | Examples | The lane |
|---|---|---|
| `fixable-dev` | red CI on `main`, a failing workspace script, a red unit test, a yanked or unparseable floor, URL lint, Lifecycle Drift | files a bug draft; picks it only on opt-in |
| `local-checkout` | behind, dirty, on a branch, worktree drift, every manifest-drift leg (they read the checkouts on disk, other sessions' worktrees included; `MANIFEST_FIXABLE` allowlists a leg that judges `main`) | reports only: another session's work may be in progress |
| `release-scope` | release integrate failed, install check F, rehearsal stale, a floor above the newest release | reports, and names the human's release action |
| `human-only` | open PR, quarantine doctrine, parked scripts, timing, credentials | reports |

For `fixable-dev` it dedupes on a key (`ci:<repo>`, `script:<path>` …):
a prompt in `draft/`/`active/` carrying `<!-- heart-key: <key> -->`, quoting
the reason or naming the script, a `queue.md` line, or the lane's state file
(`<orchestrator home>/heart_green.json`: a key it filed is not re-filed while
Heart keeps listing it; a fresh, valid read without the reason clears the
row, so a later recurrence files again). It files at most `--green-cap` (3)
new drafts per brief — `Consequence: judge`, a `Lane:`, a re-check-first
note, the quoted reason, a Witness, `Difficulty:` from the sizing faculty and
no `Unattended:` (the lane never grades its own drafts ready) — red first;
the rest wait for the next brief.

**Where it writes.** Modes are `--green off|report|file|pick` (or
`$PYAUTO_HEART_GREEN`); the default is `file`. It writes drafts and its state
only when `brief --new` has `--out` (a stdout preview writes nothing) and
`--mind` names a Mind that is not the canonical shared checkout — a temp
worktree on `origin/main`, committed and pushed from there. Otherwise it
reports what it would file and says why. `pick` is the human's opt-in: a filed
or existing `draft/` prompt whose `Lane:` the brief allows and that sizing
grades `Unattended: ready` becomes a named task under a last `heart-green`
goal. An active quarantine's bug task is picked only when a prompt carries the
lane's key mark or has the entry's bug ref as its `Issue:`; it is never filed.
The record gets a `## Heart` section: reasons by class, filed, picked, and what
needs the human. `batch green` is the same lane alone, `report` by default.

It never releases, rehearses, dispatches a workflow, forces, touches a
freeze, writes `queue.md`, edits another prompt, or quarantines (it may
propose one). `_green.py` imports no process or network module; the tests
pin that and record every process a full brief run starts.

## The watcher (phases 3a–3d)

`bin/orchestrator_watch.py --brief <record> --mind <PyAutoMind>` runs **one
tick**: `STOP` first, then the open-brief gate, the tick lock, the lease reap,
the plan inside the brief, the caps (`max-workers:`, default 2;
`max-sessions:`, default 6) and an exclusive-create lease per spawn. State lives
under `$PYAUTO_ORCHESTRATOR_HOME` (default `.orchestrator` under the worktree
root), one directory per brief: `STOP`, `leases/`, `counters.json`, `tick.log`.
Until phase 3b it spawns only stub workers (`PYAUTO_ORCHESTRATOR_FAKE=1`); a real
dispatch is refused. Doctrine: `AUTONOMY.md` "The watcher's network surface —
2026-11-03"; the exemption it runs under, `PyAutoMind/policy/shift_watcher.md`.

**The open-brief gate is a window: `dispatched:` → `review-at:`.** A brief
that passes `batch brief --check` is open only from its `dispatched:` until its
`review-at:`. Before the start, a tick is idle (`not yet open: opens at
dispatched …`) and touches nothing, not even the slot directory, so a brief may
be landed early. Until 2026-11-05 the gate ignored `dispatched:` and a brief
opened the moment it landed (pilot shadow shift 1 opened a day early;
PyAutoBrain#589). `batch watch` says `not yet open — opens in …` before the
start.

**Real workers (phase 3b).** Without `PYAUTO_ORCHESTRATOR_FAKE=1` each spawn is
`claude --bg --name shift:<task> --permission-mode <worker-mode> <prompt>`, the
prompt filled from `worker_template.md` (the `/start_dev <path> --auto` line,
the end-at-deliverable contract, the brief path, "never commit to PyAutoMind
yourself", and the `<lease>/<task>.done` marker). The lease records the short
id `claude --bg` prints (`backgrounded · <id> · <name>`; `--session-id` is not
honoured by `--bg`). Each tick reads `claude agents --json --all` once:
`working` → heartbeat; `blocked` (waiting on a person) → `stalled_since`, and
after `STALL_GRACE_S` (15 min) the task is **parked** — never killed, never
re-dispatched, named in the digest; `done` with the marker → released, without
it → crashed (re-dispatched once). **Tokens (PyAutoBrain#610)** are read every
tick for every live, parked and close-out session from its local transcript
(named by the full `sessionId`): input, output and cache creation, once per
message id, with cache reads reported apart; each read **replaces** that
session's entry in `counters.json` `usage`, never adds. No transcript is
`None`, never 0: it keeps the last read and refuses the next spawn (`token usage
unavailable`) — until `UNREADABLE_READS` (3) reads in a row fail, when the
session is `unmeasured`: it stops blocking, its reservation counts as its
usage, and the pilot row's `tokens` is `null` (`unmeasured` in `pilot.md`),
never 0. Subagent transcripts (`<sid>/subagents/agent-*.jsonl`) are included
and reported as `subagents`. The digest's `### Refusals` lists every spawn
refusal with its reason. A real worker holds a reservation from its spawn (default
`token-budget / max-sessions`) until its usage passes it, so the budget binds on
the first tick; `token-budget:` refuses a spawn once spent, or once committed
usage plus a new reservation would pass it. Every worker has one exit record
(`workers`: `spawned/finished`, `spawned/crashed`, `spawned/parked/late/finished`;
a failed launch is one `launch-failed` record per task) with its blocked minutes.
`worker-mode:` defaults to `auto` (human, 2026-11-03); `dontAsk` and
`acceptEdits` are allowed, `bypassPermissions` never.

**One Mind writer (phase 3c).** Workers never commit to PyAutoMind. Each Mind
change — the `active.md` claim, the `draft/ → active/` move, the close-out — is
queued as an op file in `<slot>/ledger/` by `bin/shift_ledger.py`
(`append | write | move | remove | drop-section`; every path must be *ledger*
by PyAutoMind's own `scripts/ledger_merge.py`, default deny). Each tick, after
the reap, `_mind_writer.commit_ledger` applies all pending ops in a temporary
detached worktree on `origin/main`, commits once and pushes; if `main` moved it
replays the ops on the new `origin/main` (up to three tries). It never resets,
never forces, and never touches the canonical checkout's working tree.
Committed op files move to `ledger/committed/`; an op that cannot apply stays
pending and the tick reports it. **Enforced, not asked:** a worker runs with
`PYAUTO_SHIFT_WORKER=1`, `PYAUTO_SHIFT_LEDGER_DIR`, and `core.hooksPath` (via
`GIT_CONFIG_*`) pointing at `bin/worker_git_hooks/`, whose `pre-commit`
refuses any commit in a PyAutoMind repo — `prompt_sync_push`, `lifecycle close`
or a raw `git commit` alike — and otherwise chains to the repo's own hook.
With that in place real dispatch no longer needs `sandbox: yes` (human,
2026-11-03); the key stays as a test-shift marker.

**The digest (phase 3d).** Every spawn records, in `counters.json` `picks`,
the prompt, its tier and **why the brief admitted it** (`_brief.pick_reason`:
`named task`, `scoped epic|tag|tier <x>`, or `backlog: fill-idle`) — at
dispatch, because by `review-at:` the prompt may have moved to `complete/`.
The reap keeps what the worker left before deleting its marker: the `.done`
lines go to `outcomes` (`<url>`, or `merged <url>` for an in-turn tiered
merge), and `<task>.proof.md` moves to `<slot>/proofs/`. The first tick after
`review-at:` runs `finish_shift` once: `_digest.build` writes the `## Digest`
(`PyAutoMind/batches/AGENTS.md` format — brief work, backlog picks each with
its `why:`, one proof packet per started task or a stub that says none was
written, every counter) to `<slot>/digest.md`, appends it to the record through
the one Mind writer, writes `digest.html` only under `packet: yes`, then
**exclusive-creates `digest.posted` before** the one `gh issue comment` on the
brief's `issue:`. A crash between the two leaves no comment, never two; a post
`gh` said failed is retried by a later tick, three tries in all (#610), and a
timed-out one never. It reaps first, so a `.done` written after the last live
tick is in the digest, and reads each worker PR's `gh pr view` once: `merges`
counts the PRs GitHub shows merged by `review-at:`, whoever merged them, and
`workers-crashed` counts exit records, not a tally. A `### Workers` section
prints one line per worker (`<label> (<id>): spawned/crashed`). An issue URL in
a `.done` is kept in `issues`, never `prs`. Health per PR is one
read-only `gh pr checks --json`, judged per check by `bin/ci_verdict.py`'s
`judge` (PyAutoBrain#628; PyAutoHeart#343): any
failed or cancelled → FAILED, any pending → RUNNING, no completed check at all
(no CI, or only skipped) → NO-CHECKS, else HEALTHY — at least one completed
check, all green; unreadable → UNKNOWN. `glance-auto-merges`, `reverts`, `pushes`, `drafts-filed` and
`packets-sent` read `counters.json` and stay 0 until phases 4–5 move them
(human, 2026-11-04). `batch digest --record <file>` prints the digest and
writes nothing; `batch brief --check` refuses a digest missing a section, a
counter, a pick's `why:` or a started task's packet.

**Picks are named for a human (PyAutoBrain#579).** Each pick
(`_orchestrator.pick_record`, shared by dispatch and shadow) keeps the prompt's
title, size and repos, and the digest names it as
`[<title>](<Mind blob link>) (`<slug>`; <size> · <repos>)`. The link is built
from the brief's `issue:` repository; a pick recorded without a title falls
back to the bare slug, and `validate` reads the backticked slug either way. The
`why:` is the brief's admission rule plus `_brief.rank_note`, which is the
planner's actual order: `queue.md #k`, or `not in queue.md · priority P ·
~N review-min` (then the path, so a tie is alphabetical), plus `epic E phase X`.
Shadow shift 1 (2026-11-04) showed why: six bare slugs, each `why: scoped tier
notify`, could not be reviewed. A shadow digest prints its counters as one line
(`- all counters 0 — shadow shift, nothing dispatched · review-minutes-planned: N`),
which `validate` accepts in place of the nine.

**Shadow shifts and the pilot ledger (phase 4a).** Under `shadow: yes` a tick
runs the same plan inside the brief but, instead of spawning, records each
proposal in `picks` with `proposed: true` (`_propose`, capped by
`max-sessions:`): no lease, no worker, no session counted. The digest marks
them `proposed (shadow)` and its packet section says nothing was dispatched;
`brief --check` asks no packet of a proposal. `finish_shift` also appends one
row to `PyAutoMind/batches/pilot/pilot.md` (`_digest.pilot_row`: the digest's
counters plus slot and mode; `review-minutes-actual` and `overrules` land as
`?` for the human) in the same Mind commit as the digest. Since #610 the row
is `pilot.md`'s render of one line of `batches/pilot/pilot.jsonl` (slot, mode,
counters, tokens by component and session kind, merged PR URLs with `mergedBy`
and merge actor, per-worker exits, stall minutes, `amended`); both are
**upserted by slot** through the one Mind writer (`jsonl-upsert`,
`table-upsert`, which keeps the human's filled cells), so a rerun or a late
arrival never adds a second line. In a **shadow** row
`merges` is a `?` too: the orchestrator merges nothing, so the baseline is the
human's own work in the window (the epic: "the human works as today, minutes
are logged"), with `review-minutes-actual` the human's own review time and
`merges` their own merges, both counted at check-in. A shift whose
`digest.posted` exists writes nothing more — no second append, row or comment.

**Unattended `glance` close-out (phase 4b).** A `glance` worker under a brief
ends at PR-open (`worker_template.md`). Each tick, `_closeouts` first reaps
running close-outs — `<task>.closeout` (`merged` | `refused`, `why`, `gate`,
`model`), or a session gone without one, which is recorded refused — then, for
each PR a worker named, judges the guards it can see with its own reads: the
recorded tier is `glance`, `gh pr checks` is green — at least one completed
check, all green (pending waits a tick; red, none or unknown is refused), merges plus in-flight close-outs are under `merge-cap:`, and the
shift is not shadow. Then it starts **one** close-out session
(`closeout_template.md`; `claude --bg --name shift-close:<task> --model opus`).
That session is the independent leg: it runs the `Witness:` itself, reviews the
diff adversarially, checks the `decision-taken` label and Heart, and only then
runs the `/prm` close-out — or refuses. A merge bumps `glance_auto_merges`,
marks the PR merged, and queues a `table-append` op that lands one row in
`autonomy_log.md` "Unattended `glance` sub-window (stage 2)" through the one Mind
writer. Every refusal is final for the shift and named in the digest
(`awaiting /prm — close-out refused: <why>`). Same-model close-out: AUTONOMY
"Stage-2 adversary amendment — 2026-11-04".

**Watching a shift live (`batch watch`, PyAutoBrain#575).** `batch watch
--record <brief> [--once] [--interval N]` (`_watch.py`) draws a running shift
in the terminal: SHADOW or LIVE, time left until `review-at:`, STOP and
`digest.posted`, each task's state with its pick reason, PR, CI health and
re-dispatch count, the budgets (live workers against `max-workers:`, sessions
against `max-sessions:`, tokens, merges against `merge-cap:`, crashes) and the last five ticks. It redraws every `--interval` seconds (at
least 30); `--once` prints one snapshot. Task wording is `_digest.task_state`,
the digest's own, plus the states only a held lease shows (`running`, `blocked
on a person`, `crashed — awaiting re-dispatch`). It is **read-only**: no write
to the slot, Mind or GitHub, no lock — safe beside the timer. Its reads are the
watcher's own: one `claude agents --json` per refresh, only on a live shift
holding real worker leases, and `gh pr checks` for unmerged PRs, cached for the
interval.

**Late arrivals (PyAutoBrain#594).** A worker may finish after `review-at:`,
once the digest is posted. A closed shift with a lease still held or a ledger op
still queued runs `late_sweep` on each tick: it reaps as a live tick does,
commits the queued ops through the one Mind writer, and appends one
`- late: <task> — <url> (after review-at, <time>)` line per arrival to the record
under `### Late arrivals`, amends the pilot line in place (`amended: true`) and
posts **one** correction comment for the shift (#610). It never spawns,
re-dispatches or starts a close-out, because the grant ended at `review-at:` and
what arrives late waits for `/prm`. It also runs while a failed digest or
correction post is due its retry.

**A blocked worker reaches the human (PyAutoBrain#611).** The human's channel
(2026-11-12) is a GitHub @mention on the shift's digest issue. When a worker is
parked (`blocked` past the grace) or parks on its issue with a question, the
tick posts one comment on the brief's `issue:` naming the task, the reason and
its session, worktree or PR, @-mentioning the login from `PYAUTO_SHIFT_MENTION`
or `config/policy.yaml` `shift_watcher: mention_login:`. One comment per worker
per state, marker (`<slot>/mentions/`) before post, a failed post retried next
tick; a crash, refusal or finished worker never mentions (AUTONOMY.md push test).
Each sent mention counts in `pushes`; more than one is a digest finding. The
trigger is durable state (a parked task or an issue-only `.done` with no
marker yet), so a tick that dies between parking and posting mentions on the
next; a failed mention is also retried by the late sweep.

**Watching and steering a shift from its issue (PyAutoBrain#622).** Each open
tick ends with the shift's **status comment** on the brief's `issue:`: the
`batch watch` snapshot as Markdown (`_watch.render_status`, no tick log),
created once (`<slot>/status.json` claimed before the create) and then only
edited, at most once a tick, when the state changes or every 10 minutes
(`STATUS_REFRESH_S`). A create that may have landed is never made again; the
comments read adopts it by its hidden tag. A failed edit is retried next tick.
After the reap, one `gh api …/comments` read takes the human's commands, each
the first line of a comment by `mention_login`, made after `dispatched:`:
`/pause` (spawns, re-dispatches, shadow proposals and new close-outs are held
until `/resume`; reaps and mentions continue), `/resume`, `/drop <task>` (a
task of this shift only, else "no such task in this shift"; `counters.json`
`dropped` plus a `leases/<task>.dropped` marker; never picked, never
re-dispatched, its PR refused for close-out; a close-out already running checks
the marker just before merging and refuses, and a merge that lands anyway is
recorded as merged outside the close-out, with no stage-2 row; a live worker is
shown `dropped, still running` and stopping it is the human's, `claude stop
<id>`) and `/stop` (writes `STOP`; that tick commits nothing to Mind). Each comment acts once, by id, and is acknowledged
once in the status comment's `Commands` list. Without a login, nothing is read
and the comment says steering is off. The dashboard's copy is the record's `-
live:` line (`record-key` op, one Mind writer, on a change of state), shown in
the batch box. Doctrine: AUTONOMY.md watcher network surface, amendment
2026-11-13.

**The watcher's GitHub identity (human rulings 2026-11-12, #611, and
2026-11-14, #630).** The watcher posts as its own minimal GitHub App,
`pyautolabs-watcher`, set by the human in the timer's environment
(`~/.config/pyauto/orchestrator.env`) with three variables, all or none:

- `PYAUTO_SHIFT_APP_ID` — the App id;
- `PYAUTO_SHIFT_APP_INSTALLATION_ID` — its installation on PyAutoMind's owner;
- `PYAUTO_SHIFT_APP_KEY` — the path of the App's private key (`.pem`, mode 600).

The App is minimal on purpose: **Issues read/write on PyAutoMind only** —
all the watcher does is comment on, edit its comment on and read the shift
issue. It is **not `pyautolabs-bot`**: that App is a ruleset bypass actor with
org-wide push, and a laptop timer must hold no bypass power. Posting as an App
also means the @mention of the human comes from another account, so it
notifies them. `_app_token.py` signs an RS256 JWT (`iat` now − 60 s, `exp` now
+ 9 min, `iss` the App id; PyJWT, else `openssl dgst -sha256 -sign` with no
shell), mints an installation token with one `POST
/app/installations/<id>/access_tokens`, and caches it with its `expires_at` in
the state directory (`app_token.json`, mode 600), minting again when it is
under 10 minutes from expiry — about one mint an hour, and only on a tick that
makes a GitHub call. The token is passed as `GH_TOKEN` to the watcher's own
`gh` calls (comments, the status edit, the steering read) and to nothing else.
If minting fails, the tick carries on but makes **no** GitHub call: never one
under the human's `gh` auth in its place. The reason goes into `tick.log`
(`github_auth`) and the digest ("GitHub writes held"); a held post costs no
try and is retried, and a failed mint is not retried for 10 minutes. An App
configured in part (one or two variables) is the same failure. Without the
App, `PYAUTO_SHIFT_GH_TOKEN` (a static fine-grained token, PyAutoMind
issues:write only) is the fallback; with neither, comments post as the human's
account. Neither the App variables, the key path, the static token nor a
minted token reaches a worker or close-out (`worker_env`). Once a shift,
before the first mention, the posting account is named — as the App,
`<slug>[bot]` from one `GET /app` with the JWT (`gh api user` does not answer
for an installation token), else `gh api user` — and if it is the mentioned
login (never, as the App) the digest's `### Workers` warns "mention will not
notify: posted as the mentioned account". With nothing pending, the tick is
idle. The worker
prompt also forbids EnterWorktree (its permission prompt stalls an unattended
worker) and requires the `decision-taken` label on any PR carrying a flagged
decision (pilot live shift 1, 2026-11-06).

**Workers start in a trusted folder.** `claude --bg` refuses an untrusted one
at once ("Workspace not trusted", exit 1) — the spawn fails and leaves no lease.
The watcher launches from the workspace root; task worktrees under the
`-wt` root are not trusted by default, so trust that root once by hand if
workers are ever launched there.

**Installing the timer is the human's act** — no session runs these. Copy
`bin/systemd/pyauto-orchestrator.{service,timer}` to `~/.config/systemd/user/`,
write `~/.config/pyauto/orchestrator.env` with `PYAUTO_BRAIN`, `PYAUTO_MIND`,
`PYAUTO_SHIFT_BRIEF` (and `PYAUTO_ORCHESTRATOR_FAKE=1` until 3b), then
`systemctl --user daemon-reload && systemctl --user enable --now
pyauto-orchestrator.timer`. The service carries `KillMode=process`: under the
default (`control-group`) systemd killed every process a tick started when the
tick exited, including the `claude --bg` daemon the first worker launched, so
live shift 1 (2026-11-06) lost all three workers about 30 seconds after spawn
(PyAutoBrain#592). A copy installed before then must be copied again
(`daemon-reload`). Separately, a worker or close-out whose `claude agents`
state is in `_digest.ENDED_STATES` (`failed`, `killed`, `error`, …) is reaped
at once, as a crash (worker, re-dispatched once) or a refusal (close-out),
never read as alive. To stop a shift, `touch <slot>/STOP` (or comment `/stop` on
its issue); to remove the
watcher, `systemctl --user disable --now pyauto-orchestrator.timer`.

## Running

```
pyauto-brain batch plan                      # the BatchDecision for this lane
pyauto-brain batch plan --budget 45          # review-minutes available
pyauto-brain batch plan --awaiting-review 6  # backpressure input
pyauto-brain batch plan --json

pyauto-brain batch collect                   # score the newest record; offline
pyauto-brain batch collect --slot 2026-09-03-pm
pyauto-brain batch collect --evidence ev.json    # PR state from this session
pyauto-brain batch collect --fetch               # laptop: `gh pr view` per PR
pyauto-brain batch collect --integration         # laptop: merge every member's head into one worktree root
pyauto-brain batch collect --evidence ev.json --apply  # the one form that writes
pyauto-brain batch collect --out report.md --json

pyauto-brain batch watch --record <brief>         # live view of a running shift; read-only
pyauto-brain batch watch --record <brief> --once  # one snapshot
```

**One board: the development one.** The science board this conductor once
opened (`--kind cortex`) was retired on 2026-09-03 — 0 slots were ever opened
by it, 0 rulings came from its packets — and checking in on the science is
`pyauto-brain cortex collect --pull --apply` now, which needs no record at all.

`plan` is stdlib-only, offline and writes nothing. `collect` is the same by
default — it reads the newest batch record (`--slot` picks another; the
newest is lexical, so `-night` sorts before `-pm` on one date), scores what it
can see and prints. It has no GitHub of its own: on the web surface the
session gathers PR state with the GitHub MCP tools (`skills/GITHUB_ACCESS.md`)
and hands it over as `--evidence <json>`; `--fetch` is the laptop's shortcut,
one `gh pr view` per PR, opt-in and still writing nothing. Only `--apply`
writes — `batches/packets/<slot>.html` and the record's own stamps — which is
why it needs a stamp (`--stamp <ISO>`, else now).

Exit codes: **0** every member delivered · **1** a member needs the human
(FAILED, NOT-DELIVERED, SUSPECT, or still PENDING) · **2** usage · **4** no
Mind (no `batches/` at all).

## Running a batch by hand (there is no dispatcher yet, and that is fine)

Phase 5 — automatic fan-out — is deliberately unbuilt. Everything below works
today, costs about two minutes of tapping, and is the honest way to find out
what a dispatcher actually needs before writing one.

**In the slot — whenever the human comes in; there is no schedule:**

1. `pyauto-brain batch plan` — read the BatchDecision. Pass `--budget` if this
   slot is not a default 45-minute one. Edit the decision by removing members
   you do not want; do not add ones it rejected without reading why.
2. **Acknowledge the Heart reason set for the shift**, if Heart is YELLOW
   (`pyauto-brain vitals`). Write it verbatim into the batch record — a grant
   recorded loosely is how a scoped one becomes standing, which doctrine voids
   (`AUTONOMY.md`, "Leg 4 under a batch launch").
3. **Say when you expect to be back** — `review-at:`, an ISO timestamp. The
   shift is dispatch → `review-at:`, and the grant expires there. It is the one
   thing only the human knows, so it is stated, never inferred.
4. Open the batch record `PyAutoMind/batches/<YYYY-MM-DD>-<am|pm>.md` from the
   schema in that folder's `AGENTS.md`, and write the members, the planned
   review-minutes, `review-at:` and the reason set **before** dispatching. That
   file is what makes the launch auditable afterwards.
5. **Dispatch — `local-dev` members first** (2026-08-31): paste their lines
   into laptop CLI chats while the laptop is still on, so RAL submissions
   queue this evening — that is the priority use of the remaining laptop
   hours. Cloud members follow, each line into **its own session**. One
   session per member — they must not share one, because a single session
   would serialise them and carry one member's context into the next.
   Spawned cloud members need the **member-session contract**
   (`skills/batch/batch.md`, dispatch step 3): seed PyAutoMind as the session
   source with the bootstrap preamble, and instruct members to **end at their
   deliverable** — no PR watching, no event subscriptions, no self-armed
   check-ins after the last push; the batch review owns follow-through
   (2026-08-31: a bare-spawned wave died on missing sources, and green
   members' self-armed check-ins drained usage overnight). The rule is now
   universal, not a batch-only exemption
   (`PyAutoMind/policy/end_at_deliverable.md`).
6. **Open the packet now** (2026-08-31): write the review page to
   `PyAutoMind/batches/packets/<date>-<slot>.html` with every member present
   — overnight runs as PENDING entries — stamped `generated:`. The human
   wakes to a live page; the morning collect fills it in.
7. Go and do something else.

**At `review-at:` (or whenever they actually sit down):**

8. **Collect** — `pyauto-brain batch collect --evidence <json> --apply`
   ("The collect recipe" below). It scores every dev member, fills the PENDING
   entries in place and stamps the page `refreshed:` — normally while the
   human is already reading the finished members. A dev member without a
   green-CI PR is not `delivered:`, and collect says so first and loudly.
   Science runs are not batch members at all: `pyauto-brain cortex collect
   --pull --apply` is their check-in, and it has its own door.
9. The human reviews on the packet page — tick, choose, annotate, submit —
   and the review lands as `batches/reviews/<date>-<slot>.md` (or they
   dictate it in-chat; same review). Failures first, then `decision-taken`,
   then clean. Act on it member by member: merge (`/prm <PR>`) and write
   science rulings into the project ledgers; tweaks become follow-up prompts
   drafted for them at the **top of `queue.md`**; rejects go to
   `condemned.md`. **Follow-ups are enacted in the next batch — a review
   never executes its own follow-ups, and an open follow-up never holds the
   next dispatch** (2026-08-31).
10. Close the batch record — `reviewed-at:` (when they really sat down, which
   calibrates their own estimates), `delivered:`, `packet:`, `review:`, and
   especially **`review-minutes-actual:`**. That last number is the only
   calibration the review estimate will ever get, and everything the planner
   does rests on it.
11. Plan the next batch, and declare the next `review-at:`.

**The one leg you must not skip.** A batch launch requires the independent
adversary (`AUTONOMY.md` leg 5). Run it before reading a PR:

```
pyauto-brain review --task <name> --witness "<the prompt's Witness:>" --adversary
```

in a session **using a different model from the one that wrote the branch**. A
self-run adversary leg is an absent leg, not a weak one. `collect` cannot run
it for you and does not pretend to: with no `adversary` block in the evidence
the leg is UNOBSERVABLE and the member reaches the human as SUSPECT — the
honest state, rather than a gap that closes itself.

**What to expect from batch 1.** Small. The planner picks against a 45-minute
review budget, and with almost no prompt carrying a `Witness:` nearly everything
grades `judge` at 20 minutes — so a slot holds two or three. That number is the
honest state of the backlog rather than a limit of the machinery, and the way to
move it is to write witnesses, which costs zero review-minutes and is the best
possible fill work.

## The collect recipe

The verb answers one question — *what came back, and is it worth the human's
next hour?* — and answers it the way the Cortex conductor answers it for a
science pull: **six legs, then one health word**. It is a reader, not an actor:
it merges nothing, runs nothing and rules on nothing.

### Six legs, each PASS · FAIL · UNOBSERVABLE

| Leg | Passes when |
|---|---|
| `pr` | a PR exists |
| `diff` | the diff is non-empty |
| `checks` | every check completed |
| `green` | every check green |
| `witness` | the witness is declared, and holds |
| `adversary` | an independent adversary read it |

**No evidence is UNOBSERVABLE, never delivered.** The offline default invents
nothing: with neither `--evidence` nor `--fetch`, every leg that needs GitHub
is unobservable and its member reaches the human as SUSPECT. Inventing PASS
would be inventing evidence and FAIL would condemn healthy work — the same
choice the Cortex conductor makes for the `delivered:` legs it cannot see.

`adversary` is the leg with a rule of its own: it passes only when the read ran
under a model that is not the branch's author. **A self-run adversary leg is an
absent leg, not a weak one** (`AUTONOMY.md` leg 5), so an equal or missing
`author_model` is FAIL, not PASS.

### Six health words, in the order the human reads them

```
FAILED · NOT-DELIVERED · SUSPECT · HEALTHY · PENDING · MERGED
```

Severity order and sort order are the same list, so the top of the report is
the part that needs a person and the bottom is the part that is not finished
being work. `FAILED` is a failed check, green or witness; `NOT-DELIVERED` is no
PR, an empty diff, or checks that never ran — green is not delivered
(`batches/AGENTS.md`); `SUSPECT` is green work carrying an unobservable leg or
a flagged decision; `MERGED` and `PENDING` short-circuit ahead of all of it,
because a merged member is a retrospective and a pending one has not landed.
`delivered: n/m` counts HEALTHY and MERGED over every non-PENDING member.

### The evidence JSON

One object per member slug; every key optional, so a session supplies what it
actually looked up and nothing more.

```jsonc
{"schema": 1, "members": {
  "resampling-info-summary-section": {
    "prs": [{"repo": "PyAutoLabs/PyAutoFit", "number": 1554, "url": "...",
             "state": "open", "merged": false,
             "additions": 86, "deletions": 12, "changed_files": 3,
             "mergeable": "MERGEABLE",
             "head_ref": "feature/autofit-resampling-info",
             "head_sha": "2629933c...", "head_repo": "PyAutoLabs/PyAutoFit",
             "checks": [{"name": "tests", "status": "completed",
                         "conclusion": "success"}]}],
    "witness":   {"holds": true, "evidence": "ordering test green on 2629933c"},
    "adversary": {"ran": true, "model": "gpt-5.1",
                  "author_model": "claude-opus-4", "verdict": "CLEAN"},
    "flagged":   ["decide-and-flag: PR opened rather than parked"],
    "pending":   false,
    "summary":   "one line"}}}
```

`head_ref`/`head_repo` are the member -> branch map: the record stores no repo
or branch per member and `active.md`'s `repos:` field has four dialects, so the
PR's own head is the only reliable source. A `head_repo` that differs from
`repo` is a fork — its head is not on `origin`, so it is reported rather than
merged.

`witness.holds` is tri-state: `true` PASS, `false` FAIL, absent UNOBSERVABLE.

### Integration branches (`--integration`)

One throwaway worktree root per slot under `$PYAUTO_WT_ROOT`, built by
`bin/worktree.sh` with `PYAUTO_WT_BRANCH=integration/<slot>`. Every affected
repo becomes a real worktree on `integration/<slot>`, cut from `origin/main`,
with every member's head branch merged in **dispatch order** — so the human can
*run* the whole batch before ruling on any of it, and "how would these resolve
at the end?" is answered by a merge rather than by reading diffs.

**It fetches and reads; it never pushes, opens a PR, or touches a remote ref.**
Like `--fetch` it is opt-in, non-default and laptop-only — a cloud session is
pointed at the laptop rather than failing halfway through a root it cannot
finish. Pushing `integration/<slot>` is a separate, later decision, and a
separate flag — see `--push` below.

```jsonc
{"slot": "2026-09-03-pm",
 "root": "~/Code/PyAutoLabs-wt/integration-2026-09-03-pm",
 "activate": "<root>/activate.sh", "branch": "integration/2026-09-03-pm",
 "at": "2026-09-03T08:00Z",
 "repos": [{"repo": "PyAutoLabs/PyAutoFit", "dir": "PyAutoFit",
            "path": "<root>/PyAutoFit", "branch": "integration/2026-09-03-pm",
            "base": "origin/main", "base_sha": "…", "head_sha": "…",
            "merged": ["autofit-resampling-info"],
            "conflicts": [{"member": "autoarray-x", "branch": "feature/x",
                           "paths": ["src/mask/mask_2d.py"]}],
            "status": "clean | conflicted | skipped", "note": "",
            // --push only; "" and false on every run without it
            "remote_branch": "integration/2026-09-03-pm", "pushed": true,
            "push_note": ""}],
 "pushed": false, "sweep_after": "",
 "notes": ["…"]}
```

`status` is the merge verdict and `pushed` is the network one; they are
deliberately separate. A push that fails leaves a clean integration reading
`clean`, because whether the merge collided is a fact about the merge and a
dead network does not change it.

**Four reasons a member's PR is left out**, each said out loud: it is already
merged; it is CLOSED; it has no `head_ref` in the evidence (gathered before the
head fields were asked for — re-run `--fetch`); or its head lives on a **fork**,
whose branch is not on `origin` and cannot be merged from a local checkout at
all. A repo with no local checkout under the workspace root is dropped the same
way.

**Nothing is resolved.** A member whose merge conflicts is left OUT of that
repo's branch and named with the conflicting paths; the merge is aborted and
the next member is tried. **That report is the product** — it does not change
the exit code, and it does not change any member's health word. A member's
health is about *its own* delivery; a merge collision is a property of the
*slot*, and mixing them would make a green, delivered member read as SUSPECT
because a sibling touched the same file.

**A dirty integration worktree is skipped, never reset.** The branch is re-cut
from `origin/main` on every run (`checkout -B`), because the merge result is a
function of the current base and the current heads — a second run stacked onto
the first would preview a base that no longer exists. That is safe only because
the one thing a re-cut could destroy, a human's uncommitted experiment inside
the review root, is refused outright and reported. **That refusal, not the
branch policy, is the safety property.**

`activate.sh`'s `PYTHONPATH` covers the libraries, so a **library** member's
change is live anywhere once the root is sourced. A **workspace** member is a
real worktree in the root but is not on the PYTHONPATH, so its script must be
run from inside `<root>/<workspace>`.

**Collect does not rewrite your `--evidence` file.** That file is an *input*;
`--apply` writes exactly two things, the packet and the record's stamps. The
computed block is emitted on `--json`, rendered into the packet and stamped on
the record as `integration-root:` — persisting it is `--json > ev.json`'s job,
and a block pasted back into an evidence file is how a cloud session renders one
at all.

### Pushing the integration branch (`--push`)

`--push` publishes what `--integration` built. It **requires** `--integration`
(without it, a usage error and rc 2) and it is refused on `plan` — and no
record can ask for it. `- integration: yes` is a request for the *local*
preview; putting a ref on GitHub is a separate act, typed at collect by the
human, because it writes into shared repos under the laptop's own credential.
Laptop lane only, for the same reason `--integration` is: a cloud session's
credential cannot write a ref at all, so it is pointed at the laptop rather
than failing halfway.

**What it publishes.** One real branch per repo — `integration/<slot>` — whose
tip is exactly the state `--integration` merged. A **conflicted** repo still
publishes: its branch carries the members that merged, and the ones left out
are named, with their conflicting paths, in the same report. A pushed branch is
therefore never a claim that the whole slot merges; it is the same partial
preview, on a machine the reviewer can reach.

**Never a PR, never a base.** These refs are review scaffolding with a
death date, not proposals. Nothing opens a pull request from one, nothing
targets one as a base, and nothing merges one anywhere.

**Never forced.** Three arms, decided per repo after re-fetching the
`integration/*` namespace:

- the remote branch carries the **same tree** → not re-pushed at all, and said
  so. This is the common case on a refresh: `--integration` re-cuts and
  re-merges honestly, so the commit SHAs differ every run even when nothing
  changed. Compare trees, not commits, or every refresh mints a new name.
- the remote branch is an **ancestor** → a plain fast-forward push.
- otherwise → published as `integration/<slot>-2` (then `-3`, …, first free
  name, capped). The earlier ref is left exactly where it was. There is no
  `--force` and no `--force-with-lease` anywhere in this path; `branch -f`
  appears once, on a *local* name already proven absent on origin.

A push that fails is a note and a `push_note` on the row, never a change to the
merge verdict.

**How it ends.** Every push stamps `integration-remote:` on the record and
fills `sweep-after:` (see below); `bin/branch_sweep.sh --records <a checkout of
PyAutoMind/batches>` deletes `integration/*` refs on or after that date and
protects them in every other case — no records dir, no record, no date, no
deletion. That expiry is the only thing keeping these refs from accumulating:
they can never be proven contained in `main`, so the sweep's ordinary
containment gate would keep them forever.

### The packet is refreshed, never rewritten

`--apply` writes `batches/packets/<slot>.html` in place and at the same path,
because the human's chips and notes live in `localStorage` keyed by the page
(`batches/packets/TEMPLATE.md`) and a moved file orphans them. Every member
owns a section with a stable `id="m-<slug>"`; a refresh replaces that span and
leaves **every other member's markup byte-identical** — a PENDING stub becomes
a full block under the same id, and nothing a neighbour's stored notes are
anchored to moves. The regenerable non-member regions (stamp, tiles, rulings
needed, sidenav) are bounded by `pyauto:*` sentinel comments; a hand-authored
archived packet has none, so it gets its member splices plus a note saying the
header was left alone. Collect never rewrites such a page wholesale.

### What it stamps on the record

`--apply` edits the batch record line by line, never re-serialising it:
`collected:` once (the first collect owns it), one `refreshed:` line per apply,
`delivered: n/m`, `packet:`, and — after an `--integration` run —
`integration-root:` (a key of its own: the dispatch-time
`- integration: yes` is the human's request, and is never overwritten
with a path). After an `--integration --push` run it also writes
`integration-remote:` — `<Repo>:<branch>`, comma-separated, under the repo name
`branch_sweep.sh --name` matches on — **rewritten on every push**, because the
current publication is the truth and a stale list would send the sweep after a
ref that no longer exists. Alongside it, `sweep-after:` is **filled once and
never overwritten**: `review-at:` plus a week by default, and a date the human
typed is a decision about their own review. Member outcomes become `<HEALTH> (<one line of evidence>)` —
**unless the outcome already opens with a ruling word**
(`ACCEPTED`, `REJECTED`, `MERGED`, `LEAVE-TO-FINISH`, …), which is a human's
verdict and is never overwritten by a machine re-read. Once the slot's review
has landed, **no member line changes at all** — the record is the history of
a batch that closed, and the pm record's `PR OPENED AT REVIEW (…)` sentences
are exactly the outcomes no word list would have protected. The write is
rehearsed on a throwaway copy and refused if a member line or a key would be
lost; the `notes: |` block is never touched.

Two **blocks** are stamped alongside those keys, both derived and both rewritten
on every apply of an open record (and filled once, then left, on a closed one —
its contents are history, like `delivered:`):

- **`outcomes:`** — one `<slug>: <merged | rejected-at-review | carried |
  unreviewed>` per member. This is the *accounting*; the member line's outcome
  column is the *evidence* ("PyAutoFit#1554, 4/4 checks green"). It is read
  from the ledger and nothing else: a `complete/` record that names the member
  (`- batch: <slot> — member `<slug>``, or a record filed under the member's
  own name) → `merged`; a review `decision:` that rejected it →
  `rejected-at-review`; a row still in `active.md` → `carried`; otherwise
  `unreviewed`. In that order, because a rejected member is still in
  `active.md` and a merged one may be too. All nine members of the
  2026-08-31-pm slot merged and every one of them was recorded
  `decision: UNREVIEWED` — the completion records knew, and nothing read them.
- **`merge-order:`** — the `/prm` sequence, as advice and never an action:
  dispatch order (the order the human listed the members in — the only stable
  order there is, since `members` is sorted by health), with library repos
  first (the library-first merge gate) and same-repo members serialised (the
  first merge moves `main` and stales its siblings' evidence). Nothing is
  filtered: a member with no PR is listed in its place with what it is waiting
  on, because an order that silently omits a member is an order somebody merges
  out of. It is rendered in the collect report's summary too.

### The close leg

**`dev` — collected once, reviewed once.** A review that has landed closes the
batch outright. Where `batches/reviews/<slot>.md` exists, collect **refuses to
write the packet** — that file is the record now, and rewriting the page the
human ruled on destroys what they ruled against — and instead fills
`reviewed-at:`, `review-minutes-actual:` and `review:` from it — **fills,
never overwrites**: a value the record already carries (anything but blank or
`(not given)`) is the human's and stays. The decisions inside are reported,
never enacted: merges, follow-ups and rejections are the orchestrator's next
act with the human, not collect's. The review button lives on `collected:` —
there is exactly one packet to press it on, because a dev batch is dispatched
at once and reviewed at once.

**`cortex` — a rolling board, reviewed as many times as it takes.** A review
landing does **not** by itself refuse the packet write: `PyAutoCortex/batches/
AGENTS.md`, "The first review does not close the slot" — the human rules on
whatever is reviewable whenever they come in, and the packet keeps refreshing
under whatever is still on the board while they do. A later sitting lands as
`batches/reviews/<slot>-r<N>.md` (N ≥ 2; the first sitting is `<slot>.md` — see
"Two kinds, two records" below), and each one adds its own `- review:` line to
the record rather than replacing the last. What a review DOES do, on every
kind, is take its own members out of further splicing (`_on_the_board`): a
member the record already shows `ruled: yes` for is never re-rendered, on this
sitting's collect or any later one — its packet span is what the human was
shown. The record's `delivered:`/`packet:` keys are filled once the slot is
CLOSED — nothing left in a board state, carried members excluded — and moved
on every refresh until then; `reviewed-at:`/`review-minutes-actual:` still
fill from whichever sitting sets them first, and `carried:` is written once
per member the moment a sitting finds it still running.

### The extension point

Scoring is registered per member **kind** (`KINDS`) — a scorer plus a block
renderer, over the one flat scored shape the report and the packet both read.
`dev` was the kind that shipped first; the science kind (`cortex`) now ships
here too, over the phase-2 Cortex conductor's own `score_phase` and
`member_block` rather than a second collect. A third kind is a scorer, a block
renderer and a claim function — nothing else moves.

## One kind, one record

`dev` reads the Mind, and that is the whole roster. A second kind — `cortex`,
a science phase on a rolling board with its own record, packet, chips and
carry-forward — existed from 2026-08-31 to 2026-09-03 and was retired: 0 slots
were opened by the conductor, 0 rulings came from a packet, 0 partial reviews
were ever filed. What the human actually does with the science is check in on
the runs, which is `pyauto-brain cortex collect` (`agents/conductors/cortex/`).

The extension point above (`KINDS`) is what made that possible and is kept: a
member kind is a scorer plus a block builder plus a claim, and nothing about
the record, the packet or the renderer has to learn its vocabulary.

## Slicing a `needs-slicing` prompt (`slice`)

```
pyauto-brain batch slice <prompt>                      # propose; writes nothing
pyauto-brain batch slice <prompt> --slices plan.md     # cut from a plan file
pyauto-brain batch slice <prompt> --apply [--mind P]   # write children + epics.md
```

A prompt too large for one unattended run is a decomposition problem, not a
scheduling one. `slice` proposes **two to four** children of a prompt grading
`Unattended: needs-slicing`, offline and stdlib-only.

**The cut is declared, never invented.** Where work divides is a semantic
judgement no stdlib heuristic makes honestly, so the candidate slices come from
the parent's own `## Slices` (or `## Phases`) section, or from an
agent-authored plan file passed with `--slices` (the same numbered items; the
heading optional). One numbered item per slice:

```
1. **Library core.** What it does. *Repos:* PyAutoFit
   *Witness:* `pytest test_autofit/thing` passes. *Consequence:* glance.
2. **Workspace example.** ... *Witness:* the example runs in smoke. *Depends:* 1
```

`*Witness:*` is required; `*Repos:*`, `*Consequence:*`, `*Difficulty:*`,
`*Lane:*`, `*Review-minutes:*` and `*Depends:*` are optional (repos default to
the parent's repos the item names). The verb renders each child — the parent's
`Type`/`Autonomy`/`Priority`/`Themes`, `Epic:` + `Phase:`, and a `## Seam`
section naming what it owns and what comes before and after — and the sizing
faculty (`judge_slices`) judges it against the seam rules:

1. **one unattended run** — the child must grade `Unattended: ready`;
2. **its own witness** — none is refused as *a smaller judge task, not a
   slice*;
3. **independently revertible** — it names a repo, and depends on no later
   slice;
4. **repo-boundary seams, library before workspace** — warnings, not refusals.

Fewer than two or more than four slices is refused. Revertibility beyond rule 3
is the human's to read off the proposal.

Without `--apply` it only prints (`--json` too). `--apply` writes only a clean
proposal: the children beside the parent as `<parent>_s<N>_<title>.md`, never
overwriting, plus an `epics.md` entry with the parent as its **ledger** unless
the parent already is one. The parent is never renamed, retired or edited —
that is the human's call. `/intake` offers the verb when a freshly filed prompt
sizes `needs-slicing`. Exit: **0** proposed · **1** refused · **2** usage ·
**4** no Mind.
