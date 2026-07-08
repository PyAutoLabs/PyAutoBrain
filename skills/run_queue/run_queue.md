# Run Queue: the Generic Autonomous Task Loop

Work through a queue of **PyAutoMind prompts** unattended, running each through
the standard dev lifecycle (`start_dev → start_library/start_workspace →
ship_*`) at that task's **effective autonomy level**, checkpointing questions,
auto-advancing, and ending with one batch report. This is the generic loop
extracted from `register_and_iterate` (the pytree instance, which now delegates
here); the autonomy semantics are the contract's —
[`../../AUTONOMY.md`](../../AUTONOMY.md) — never restated.

**Tier note (settled):** a *skill*, not a conductor — the consult DAG forbids a
conductor consulting conductors, and the loop drives the same lifecycle a human
would, task by task.

## Usage

```
/run_queue <prompt1>[,<prompt2>,...]     # explicit list (paths relative to PyAutoMind/)
/run_queue --queue [<file>]              # read a queue file (default PyAutoMind/queue.md)
```

Launching the runner **is** the batch's explicit `--auto` activation (the
contract's activation rule — per invocation, never ambient). If Heart is
YELLOW at launch, present the exact reason list; the human's acknowledgement
binds to that set for this run only and is recorded per task (`heart-ack:` in
`active.md`).

## Queue conventions

- Entries are processed **in order**; a line is one prompt path.
- Done entries are prepended `# DONE <date>` — never deleted (order history).
- Parked entries are prepended `# PARKED <date> <issue-or-comment-url>` and
  the loop moves on; a later run (or the human) unparks by removing the marker
  after the question is answered.

## The loop (per entry)

1. **Resolve + level** — read the prompt; effective level = min(`Autonomy:`
   header, work-type cap). `human-required` → mark `# PARKED (human-required)`
   with a note and continue; it is never run unattended.
2. **Conflict guard** — `worktree_check_conflict <task> <repos>`; on conflict,
   park the entry (holding task noted) and continue. Tasks run **serially**;
   parallel only when repo claims are provably disjoint.
3. **Run the lifecycle** — `start_dev <prompt> --auto` and follow the standard
   skills end-to-end:
   - `safe` → through the four-leg autonomous-ship gate to **PR-open**.
   - `supervised` → same, but judgment gates follow checkpoint-and-continue
     (question to the issue, `awaiting-input`, advance).
   - A failed gate leg parks the task per the contract — never "fix forward".
4. **Record** — mark the queue line (`DONE` / `PARKED`), append the
   calibration row, push Mind. One task per session-scale unit of work: the
   loop is a sequence of sessions' worth of work, not one monster context.
5. **Advance** — next entry. A hard blocker in one task never aborts the
   queue; it parks that task.

## The batch report (end of run)

One summary, posted where the run was launched (and to a pinned issue if the
run was scheduled): per task — outcome (`PR-open <url>` / `parked <question
url>` / `skipped (human-required)` / `blocked`), gate-leg results, calibration
rows appended, plus anything RED (which stops the whole run immediately —
never park-and-continue past RED).

## Instances

- **`register_and_iterate`** — the pytree PoC instance: adds the scaffold
  pattern, offending-type classification and its domain judgment gates on top
  of this loop. New task-type-specific queues follow the same shape: a thin
  skill that adds domain gates + scaffolds, and delegates the loop here.

## Hard rules

- Everything the contract forbids stays forbidden mid-queue: merge/close are
  human, runs end at PR-open, Heart RED stops the run, never modify code to
  make a gate pass, never rewrite history.
- The runner never edits the queue beyond the `DONE`/`PARKED` markers and
  never reorders entries.
