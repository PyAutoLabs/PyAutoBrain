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
| **One `Phase:` task per epic per batch** | epic phases are ordered, so two members could not run in parallel anyway — and this is what interleaves small pieces of long programmes with standalone work. A side task of the epic (no `Phase:`) is not counted and orders itself by `Blocked-by:` (ruling R5, M3.6b) |
| **`Unattended: ready` only** | `needs-slicing` goes to the decomposition pass (`batch slice`); `never` never enters a batch |
| **Lane match** | a session detects its own lane and plans only that one |
| **No Lane, no unattended pick** | a backlog draft with no valid `Lane:` is excluded from every unattended plan (the default, and the watcher) and the plan says so; `--attended` reads it as `any`. A lane-less draft that needs the laptop, RAL or private data would otherwise reach a cloud worker (M2.3, `AUTONOMY.md` "M2 rulings — 2026-11-12") |
| **Empty queue, no dip** | an empty or absent `queue.md` stops an unattended shift's backlog dip; a brief's named tasks still run (M2.3) |
| **Not `looks-shipped`** | a draft the close-out guard (`intake looks-shipped`) flagged with strong evidence that its work already shipped waits until a human closes it or lists it in `PyAutoMind/looks_shipped_dismissed.md`; the flags are read from `PyAutoMind/looks_shipped.json` at plan time, so a dismissal takes effect at once. The 2026-11-05-am batch proposed two shipped drafts. |
| **Backpressure** | see below |
| **Brief scope** | under a shift brief, only its named tasks and the backlog its dip policy covers run; anything else is a dispatch outside the launch, which "What a batch launch is" forbids (`AUTONOMY.md`, 2026-11-03) |
| **Merge cap** | unattended `glance` merges stop at the brief's `merge-cap:`; each merge moves `main` and stales the next member's evidence, and the cap bounds what one unread shift can change |

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

