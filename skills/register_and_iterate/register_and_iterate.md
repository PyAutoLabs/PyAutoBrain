# Register and Iterate: Autonomous Pytree PoC Loop

Autonomously work through a queue of `fit_*_pytree_*.md` prompts: scaffold each
variant's `_pytree.py`, run it, register offending types until the
`jax.jit(analysis.fit_from)` round-trip matches NumPy, then hand off to
`/ship_library` + `/ship_workspace`. Pause only at hard judgment gates.

The **pytree instance of the generic queue loop** — the loop itself (queue
conventions, per-entry lifecycle at the task's autonomy level, `DONE`/`PARKED`
markers, batch report) is [`/run_queue`](../run_queue/run_queue.md); this skill
adds only what is pytree-specific: the scaffold pattern, the offending-type
classification heuristic, and the domain judgment gates below. Read
[`../WORKFLOW.md`](../WORKFLOW.md) for the organ boundary; the scaffold pattern,
classification heuristic, delegation block, recommended queue, and
failure/reporting detail are in
[`reference.md`](reference.md) (`PyAutoBrain/skills/register_and_iterate/reference.md`).

## Usage

```
/register_and_iterate <prompt1>[,<prompt2>,...]
/register_and_iterate --queue          # reads PyAutoMind/queue.md
```

Prompts are paths relative to `PyAutoMind/`, organised by work type
(e.g. `feature/autolens/fit_imaging_pytree_rectangular.md`). Pre-migration
`<target>/<name>.md` paths still resolve.

## Autonomy contract

This contract is the origin of, and now an instance of, the general
**checkpoint-and-continue** mechanics in
[`../../AUTONOMY.md`](../../AUTONOMY.md) — question format, `awaiting-input`
parking and resume are defined there, once. Runs without intervention
**except** at these gates, where it writes a clear question and stops:

1. **Aux/dynamic judgment** on an offending type whose classification is not
   obvious (non-Array attributes, callable state, known-gotcha class).
2. **Ship PR approval** — `/ship_library` and `/ship_workspace` always require
   user sign-off on the `## API Changes` / `## Scripts Changed` sections, and run
   their own Heart readiness gate. Never bypass.
3. **Hard blockers** — a type that cannot be registered. Stop and write up the
   blocker per the prompt's fallback clause.

Between tasks, auto-advance to the next queued prompt. Iteration, scaffolding,
testing, and post-merge cleanup run unattended.

## Per-prompt flow

### 1. Resume or start the task

Read `PyAutoMind/active.md`. If the prompt's derived task name is already active,
resume it (source the worktree's `activate.sh`, verify the feature branch,
continue). Otherwise run `/start_dev <prompt>` then `/start_library` inline
(Feature Agent classify → issue → worktree → register in `active.md`). The
derived task name is the filename stem with `_`→`-`
(`fit_imaging_pytree_rectangular` → `fit-imaging-pytree-rectangular`).

### 2. Check dependencies

Parse the prompt's `__Depends on__` section; verify each appears in
`PyAutoMind/complete.md`. If a dependency is missing, stop and tell the user
which prompt to run first. **Do not** re-order the queue automatically.

### 3. Scaffold + iterate

Scaffold `<variant>_pytree.py` and run the registration loop (max 8 iterations),
classifying and registering each offending type. Full pattern, the three-step
assertion, and the classification heuristic are in
[`reference.md`](reference.md) → "Scaffold", "Registration loop",
"Classification heuristic". In local-dev, delegate the mechanical run-and-register
cycle to an execution-tier subagent (reference.md → "Delegation").

### 4. After PASS — gate: ship approval

Run the affected repo's test suite under the worktree and re-run the script as a
smoke check (reference.md → "After PASS"), stage changes (do not commit), then
write a ship-ready summary listing the registrations added, the workspace script,
and the test result. **Wait for user confirmation** — do not auto-invoke
`/ship_library`. The ship skills handle their own Heart readiness gate, commit,
push, feature PR, merge, and post-merge cleanup.

### 5. Advance

After both PRs for the task are merged and post-merge cleanup completes, read the
queue and start the next prompt. If the queue is empty, print the final report
(reference.md → "Reporting") and stop.

## Queue mode

With `--queue`, read `PyAutoMind/queue.md` (skip blank/`#` lines, process in
order, prepend `# DONE <date> ` to a line on successful ship). If `queue.md` is
absent, write the recommended order (reference.md → "Recommended queue") and ask
the user to confirm before proceeding.

## Scope boundaries

- **Do not** modify `use_jax` dispatch, the `xp is np` guard, or any non-JAX path.
- **Do not** auto-run `/ship_library` or `/ship_workspace` — those are human gates.
- **Do not** re-order the queue; if a dependency is missing, stop and ask.
- **Do not** commit or push — the ship skills handle that.
- **Do not** delete or modify existing registrations, even if they look wrong —
  flag them.

Failure modes and end-of-queue reporting: [`reference.md`](reference.md).
