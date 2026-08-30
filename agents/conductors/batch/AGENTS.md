# Batch Agent

> **Tier: conductor** — a front-door agent a human *drives*. It *composes one
> unattended shift*: given the queue, the backlog and the review-queue state, it
> emits a **BatchDecision** — the members, what they will cost the human to
> review, and what it rejected and why. It **proposes; it never dispatches.**
> Approving the proposal in a slot is what launches a batch.

## What it is for

The organism has no throughput problem. August 2026 shipped **332 completion
records, about eleven a day**. The scarce resource is the human's judgement, and
a batch layer that plans by task count spends it faster rather than slower.

So the composition rule is a budget in **review-minutes**, not a count:

> Σ `Review-minutes:` over `glance` and `judge` members ≤ the slot's budget
> (default 45 — a slot also has to queue the next batch).

Read against the ledger, an honest hour holds about three library-touching
tasks. Planning by count over-promises capacity roughly threefold, and the
overflow lands on the human at 6am.

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

Everything rejected says so, with its reason. A planner that silently drops work
teaches the human to distrust the number it reports.

## Backpressure ramps; it never deadlocks

Counted in **tasks awaiting review**, never in PRs — 94 of 332 August records
named two or more PRs, so a PR-count cap trips on a single healthy batch.

- clear → the full budget;
- above half the cap → the review-bearing half is **halved** (the fill is not:
  it does not touch the queue);
- at the cap → the batch is the **floor**: fill only, dispatched whether or not
  the human turned up.

A missed slot is the common case for an academic, not an exception, and a
conference week must not stop the thing whose whole purpose is working while
nobody watches. An **empty floor is a finding, not a deadlock** — it means
nothing in the backlog costs zero review-minutes, which is exactly what the
`notify` tier and the `Witness:` field exist to change, and the decision says so
in those words.

## Lane detection

`local-dev` or `web-github`, probed from the environment rather than declared,
and from the signal the organism already uses: a remote session has no `gh`
(measured; `skills/GITHUB_ACCESS.md`). No flag and no environment variable
decides it — a session that could lie about where it is could plan `local-dev`
work it cannot run. A session reports the other lane's ready count rather than
hiding it: *"4 local-dev task(s) are ready — run `batch plan` from the laptop."*

## It proposes; the human launches

`AUTONOMY.md` ("What a batch launch is") defines a batch dispatch as **one
launch**: membership fixed at approval, the grant expiring with the shift, the
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
```

Stdlib-only, offline, writes nothing.

## Running a batch by hand (there is no dispatcher yet, and that is fine)

Phase 5 — automatic fan-out — is deliberately unbuilt. Everything below works
today, costs about two minutes of tapping, and is the honest way to find out
what a dispatcher actually needs before writing one.

**In the slot (about an hour, once a day):**

1. `pyauto-brain batch plan` — read the BatchDecision. Edit it by removing
   members you do not want; do not add ones it rejected without reading why.
2. **Acknowledge the Heart reason set for the shift**, if Heart is YELLOW
   (`pyauto-brain vitals`). Write it verbatim into the batch record — a grant
   recorded loosely is how a scoped one becomes standing, which doctrine voids
   (`AUTONOMY.md`, "Leg 4 under a batch launch").
3. Open the batch record `PyAutoMind/batches/<YYYY-MM-DD>-<am|pm>.md` from the
   schema in that folder's `AGENTS.md`, and write the members, the planned
   review-minutes and the reason set **before** dispatching. That file is what
   makes the launch auditable afterwards.
4. **Dispatch**: paste each line the decision prints into **its own session**.
   One session per member — they must not share one, because a single session
   would serialise them and carry one member's context into the next.
5. Go and do something else.

**Next slot:**

6. Read the PRs. Failures first, then anything labelled `decision-taken`, then
   clean ones. For each: merge (`/prm <PR>`), or say one line of what you want
   changed and let a session draft the follow-up prompt into `queue.md`.
7. Append the outcome to the batch record — `delivered:`, and especially
   **`review-minutes-actual:`**. That last number is the only calibration the
   estimate will ever get, and everything the planner does rests on it.
8. Plan the next batch.

**The one leg you must not skip.** A batch launch requires the independent
adversary (`AUTONOMY.md` leg 5). Until `batch collect` exists, run it by hand
before reading a PR:

```
pyauto-brain review --task <name> --witness "<the prompt's Witness:>" --adversary
```

in a session **using a different model from the one that wrote the branch**. A
self-run adversary leg is an absent leg, not a weak one.

**What to expect from batch 1.** Small. The planner picks against a 45-minute
review budget, and with almost no prompt carrying a `Witness:` nearly everything
grades `judge` at 20 minutes — so a slot holds two or three. That number is the
honest state of the backlog rather than a limit of the machinery, and the way to
move it is to write witnesses, which costs zero review-minutes and is the best
possible fill work.

## Not built yet

`slice` (the decomposition pass doctrine has named since inception) and
`collect` (the review packet) are the conductor's other two verbs — see the
epic ledger, `PyAutoMind/draft/feature/pyautomind/two_slot_batching_epic.md`.
`plan` is useful on its own: run it in a slot and dispatch by tapping the
dashboard's existing chips.
