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
| **`Unattended: ready` only** | `needs-slicing` goes to the decomposition pass; `never` never enters a batch |
| **Lane match** | a session detects its own lane and plans only that one |
| **Backpressure** | see below |
| **One integration root per slot, and it is local** | `integration/<slot>` is cut fresh from `origin/main` on every run and never pushed, so a re-run is a re-preview rather than a rewrite; a dirty integration worktree is skipped, never reset. The one-member-per-library-repo rule above is what keeps within-repo conflicts rare — the common case is one member with organ PRs across five repos. |
| **Publishing that root is a separate act, typed by the human** | `--push` is the only remote write the batch makes, and no record can ask for it — `- integration: yes` requests the *local* preview. What it writes is a throwaway `integration/*` review ref and nothing else: never a pull request, never a base for one, never forced. A refresh that is not a fast-forward publishes `-2` rather than moving what is already there, and the ref expires at the record's `sweep-after:`. |

Everything rejected says so, with its reason. A planner that silently drops work
teaches the human to distrust the number it reports.

## Backpressure ramps; it never deadlocks

Counted in **tasks awaiting review**, never in PRs — 94 of 332 August records
named two or more PRs, so a PR-count cap trips on a single healthy batch.

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
hiding it: *"4 local-dev task(s) are ready — run `batch plan` from the laptop."*

## It proposes; the human launches

`AUTONOMY.md` ("What a batch launch is") defines a batch dispatch as **one
launch**: membership fixed at approval, the grant expiring with the shift — the
interval from dispatch to the `review-at:` the human states at dispatch — the
terms written into `PyAutoMind/batches/<date>-<am|pm>.md`, and the human
performing the dispatch. A scheduler may build the review packet and wake a
session; the act that starts work on the approved list is the human's. That is
the line that keeps "never ambient" true — the schedule carries the *timing*,
never the *authority*.

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

pyauto-brain batch plan --kind cortex [--cortex DIR] [--cortex-budget N]
pyauto-brain batch plan --kind cortex --apply --review-at <ISO> \
      [--slot <YYYY-MM-DD-label>] [--shift <label>] [--stamp <ISO>]  # writes the record