**A queued epic ledger queues its members** (PyAutoBrain#696). A `kind:
prompt` entry whose prompt is an epic ledger (`Epic:`, no `Phase:`, `Status:
campaign map`), or which `epics.md` lists as an epic's `- ledger:`, makes every
member of that epic count as queued at the ledger's rank (`queue_standing`, the
one test of "is this queued?"). So the backlog-reach ruling no longer keeps a
medium or multi-repo phase out. Every other gate still applies: phase order,
`human-required`, `Unattended:`, `Blocked-by:`, Witness, lane, repo holds and
budget. A queued phase or side task queues only itself. `batch plan` (text and
`--json` `queued_epics`), `brief --check` and the digest give one line per
queued epic: what it takes, or why nothing (its next phase and each member's
gate, or "no draft prompt" — file it from the epic's Continue prompt in an
attended chat).

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
`backlog: scoped` to their `epics:`/`tags:` (else `scoped` by `tiers: notify,
glance`, M3.6b), plus the epics of `queue.md`'s queued ledgers, `merge-cap: 0`,
and `lanes: any local-dev ral` with a `ral-allowance:` of 2 packets, partition
`ral`, 64 cpu-hours (PyAutoBrain#696; edit either per shift). It prints to stdout (`--out FILE` writes it) and never writes a
record into `batches/` — saving it there is the human's dispatch.
`goals.md` is written by the human alone (by hand or in chat), so every goal
is copied as their word; `--new` also prints on stderr how the goals changed
since the newest brief. `brief --check` warns when `goals.md`'s goal 1 is
missing from a brief (PyAutoMind#565; readers in `_steer.py`).

**The launch preflight (M3.6a, PyAutoBrain#659).** With `--out`, `brief --new`
first makes the shift issue: one `gh issue create` on the Mind's `origin` repo
(`create_shift_issue`), written as `- issue: <url>`. It runs in the launch
chat, never in the watcher (AUTONOMY.md, the 2026-11-17 exception to "The
Brain reads no network"). A file that already names an `issue:` keeps it, so
a re-run never makes a second; `--issue <url>` names one by hand;
`PYAUTO_BRIEF_ISSUE=off` skips it. The issue is made last, just before the
write: if `gh` fails, no brief is written (exit 1), and if the write fails
after it, the URL is printed to re-run with `--issue <url>`.

**The RAL probe (2026-11-22).** For a live brief whose `lanes:` include `ral`,
`brief --check` runs one `ssh -o BatchMode=yes <host> true` (`_ral.py`) and
warns when unattended key auth fails — shift 2026-11-20-am granted `ral` and
its worker parked on "Too many authentication failures". A warning, never a
refusal; launch chat only, never the watcher. The host is
`PYAUTO_RAL_SSH_HOST`, else the "SSH alias" in the Mind's
`policy/hpc_ral.md`; `PYAUTO_RAL_PROBE=off` skips it.
`brief --check` then adds what only a launch needs (`_brief.launch_errors`,
`login_findings`): a live brief (not `shadow: yes`) without a GitHub issue URL
is refused (`issue: missing — …`), and so is a CLI login that has expired
("login: CLI login expired: run `claude /login`") or that expires before
`review-at:`. The login is read by `_login.probe`: `claude auth status
--json` (`loggedIn`, `loginExpiresAt`), no model call; a probe that cannot
tell only warns, and `PYAUTO_LOGIN_PROBE=off` skips it. `_brief.check` itself
is unchanged: the watcher's open-brief gate does not require `issue:`.

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

`bin/orchestrator_watch.py --mind <PyAutoMind>` finds the brief and runs **one
tick** of it (finding it is below, "Which brief"); `STOP` first, then the open-brief gate, the tick lock, the lease reap,
the plan inside the brief, the caps (`max-workers:`, default 4;
`max-sessions:`, default `max(2 × max-workers, ceil(token-budget / 150k))` when the
brief has a `token-budget:`, else 8 — M3.6c) and an exclusive-create lease per
spawn; `first: glance` starts ready glance work before named judge tasks (spawn
order only: what the plan selects is unchanged). The plan
is checked against Mind `origin/main` (#632): a draft not under its `draft/` or
claimed in its `active.md` is excluded unless this shift picked it, read from the
local `origin/main` ref after one `git fetch` per shift through the one Mind
writer's own fetch (never a pull); an unreadable ref fails closed. From
PyAutoBrain#637 the same read also skips a task whose declared repo (`Repos:`
header and target) a claim in that `active.md` holds, unless the claim's
`coordination:` or `conflict-override:` line names that task (ruling R2, M3.6b;
a shift's dip also skips a draft with no `Witness:`, counted in the digest, and
`brief --check` lists each named task that will not start and applies the
organ rule to it); a task an earlier shift in the same
home left parked on a question is not startable until a later shift finishes
it or a brief names it again; a dip never takes a Brain, Mind or Hands target;
a `backlog: scoped` dip beyond `queue.md` takes only small single-repo tasks
(ruling 2026-11-16; a queued epic ledger queues its members, #696); a re-dispatch goes first and may pass `max-sessions:` by
one; and a worker's token reservation is the larger of the even share and the
mean spend of finished workers in this and the last three shifts. State lives
under `$PYAUTO_ORCHESTRATOR_HOME` (default `.orchestrator` under the worktree
root), one directory per brief: `STOP`, `leases/`, `counters.json`, `tick.log`.
Until phase 3b it spawns only stub workers (`PYAUTO_ORCHESTRATOR_FAKE=1`); a real
dispatch is refused. Doctrine: `AUTONOMY.md` "The watcher's network surface —
2026-11-03"; the exemption it runs under, `PyAutoMind/policy/shift_watcher.md`.

**A library is held while its worker runs; merges wait in PR order (M3.6j,
2026-11-19, PyAutoBrain#683).** The plan admits one *live* task per library
repo, so two workers never share one. Work does not collide; merges do. A task
this shift picked holds its library while its worker runs and while a
re-dispatch is pending. A park holds it for 15 minutes from the park
(`PARK_HOLD_GRACE`; ruling d as amended 2026-11-24, PyAutoBrain#720): a lease
park (on a question or a person) and an outcome with an open question. The
park time is `counters["park_times"]` (the lease's `parked_at`, or when the
`.done` was read), else the inbox entry's `asked`, taken at the end of its
minute; with no known time the park keeps holding. A lease-parked task that
later writes a `.done` with a question keeps its lease park time. Only an open
question (not obsolete, not merged) is a park. Inside the 15 minutes the
waiting task is refused as `<repo> held by <task> (parked) until HH:MMZ` and
counted `startable`; it starts on the first tick after them.

A lease park's session is still alive, so its library is released only once
that session is stopped (human ruling 2026-11-27, "Stop, then release").
When its 15 minutes end, `stop_expired_parks` stops it through `/kill`'s stop
(`_stop_session`: `claude stop <id>`, or the Codex supervisor's STOP file),
records `park_released[task]` (`how: stopped`) and a `park-stopped` event, and
moves the task from `parked` to `done` with its inbox question as the
outcome's open question. From then on it is a park on a question: an answer
restarts it with the answer (`released_here`) once its library is free, and
its old lease is reaped when the session has ended. The stop is skipped while
the shift is paused. Fail closed: no session id, no question in the inbox, or
a failed stop keeps the hold, is recorded in `park_stop_failed` (one
`park-stop-failed` event, needs you) and is tried again next tick. A lease
park whose session ended by itself (`parked-ended`) is released by the 15
minutes alone (`how: ended`). An answered park waiting to restart
(`inshift_pending`) keeps its library until it starts, so no other task on
that library goes ahead of it. Once its
worker has ended, the next tick may start the next task on that library, its
PR open, refused or merged alike (`released_picks`; first PyAutoBrain#679 freed
it only at merge, and one `/prm`-bound PR stalled the shift). A `/drop`ped task
with no live worker holds nothing. The finished task stays in the plan, so it
is never re-dispatched, and a claim its own shift worker left in `active.md`
holds nothing either. The next worker's prompt starts with `SIBLING_NOTE`,
naming this shift's open PRs on that library: branch from `main`, never stack;
end `obsolete` if a sibling already does the task; a `worktree_check_conflict`
hit naming only a listed sibling's slug is not a conflict (ruling e). The plan's
reason for a held task is `<repo> held by <task> — will start once <task>'s
worker ends` (named) or `<repo> held by <task> while its worker runs`.

**The open-brief gate is a window: `dispatched:` → `review-at:`.** A brief
that passes `batch brief --check` is open only from its `dispatched:` until its
`review-at:`. Before the start, a tick is idle (`not yet open: opens at
dispatched …`) and touches nothing, not even the slot directory, so a brief may
be landed early. Until 2026-11-05 the gate ignored `dispatched:` and a brief
opened the moment it landed (pilot shadow shift 1 opened a day early;
PyAutoBrain#589). `batch watch` says `not yet open — opens in …` before the
start.

**Which brief (M3.6a, PyAutoBrain#659).** The watcher reads the briefs itself
from Mind `origin/main` (`shift_briefs`: a local `git ls-tree` / `git show`,
never a fetch), so only a pushed brief opens. It ticks the one open brief
(`dispatched:` <= now < `review-at:`) and every late one (`review-at:` <= now
< + 45 min, for the digest and the late sweep). Two open briefs tick neither:
the tick prints `idle: two open briefs on origin/main (a, b)`. A pushed brief
missing from the checkout's working tree is not ticked (`pushed, but the Mind
checkout is behind`). A brief past its late window is still ticked, for up
to a day, while its slot owes something (`late_owed`: no digest yet, a post
retry due, a queued Mind op), so a laptop that was off catches up. Past that
day it is not ticked again; the first tick after says once (`abandoned: <slot>
past catch-up (<what it owes>; N leases)`, marker `abandoned.noted`) so the
human runs `batch digest` and closes it by hand. The tick
reads the local `origin/main` ref and never fetches it: the Mind checkout it
reads must be fetched (or the brief pushed from it) before launch, or the
tick idles `no open brief`. `--brief` or `$PYAUTO_SHIFT_BRIEF` is an override:
while that brief is open it takes the open brief's place; in its late window
it is one more late brief, ticked beside the open one; otherwise it is
ignored, so a stale env file never displaces the next shift.

**The end: `review-at:` + 45 min.** Once the late window
(`_brief.LATE_WINDOW_S`) has closed and nothing is owed (the digest posted, no
post retry due, no queued Mind op), a tick of that brief returns
`idle: late window closed at …` before the lock: no reap, no lease renewed, no
`tick.log` line. A worker still out by then is in the digest, for the human.

**The tick, the kick and the early close (M3.7c, PyAutoBrain#690).** The timer
ticks every 60 seconds. `worker_env` sets `PYAUTO_SHIFT_KICK` to the kick file
(`kick_path`: `$XDG_STATE_HOME/pyauto/orchestrator.kick`, else
`~/.local/state/pyauto/orchestrator.kick`, systemd's `%S`). A worker appends a
line to it after its `.done`, and a close-out or branch update after its
`.closeout`, best effort. `bin/systemd/pyauto-orchestrator.path` starts a tick
when the file changes. `PathChanged` is edge-triggered: a kick that lands
while a tick runs is dropped, not queued, and the timer picks it up within 60
seconds. The service has no start limit (`StartLimitIntervalSec=0`) and the
path unit allows 20 triggers in 10 s. The
shift closes early on the tick that leaves nothing to do (`early_close_ready`):
not paused, not shadow, something started, no live lease, no re-dispatch owed,
no close-out or update running or waiting on its new head, every PR judged
(refused, merged, or waiting in merge order), and no task that could still
start (`startable`: a failed launch, an unreadable spend, an expired login).
Nothing this tick could not read: the steering comments (`commands_unread`)
or Mind `origin/main` (a draft held as `fail closed`) keeps it open. A
task held by a library, `max-sessions` or the token budget cannot start, and a
task parked on a question does not hold the shift open. A task held only by a
park whose 15 minutes still run can start when they end, so it is `startable`
and keeps the shift open until then (PyAutoBrain#720). `close_early` records
`counters["closed_early"]` and runs `finish_shift` with that time as the end.
The digest opens with `Closed early at <time>; review-at was <time>`. Later
ticks in the window run the late sweep while something is owed, else idle;
they read no steering, so an `/add` after the close does nothing.

**S7: `decision-taken` at PR-open (M3.7c).** `_start_closeouts` reads a new
PR's labels right after the tier check (`labels` in `gh_pr_state`, kept in
`counters["pr_labels"]`, once per PR per shift, after the carried-PR check;
unreadable means wait, at most one read a tick; after 3 misses over 15
minutes from first seen (`LABEL_READ_GRACE_S`) the PR goes to `/prm` as
`labels unreadable`, counted in the digest). A
`decision-taken` PR is refused (`decision-taken — the human's /prm`) with no
close-out, no merge slot and no CI read. It stays an earlier PR in the merge
order, so later PRs on its library wait until GitHub says MERGED or CLOSED.
The digest's `### Waited behind your /prm` names them, one line per library.

**S4: the shift-end sweep and the red block (M3.7e, PyAutoBrain#692).**
`_sweep.py` holds the mechanics; `config/policy.yaml` `shift_watcher:`
names the workflow (`sweep_repo`, `sweep_workflow`, `sweep_siblings`). At
close, `finish_shift` dispatches the Workspace Smoke workflow once
(`gh workflow run`, no inputs, marker `sweep.dispatched`) when GitHub
confirmed a merge this shift on a library, workspace or Heart chain repo.
`late_sweep` makes it instead when a close-out merged after the close. A
shadow shift never dispatches, and a failed dispatch is not retried. Each shift tick makes one
`gh run list` of the workflow on `main`, before steering. Each run's
artifacts are downloaded once per run id, at most 3 tries, into
`<home>/sweep/`, which every shift shares. When the latest completed run (a
cancelled one is skipped) is red and not cleared, `_start_closeouts` refuses a PR on a failing
workspace's chain (Heart `config/repos.yaml` `smoke:`, read locally, plus
the workspace repo from Heart's validation workflow) as `workspace sweep
red: <url>`, right after the S7 check. An unmapped workspace or an
unreadable report blocks every library, chain and workspace repo. A run
list failing for 30 minutes from the streak's first failure holds those
PRs in `counters["sweep_waits"]` instead (a wait, re-judged each tick, no
refusal), and `early_close_ready` keeps the shift open. A failed read whose
previous read was another shift's (`read_shift`), or over 2 hours old
(`SWEEP_STREAK_GAP_S`), starts a fresh streak. A running close-out on a
blocked repo gets `leases/<task>.sweep-red` and refuses before it merges;
a marker the current block does not cover is removed.
A later green run clears the block, as does `/clear-sweep`. The latest
red run, cleared or not, files one bug draft (`draft/bug/<most upstream suspect library>/
workspace_sweep_red_<id>.md`, marker `sweep/drafted/<id>`) through the one
Mind writer, with suspect PRs from one compare read per affected repo. All
these calls use the human's own `gh` login (decision b). The digest's
`### Workspace sweep` names the dispatch, the verified SHA per library and
any red block. Nothing in the watcher reverts or bisects.

**Deploy.** Installing the units is the human's step, when no shift is live:

    cp bin/systemd/pyauto-orchestrator.{service,timer,path} ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user restart pyauto-orchestrator.timer
    systemctl --user enable --now pyauto-orchestrator.path

If the path unit ever shows failed (trigger limit hit, systemd 250 or later),
run `systemctl --user restart pyauto-orchestrator.path`. On systemd 249 the
`TriggerLimit` keys are ignored with a warning.

**The login hold.** A real spawner probes the CLI login (`_login.probe`) when a
member waits to start and the last probe was not `ok` (the shift's first
spawning tick, and each tick after an expiry), and again whenever a worker
shows `blocked`. An expired login holds every spawn and is its own
`login-expired` event ("CLI login expired: run `claude /login`. No worker
starts until it passes."), a needs-you comment on the shift issue, never a
worker "blocked on a person". It is kept in `counters["login"]` and in the
tick's result.

**Real workers (phase 3b).** Without `PYAUTO_ORCHESTRATOR_FAKE=1` each spawn is
`claude --bg --name shift:<task> --model opus --effort medium --permission-mode
<worker-mode> <prompt>` (`WORKER_MODEL`/`WORKER_EFFORT`, PyAutoBrain#672), the
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
refusal with its reason: `counters.json` keeps one entry per task and reason
class (a token reason without its running figure) with its count and first and
last time, and each shift-wide reason (`max-workers`, `max-sessions`, a token
reason) is one line for all the tasks it held back (#632). A real worker holds a reservation from its spawn (default
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
(`--task <task>` then `append | write | edit | move | remove | drop-section |
table-append | set-header | queue-retire`; every path must be *ledger* by
PyAutoMind's own `scripts/ledger_merge.py`, default deny). `write` only
creates; `edit` replaces an expected old text that must appear exactly once,
so it never clobbers a concurrent change. `shift_ledger.py` refuses at queue
time a `write` to a path already on Mind `origin/main` (or created by a queued
op), an `edit` whose base is not there, and a `table-append` whose `## `
heading or table is missing, so the worker can switch while it runs. Each tick, after
the reap, `_mind_writer.commit_ledger` applies all pending ops in a temporary
detached worktree on `origin/main`, commits once and pushes; if `main` moved it
replays the ops on the new `origin/main` (up to three tries). It never resets,
never forces, and never touches the canonical checkout's working tree.
Committed op files move to `ledger/committed/`. One bad op never strands the
rest (#632): a re-dispatched task's repeat of a claim this shift already
committed, with main's content matching it, is a skipped note; the same shape
from anyone else is a conflict, set aside; any other worker op that is invalid
or cannot apply is set aside in `ledger/set_aside/` — and the rest commit. A
task's ops land together (#660): its closing ops (the `complete/` record,
`drop-section`, the `active/` prompt's `remove`, `queue-retire`,
`question-retire`) apply last, and are *withheld* — set aside, not retried —
when any op of that task was set aside for a human this shift, so Mind never
records it shipped with a change missing. They apply as one group per task: if
one fails for a human the group is rolled back and withheld; while a sibling
op is *held* (retried) the group stays pending beside it; an op on a path the
group creates (an edit of the `complete/` record) is part of the group. A
`drop-section` paired with an `append` of the same task re-adding that
`## slug` to the same path is not closing but an *update* of the worker's own
claim (2026-11-18, PyAutoBrain#681: a worker's PR-open claim update was set
aside as a conflict): the drop applies just before its append, as one unit,
and only when main's section is one this shift committed or its `- session:`
names this slot's shift worker — anyone else's is a conflict, set aside. Two
limits: a `complete/` record committed in an earlier tick than a sibling that
fails later stays on main (the NEEDS YOU line and the digest say "already on
main"), and the block is sticky for the shift — a re-dispatched task's record
is withheld too, for the rest of the shift. An op that is already true on main
(an edit already applied, a write of the same text, a remove of a gone file) is
set aside as *mechanical*: a digest line, never a NEEDS YOU; a task's human
set-asides are one NEEDS YOU event naming the task. The
watcher's own ops (record appends, pilot row, live line, stage-2 rows) are never
set aside: they are held pending and retried. Every note, set-aside, conflict
and hold goes to `ledger/report.jsonl`, into the digest, and after `review-at:`
into a late line and the correction. A re-dispatched worker is told its claim
may already exist. **Enforced, not asked:** a worker runs with
`PYAUTO_SHIFT_WORKER=1`, `PYAUTO_SHIFT_LEDGER_DIR`, and `core.hooksPath` (via
`GIT_CONFIG_*`) pointing at `bin/worker_git_hooks/`, whose `pre-commit`
refuses any commit in a PyAutoMind repo — `prompt_sync_push`, `lifecycle close`
or a raw `git commit` alike — and otherwise chains to the repo's own hook.
These variables (and `PYAUTO_SHIFT_BRIEF`, `PYAUTO_SHIFT_KICK`) travel to every
worker, update and close-out as `claude --settings '{"env": …}'` (`shift_env`),
because `claude --bg` hosts a session on a daemon spare that keeps the
environment of whoever started the daemon, not the caller's (PyAutoBrain#724);
`worker_env` stays as the backstop. Every ledger reader refuses a ledger whose
slot is not the brief's: the Python readers through
`_mind_writer.shift_ledger_dir`, and `bin/worktree.sh`'s
`_worktree_release_queued` with the same check in shell (it warns and treats
the claim as still held). Not fixed: a human `claude --bg` on a daemon a worker
started can still inherit worker variables (CLI behaviour), `PYAUTO_SHIFT_BRIEF`
among them, which the watcher CLI honours as an override only inside that
brief's own window.
With that in place real dispatch no longer needs `sandbox: yes` (human,
2026-11-03); the key stays as a test-shift marker.

**The digest (phase 3d).** Every spawn records, in `counters.json` `picks`,
the prompt, its tier and **why the brief admitted it** (`_brief.pick_reason`:
`named task`, `scoped epic|tag|tier <x>`, or `backlog: fill-idle`) — at
dispatch, because by `review-at:` the prompt may have moved to `complete/`.
The reap keeps what the worker left before deleting its marker: the `.done`
lines go to `outcomes` (`<url>`; a `merged <url>` line, which no shift
worker writes since 2026-11-19, is still recorded as an in-turn merge), and `<task>.proof.md` moves to `<slot>/proofs/`. The first tick after
`review-at:` runs `finish_shift` once: `_digest.build` writes the `## Digest`
(`PyAutoMind/batches/AGENTS.md` format — first a numbered review table grouped
by the human's next action (#718), then brief work, backlog picks each with
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
recorded tier is `glance` or `notify` (ruling R3, 2026-11-17; since 2026-11-19
every `notify` PR comes here, its worker having ended at PR-open — ruling "ii",
PyAutoHeart#352), `gh pr checks` is running or green (ruling S5, M3.7b:
the close-out starts at PR-open; red or unknown is refused; none at all waits
`UPDATE_CHECKS_GRACE_S`, 600 s, from when the watcher first saw the PR in
`counters["pr_seen"]`, then is refused), the shift is not shadow,
`review-at:` is more than 20 minutes away, spend is under 1.5×
`token-budget:` (#632; AUTONOMY.md "Close-out budget — 2026-11-14"), and —
last — a merge slot is free under `merge-cap:` (`_merge_slots.room`, counting
the merge close-outs already running without one). The watcher takes no slot
for a merge close-out (decision A): the session takes it itself with
`pyauto-brain merge-slot take` immediately before the merge, and the reaper
frees it when the close-out refuses, whoever holds it for that task. Then the
watcher starts **one** close-out session
(`closeout_template.md`; `claude --bg --name shift-close:<task> --model opus --effort medium`),
with a CI deadline: `CLOSEOUT_CI_WAIT_S` (30 minutes) from now, never later
than `review-at:` minus `CLOSEOUT_MERGE_MARGIN_S` (5 minutes). That session is the independent leg: it runs the `Witness:`
itself on the PR head and records that head, reviews the diff adversarially,
checks the `decision-taken` label and Heart, then waits in-turn for CI
(`pyauto-brain ci-verdict <pr> --until <deadline>`, repeated while PENDING),
checks the head did not move, takes its slot (its output must say `taken: `)
and runs the `/prm` close-out, its merge pinned with `--match-head-commit` —
or refuses. It runs no full affected smoke (ruling S2); the cloud sweep runs
after the merge. A merge marks the PR merged; a `glance` one also bumps `glance_auto_merges`
and queues a `table-append` op that lands one row in
`autonomy_log.md` "Unattended `glance` sub-window (stage 2)" through the one Mind
writer. Every refusal is final for the shift and named in the digest
(`awaiting /prm — close-out refused: <why>`). Same-model close-out: AUTONOMY
"Stage-2 adversary amendment — 2026-11-04".

**Merge order and the branch update (M3.6j, PyAutoBrain#683).** Before CI is
read, a library PR waits behind every earlier PR this shift knows on the same
GitHub repo (its outcomes and a carried outcome's `behind`; library repos only,
ruling f) until GitHub says that PR is MERGED or CLOSED, whatever this shift
made of it (ruling c); an unreadable one blocks. Waiting is not a refusal: no
close-out, no merge slot, an entry in `counters["merge_waits"]` (rebuilt each
tick, one `gh pr view` per blocking PR per tick, ruling b) and a `waiting`
event when what it waits behind changes. A workspace PR waits while its own
task's library PR waits or is being closed out. Once nothing is ahead, a PR
whose branch was cut before an earlier PR merged (merged after its task's first
worker started; for a carried PR, any merged earlier PR) gets a branch update
only when the two PRs' changed files overlap, a file list cannot be read, or
GitHub reports this PR `CONFLICTING` (ruling S6, M3.7b). The watcher reads
each PR's files once a shift (`gh pr view --json files`, kept in
`counters["pr_files"]`; an unreadable list is kept as unreadable, counts as
an overlap and is not read again) and `mergeable` from its usual `gh pr view`. A
disjoint earlier PR is not updated for: the close-out's step 4b names it
`merged ahead, disjoint files, not updated (S6)` and does not compare it. A
PR that needs the update has the watcher take its merge slot and gets one
**branch-update session** (`closeout_update_template.md`, `claude
--bg --name shift-update:<task>`), after the public-name gate: it runs `gh pr
update-branch` (a merge commit from `main`; never a rebase or force-push,
ruling a), writes `updated` (new head), `current` or `refused` (`conflicts with
main after <A> merged → your /prm`) and ends. An `updated` or `current` PR
keeps its slot and is looked at again each tick: NO-CHECKS within
`UPDATE_CHECKS_GRACE_S` (600 s) waits; red refuses (`CI <verdict> on the
updated head → your /prm`) and frees the slot; running or green on the head
the update made starts the merge close-out (S5), which waits in-turn for CI
and whose step 4b checks every earlier PR is no longer OPEN and each merged
one it was updated for is in the branch. A PR needing a third update refuses (`main kept
moving`, `UPDATE_LIMIT` 2). A waiting or updated PR at `review-at:` is not
refused; the next shift carries it with what it waited behind. The digest says
`waits behind <A> (<A's state>) — merge <A> first` and lists a per-library
"Merge order" block, ▶ on the PR that needs your /prm now. Shift workers no
longer merge in-turn (2026-11-19, ruling "ii"); as a backstop `merge-slot take`
(`bin/merge_slot.py`) still refuses an in-turn merge while an earlier shift PR
on the same library is open (`in_turn_merge_blockers`, the close-out's rule). An `updated` PR's CI is read only
once GitHub shows the head the update made; a head that moved since refuses.
The spawn loop also refuses a task whose library a live, parked or
re-dispatch-pending task holds, whatever the plan's order made of it; a park
holds only for its 15 minutes, and a lease park until its session is stopped.

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

**Carry-over and in-shift restart (M3.6c, PyAutoBrain#669).** A shift's first
tick takes the newest earlier slot's late `glance`/`notify` PRs (never closed
out, or refused only for going green too near `review-at:`) into its own
close-out path under its own grant, and the digest names them ("Carried over
from …"). A carried PR the human merged between the shifts is settled: no
close-out, no entry, no proof packet, one line ("… PR(s) you had already
merged — nothing to do"), and it drops out of the merge order with any earlier
PR GitHub reads MERGED or CLOSED (2026-11-22). A task this shift parked on a question restarts this shift when the
inbox answers it with more than 30 minutes left (once per answer; a release
waits for its spawn, else the park stays for the next shift); the writer's
fetch repeats for that only while such a park is open, at most every 10 minutes.
A task an answer released is admitted whatever the brief's backlog scope.

**Late arrivals (PyAutoBrain#594).** A worker may finish after `review-at:`,
once the digest is posted. A closed shift with a lease still held, a close-out
still running or a ledger op still queued runs `late_sweep` on each tick: it
reaps workers and close-outs as a live tick does (a late close-out merge is
counted, its stage-2 row written and named as a late line, #632),
commits the queued ops through the one Mind writer, and appends one
`- late: <task> — <url> (after review-at, <time>)` line per arrival to the record
under `### Late arrivals`, amends the pilot line in place (`amended: true`) and
posts **one** correction comment for the shift (#610). It never spawns,
re-dispatches or starts a close-out, because the grant ended at `review-at:` and
what arrives late waits for `/prm` — or for the next shift's first tick, which
carries a late `glance`/`notify` PR over (M3.6c). It also runs while a failed digest or
correction post is due its retry.

**A blocked worker reaches the human through the questions inbox (M3.5,
PyAutoBrain#645).** A parked worker (`blocked` past the grace) or a `.done`
issue not marked `verdict:` (`question:`, bare or any other marker) @-mentions
nobody: the per-worker @mention of PyAutoBrain#611 was removed. The human's
login (`PYAUTO_SHIFT_MENTION`, else `config/policy.yaml` `shift_watcher:
mention_login:`) now only names whose comments steer the shift. The reap queues one `question-add` op per issue
(`land_question`): the task's prompt, the issue, `kind: question` (or
`blocked`, filed on the shift issue), the ask and options from the worker's
`{task}.question.json` sidecar (sanitised; `see the question on the issue`
without one; it sits in `leases/` and is never read as a lease — until
2026-11-22 each one held a worker slot to `review-at:`), the shift, the time and the worker. The one Mind writer lands
it in PyAutoMind `questions.md` through Mind's own `questions_edit.add_text`.
The digest gets one line under its heading (`Inbox: N questions added to your
inbox this shift (Q17, Q18), M open in all — <dashboard #inbox>`), and the
status comment a `- inbox:` count. Before planning, `_questions.read_origin`
reads `questions.md` from Mind origin/main (after the one fetch) and
`parked_elsewhere(slot, inbox, resumes)` rules on each earlier park: all its
entries answered → released and resumed at its old standing; one dropped →
shelved; one open or deferred → `waiting on Q<n> in your inbox`; none, or an
unreadable inbox → held as before. A released task a shift worker already
claimed (`- session: shift worker …`) is graded from `active/<task>.md` on
origin (`resume_records`), kept by `on_origin(…, resumes=)` (its own claim
does not hold its repos) and spawned with `RESUME_NOTE`; its pick's `why:`
starts `resumed after Q<n> was answered`. The human answers in a `/questions`
chat (`skills/questions`).

**The readiness pass (M3.3, PyAutoBrain#671, `_ready.py`).** `batch ready`
resolves each `queue.md` entry to its next unit(s) (an epic ledger to its open
members at the lowest phase, in `draft/` and `active/`), checks the gates
(`looks-shipped` and `obsolete` first, then `claimed`, `unattended`,
`human-required`, `blocked-by`, `no-lane`; an epic with no open member is
`no-next-phase`) and files each as an inbox entry of kind `ruling` (a `gate:`,
no `issue:`), skipping a task and gate already ruled on Mind origin/main in
any state (once answered or dropped it stays quiet; `/questions` reopen asks
again — the human's ruling, 2026-11-18) and filing none while Mind main has
no `ruling` kind. Dry run by default;
`--queue <slot>` queues `question-add` ops, `--apply` writes a session-branch
checkout (never main). `finish_shift` runs it offline before the digest, whose
last line is "The next shift needs N rulings from you." Rulings never hold or
release a parked task, and the inbox line leaves them out.

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
shown `dropped, still running` until the human stops it, by hand or by `/kill`)
and `/stop` (writes `STOP`; that tick commits nothing to Mind). PyAutoBrain#644
adds three, making seven: `/cap merges|workers|sessions|tokens <n>` (lowers a
cap for this shift, or raises it back, never above the brief's own value;
`_brief.effective` applies it from that tick), `/add <prompt>` (one Mind fetch
per command; the draft on origin/main becomes a named task, refused within 30
min of `review-at:`; it overrides `exclude:` and an earlier shift's parked hold,
never the organ rule) and `/kill <task>` (the watcher runs a local `claude stop`
on that task's running worker; the reap marks the exit `killed`, not crashed,
and it is re-dispatched once unless dropped first). M3.7e adds `/clear-sweep`, making
eight: it clears the red sweep block for the latest red run id only
(`<home>/sweep/cleared.json`, kept for later shifts). Each comment acts once, by id, and is acknowledged
once in the status comment's `Commands` list. Without a login, nothing is read
and the comment says steering is off. The dashboard's copy is the record's `-
live:` line (`record-key` op, one Mind writer, on a change of state), shown in
the batch box. Doctrine: AUTONOMY.md watcher network surface, amendment
2026-11-13.

**The event stream (PyAutoBrain#644).** Every tick that does work appends what
it did to `<slot>/events.jsonl` (`_events.record_tick`, inside the tick lock,
local only), one plain line per event, deduplicated by key in the file itself;
`batch watch --stream` prints it until `shift-end`. A needs-you event (an
`ignored:`/`refused:` ack, commands unread three ticks running, the watcher
unable to post or write Mind, a dropped task's PR merged anyway) is also one
short comment on the brief's `issue:`, no `@`, marker `mentions/event.<seq>`,
at most 5 + 1 a shift, counted as `event_comments` apart from `pushes`.
Doctrine: AUTONOMY.md watcher network surface, amendment 2026-11-16 (#644).

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
also means the watcher's comments come from another account, so they
notify the human. `_app_token.py` signs an RS256 JWT (`iat` now − 60 s, `exp` now
+ 9 min, `iss` the App id; PyJWT, else `openssl dgst -sha256 -sign` with no
shell) and mints an installation token with one `POST
/app/installations/<id>/access_tokens` on the first watcher GitHub call of a
tick, reusing it for the rest of that tick. The token is held **in memory
only** — never written to disk, where a worker running as the same user could
read it; each tick that makes a watcher GitHub call mints its own. The token is
passed as `GH_TOKEN` to the watcher's own `gh` calls and to nothing else:
**every watcher write** (the status comment and its edits, event comments, the digest,
the correction) and the steering read of the shift issue's comments. Two
**reads** deliberately stay under the human's own `gh` auth, because the App
cannot see library repositories: `gh pr view` for the PRs its workers named
(`gh_pr_state`, the close-out's merge truth and the digest's `merges`) and
`gh pr checks` for their CI (`_digest.pr_health`). If minting fails, the tick
carries on but makes none of the App's calls — no write and no steering read,
never under the human's `gh` auth in their place. The reason goes into
`tick.log` (`github_auth`) and the digest ("GitHub writes held"); a held post
costs no try and is retried. A failed mint is not retried for 10 minutes; the
state directory keeps only its time and reason (`app_mint_failure.json`), no
secret. An App
configured in part (one or two variables) is the same failure. Without the
App, `PYAUTO_SHIFT_GH_TOKEN` (a static fine-grained token, PyAutoMind
issues:write only) is the fallback; with neither, comments post as the human's
account. Neither the App variables, the key path, the static token nor a
minted token reaches a worker or close-out (`worker_env`). When the status comment is adopted, the posting account is named — as the
App, `<slug>[bot]` from one `GET /app` with the JWT (`gh api user` does not
answer for an installation token), else `gh api user`. With nothing pending, the tick is
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
write `~/.config/pyauto/orchestrator.env` with `PYAUTO_BRAIN`, `PYAUTO_MIND`
(and `PYAUTO_ORCHESTRATOR_FAKE=1` until 3b; `PYAUTO_SHIFT_BRIEF` only as an
override, see "Which brief"), then
`systemctl --user daemon-reload && systemctl --user enable --now
pyauto-orchestrator.timer`. The service carries `KillMode=process`: under the
default (`control-group`) systemd killed every process a tick started when the
tick exited, including the `claude --bg` daemon the first worker launched, so
live shift 1 (2026-11-06) lost all three workers about 30 seconds after spawn
(PyAutoBrain#592). A copy installed before then must be copied again
(`daemon-reload`). Since PyAutoBrain#634 every worker and close-out is
launched through `systemd-run --user --scope` when the tick runs inside a
unit (`INVOCATION_ID` set) and `systemd-run` is on PATH
(`_orchestrator.scope_command`): the transient `claude daemon run` and its
`bg-pty-host` spares then live in their own `app.slice/run-*.scope`, not in
the unit's cgroup, so systemd no longer logs "Found left-over process" on
every tick (211 lines in the 2026-11-14-pm shift). The daemon still quits
on its own 5 s after its last client; nothing in the watcher stops it.
Outside a unit, without `systemd-run`, or when systemd-run cannot reach the
user bus, the session is launched plain, as before. Separately, a worker or close-out whose `claude agents`
state is in `_digest.ENDED_STATES` (`failed`, `killed`, `error`, …) is reaped
at once, as a crash (worker, re-dispatched once) or a refusal (close-out),
never read as alive. To stop a shift, `touch <slot>/STOP` (or comment `/stop` on
its issue); to remove the
watcher, `systemctl --user disable --now pyauto-orchestrator.timer`.

## Codex execution workers

A brief may explicitly select `worker-backend: codex`; omitted means Claude.
The adapter changes execution, observations, stop and accounting only, retaining
this conductor's scheduling and autonomy contracts. Codex workers use an
accounted fresh Opus session for the required pre-ship review; close-outs remain
Opus. The canonical keys live in Mind `batches/AGENTS.md`. Read
[Codex setup and first-run checks](../../../docs/codex_orchestrator.md) before
the first Codex shift. No live shift is authorized by selecting a backend.

## Running

```
pyauto-brain batch plan                      # the BatchDecision for this lane
pyauto-brain batch plan --budget 45          # review-minutes available
pyauto-brain batch plan --awaiting-review 6  # backpressure input
pyauto-brain batch plan --json

pyauto-brain batch watch --record <brief>         # live view of a running shift; read-only
pyauto-brain batch watch --record <brief> --once  # one snapshot
```

`plan` is stdlib-only, offline and writes nothing.

Exit codes: **0** ok · **1** findings · **2** usage · **4** no Mind.

**The one leg you must not skip.** A batch launch requires the independent
adversary (`AUTONOMY.md` leg 5). Run it before reading a PR:

```
pyauto-brain review --task <name> --witness "<the prompt's Witness:>" --adversary
```

in a session **that did not write the branch — by default a fresh Opus
session or sub-agent, even when your own chat is on Fable**; a more expensive
model reads only when the human asks (`AUTONOMY.md` "Adversary model default —
2026-11-22"). A self-run adversary leg is an absent leg, not a weak one. The
shift worker does not run this pass (`AUTONOMY.md` "Shift speed — 2026-11-19",
ruling S3): your read, or the close-out session for an unattended merge, is
the adversary.

The manual batch flow this conductor began with (a hand-dispatched batch
record, then `batch collect` scoring it into a review packet, with an optional
`integration/<slot>` preview) was retired in favour of the watcher above: a
shift is now a brief, and its digest is the report.

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
