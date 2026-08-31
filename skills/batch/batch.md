# Batch — the slot door

The front door for the batch workflow: **what runs unattended, and what came
back**. Drive it from a chat; nothing here needs a terminal.

Read [`../../agents/conductors/batch/AGENTS.md`](../../agents/conductors/batch/AGENTS.md)
before acting — it holds the constraints, why each exists, and the full slot
procedure. This page is how to *converse* with it.

## The three things a human says

**1. "What should I run?"** — `/batch`, or any ask for the next batch.

Run `bin/pyauto-brain batch plan` and return the **BatchDecision as written**.
Do not re-rank it. Do not quietly add a member it rejected. Two parts must
survive into your reply because they are the point of the whole surface:

- the **review-minute total** — the budget is the human's hour, not a task count;
- the **other lane's ready count**, when this session cannot plan it: *"4
  local-dev tasks are ready — run this from the laptop."*

An empty batch at the backpressure cap is a **finding, not a deadlock**: nothing
in the backlog costs zero review-minutes. Say which it is.

**2. "Here are the ones I want."** — a paste of paths from the Mind dashboard,
or a description ("something on the numba path", "the next euclid slice").

Resolve what they gave you to prompt paths, then run the planner's constraints
over exactly that set — do not silently substitute your own picks. Report, per
task they named:

- **taken** — with its tier and review-minutes;
- **rejected, and why** — in the planner's own words. The reasons that come up
  most: `autonomy supervised — would park at ship` (it will stop at the ship
  checkpoint and come back as a question, which is the failure this workflow
  exists to remove), `Status: says the work is already done`, `epic <slug> phase
  N is not next`, `<repo> already claimed this shift`, `would exceed the budget`.

If everything they named is rejected, **say so plainly and offer the planner's
own proposal instead** — never hand back a batch they did not ask for as though
it were what they wanted.

The human may overrule any rejection except two: a `Blocked-by:` that is still
open, and `Unattended: never`. Those are not preferences.

**3. "Go."** — the dispatch. This is the launch, and it is the human's act
(`AUTONOMY.md`, "What a batch launch is"): membership fixed at approval, the
grant expiring with the shift — the interval from dispatch to the `review-at:`
they declare here. Never dispatch on your own initiative, on a schedule, or
because a batch looks ready.

In order:

1. Consult vitals (`bin/pyauto-brain vitals`). If Heart is YELLOW, **ask the
   human to acknowledge the reason set for this shift** and record it verbatim.
   You may not acknowledge it for them, and a set carried from an earlier batch
   is void.
2. Write `PyAutoMind/batches/<YYYY-MM-DD>-<am|pm>.md` from the schema in that
   folder's `AGENTS.md` — members, planned review-minutes, the reason set and
   **`review-at:`** — **before** any session starts. That file is what makes the
   launch auditable. `review-at:` is when the human expects to be back, and it
   is where the grant expires; **if they did not say, ask before dispatching.**
   It is the one thing only they know — never infer it from a schedule, a
   previous batch, or the time of day, and do not dispatch without it.
3. Start one session per member, each carrying exactly
   `/start_dev <path> --auto`. Spawn them if this harness can; otherwise hand
   the human the lines to paste. **One session per member, never shared**: a
   shared session serialises them and carries one member's context into the
   next.
4. Confirm what was dispatched, and stop. Do not follow the runs.

## When they come back

Read the PRs. Order: **failures first, then anything labelled `decision-taken`,
then clean.** For each, offer three things and do the one they pick:

- **merge** — `/prm <PR>`;
- **tweak** — they say one line; *you* draft the follow-up prompt and put it at
  the top of `queue.md`. They should never have to write a prompt file.
- **reject** — route it to `condemned.md`.

Then append the outcome to the batch record: `reviewed-at:` (when they actually
sat down — the calibration of their own `review-at:` estimate), `delivered:`
(see below) and **`review-minutes-actual:`**. That last number is the only
calibration the review estimate will ever get, so ask for it if the human does
not volunteer it.

**Before reading any PR from a batch, the independent adversary leg must have
run** (`AUTONOMY.md` leg 5): `bin/pyauto-brain review --task <name> --witness
"<the prompt's Witness:>" --adversary`, **in a session using a different model
from the one that wrote the branch**. A self-run adversary leg is an absent leg,
not a weak one, and recording it as run is a false ledger row. If it has not
run, say so rather than reviewing as though it had.

**`delivered:` is not "green".** A cloud session's green status means it exited
without an infrastructure error — not that the task succeeded. A member counts
as delivered only with a PR that has a non-empty diff and checks that ran. A
member that ended green with no PR is reported **not delivered**, loudly, at the
top.

## Never

- Dispatch without an explicit go from the human in this conversation.
- Acknowledge a Heart YELLOW or RED on their behalf, or reuse a previous
  shift's reason set.
- Add a member the planner rejected without saying which rejection you are
  overruling and why.
- Present the proposal as a schedule. The schedule may carry the timing; it
  never carries the authority.
- Dispatch without a `review-at:` in the batch record, or invent one for them.