pyauto-brain batch collect --kind cortex [--pull] [--apply] [--review-at <ISO>]
```

`--kind dev | cortex | both` picks the member kind, and its default is the
**lane's**: `local-dev` offers `both`, a cloud session `dev` only — with the
Cortex ready count reported rather than hidden, as the lane rule says. `--cortex
DIR` names the checkout when it is not where `_cortex.resolve_root` finds it;
`--cortex-budget N` is the science slot's own review-minute budget (default
`--budget`). `plan --kind cortex --apply` is the only form that opens a Cortex
record, and it **refuses without `--review-at`**: the shift is dispatch →
`review-at:`, and that horizon is the human's to declare, never inferred.
`collect --kind cortex` scores the record's members and refreshes the packet;
`--pull` runs each project's own sync CLI first (laptop only), and `--review-at`
re-declares the record's horizon at a refresh. `--fetch` and `--evidence` are
dev-only — a science member's evidence is on disk, not on GitHub.

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
Mind (no `batches/` at all) · **5** no usable Cortex tree (`--kind cortex` with
nothing to read).

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
   members' self-armed check-ins drained usage overnight).
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
   Science members are their own batch: `hpc/sync pull` per project (or
   `collect --kind cortex --pull`), then `pyauto-brain batch collect --kind
   cortex --apply` against the Cortex record, so every pointer in the packet is
   a local path (remote-only pointers exist only where the pull cannot fetch by
   design, and say so; a mobile session cannot pull and says "run collect from
   the laptop").
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

## Two kinds, two records

`dev` reads the Mind, `cortex` reads the Cortex, and the two vocabularies are
kept apart on purpose: they are different genres of work reviewed by different
acts.

| | `dev` | `cortex` |
|---|---|---|
| a member is | a Mind prompt | a Cortex phase |
| its record | `PyAutoMind/batches/<slot>.md` | `PyAutoCortex/batches/<slot>.md` |
| its legs | pr · diff · checks · green · witness · adversary | the six science legs of `cortex collect` |
| its health words | FAILED · NOT-DELIVERED · SUSPECT · HEALTHY · PENDING · MERGED | FAILED · SUSPECT · HEALTHY · **RUNNING** |
| the human's verbs | merge · tweak · reject · defer | accept · rerun · drop · leave-to-finish |
| the review lands as | a merge and follow-up prompts | a ruling (`cortex.py rule`) |

**Admission is the phase-2 rule, not the dev one.** A cortex member is `ready`,
carries a witness, fits the budget and matches the lane. The **autonomy cap is
never consulted** — a science member is supervised by definition, the human
submits the run and rules on it — and the one-member-per-library-repo clash
applies **in neither direction**: a science run claims no library worktree, so
it can neither be blocked by a dev member nor block one.

**The Cortex packet is a rolling board.** A dev batch is dispatched at once and
reviewed at once; a science phase **joins** its board when its results are
pulled. `collect --kind cortex` may therefore run any number of times in one
slot — each pull appends the member that just landed and leaves every other
section byte-identical. Members still `submitted`/`running` render as RUNNING
with their job ids and wall-vs-budget, and **hold no review control at all**:
no chips, no ruled box, `(none)` in the submitted review. There is nothing for
the human to say about a run that has not finished.

**The first review does not close the slot, either.** A dev batch is reviewed
once — `collected:` puts the button on the packet, and `batches/reviews/
<slot>.md` existing closes it outright (see "The close leg" above). A Cortex
slot stays open across as many sittings as it takes: the human rules on
whatever is reviewable whenever they come in, and every sitting after the
first lands as its own numbered file, `batches/reviews/<slot>-r<N>.md` (N ≥
2 — `-r1` is not a name, the first sitting is `<slot>.md`;
`PyAutoCortex/batches/reviews/AGENTS.md`). `organ_for`'s `review_path` always
names the **next free** one, so the packet's submit button (and the GitHub
new-file link it builds) never points a later sitting at an earlier one's
file. The record's `- review:` key **repeats**, one line per sitting, in the
order they happened — `collect` appends whichever of a slot's review files the
record does not already carry a line for, and never touches the ones it does.

**A rolling slot closes when nothing is left in a board state.** Not "a review
exists" — a Cortex record may carry several `- review:` lines and still be
open, because a later sitting can rule on members a pull only just landed.
Closed means: every member is either **ruled** (its review row says `ruled:
yes` — `_on_the_board` drops it from the score for good, so no later sitting
re-splices it even if the underlying phase file changes afterward) or
**carried** (a `- carried: <slug> — still <state> at review` line for it is
already IN THE RECORD, written by an earlier sitting). A member that is merely
`submitted`/`running`/`pulled`/`awaiting-ruling` **right now**, with no
`- carried:` line yet, still holds the slot open — carrying happens at a
sitting, not by inference from the tree. This is the same reading
`agents/conductors/batch/_status.py`'s `cortex_status` gives the status box on
both dashboards (`_cortex_slot_open` in `_batch.py` is the collect-side
replay of it), so a slot the box shows as still in flight is a slot `collect`
also still treats as open.

**Carry-forward is the mechanism that moves them on.** At close, every member
still `submitted`/`running` gets a `- carried: <slug> — still <state> at review`
line on the record, and the next `plan --kind cortex --apply` includes those
members automatically with a `- carried-from:` naming the record they came from.
The human never re-specifies them, and **a Cortex member never blocks a Cortex
review** (`PyAutoCortex/batches/AGENTS.md`).

**A Mind record never lists a Cortex member, and a Cortex record never lists a
dev one.** Each surface holds its own `review-at:`, so one record cannot carry
two shifts — and a member reading its organ's record at leg 4 (`AUTONOMY.md`,
"How a member learns the shift's grant") would otherwise read the wrong grant.

## Not built yet

`slice` — the decomposition pass doctrine has named since inception — is the
conductor's one remaining verb; see the epic ledger,
`PyAutoMind/draft/feature/pyautomind/two_slot_batching_epic.md`. `plan` and
`collect` stand on their own in the meantime: plan a slot, dispatch by tapping
the dashboard's existing chips, collect what comes back.
