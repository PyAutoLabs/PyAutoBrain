# Start Bundle: Run Several Independent Tasks in One Session

A **bundle** is a set of *independent* PyAutoMind prompts worked in one
orchestrated session. The session model is the **architect**: it plans and
judges, and delegates the implementation of each member to a subagent one rung
down the capability ladder (see [`WORKFLOW.md`](../WORKFLOW.md) — Fable > Opus >
Sonnet; a Fable session delegates to Opus). Bundles come from the PyAutoMind
dashboard's **Bundles** section — pinned entries in `PyAutoMind/bundles.md`, or
proposals it computes from the backlog — or from a human naming several prompts.

**A bundle is not an epic.** An epic is ordered and phase-gated: one phase at a
time, through its ledger. A bundle has no order at all. If the members turn out
to depend on each other, it is not a bundle — say so, work the first one, and
file the rest as an epic or as ordinary backlog.

**What a bundle does NOT change:** one prompt = one task = one issue = one PR.
The bundle is an orchestration convenience, never a batching of the record.

## Steps

### 1. Read every member first

Read each member prompt in full *before* planning any of them. Confirm they are
independent (no member's plan needs another's merge) and that they belong to the
repos the bundle claims. Drop anything that is blocked, `Autonomy:
human-required`, or `Difficulty: too-large` — those are worked alone. Report the
membership you are actually taking on, and what you dropped and why.

### 2. One `/start_dev` per member — never a bulk issue queue

Run `/start_dev <member prompt path>` for **each** member: each gets its own
plan, its own GitHub issue and its own `PyAutoMind/active.md` entry. This is the
no-bulk-issue-series rule, unchanged — a bundle files the same issues a human
would have filed one at a time, in one sitting. Never merge members into one
issue, and never open issues for members you have not planned.

### 3. One shared worktree per repo

Create the worktree **once** for the whole bundle, not once per member:

```bash
source PyAutoBrain/bin/worktree.sh
worktree_create <bundle-slug> <repo1> [repo2 ...]
```

listing every repo any member touches, then follow `/start_library` (or
`/start_workspace` for workspace/tutorial members) for the registration and
activation steps. Register the claim in `active.md` under each member's task
entry, naming the shared `worktree:` path.

A git worktree holds **one branch at a time**, so inside one repo the members
are worked **one at a time**, each on its own `feature/<member-task>` branch cut
from `origin/main` — never all of them on one branch, which would collapse the
bundle into a single PR. Members whose repos do not overlap have separate
worktrees and may run in parallel.

### 4. Delegate each member to a subagent

One subagent per member (`Agent(model="opus", …)` from a Fable session; the
execution tier of [`WORKFLOW.md`](../WORKFLOW.md) otherwise), passing the
subagent prompt contract from that file: the worktree path, the repo list, the
branch to work on, the member's issue plan, and the instruction to stop and
report verbatim on failure rather than editing tests to pass. The architect
session keeps planning, judgment, registry updates and everything user-facing.

Run subagents in parallel **only** where their branches are in different
worktrees. Within one repo, sequence them: implement → ship → cut the next
branch.

### 5. Ship each member on its own

`/ship_library` or `/ship_workspace` per member — **one PR per task**, so
`/prm` closes each member out with no bundle-specific handling anywhere. Library
members ship before the workspace members that depend on them (the library-first
gate is unchanged).

### 6. Close out

`/prm` per member, as usual. Then, if the bundle was **pinned** in
`PyAutoMind/bundles.md`, update or remove its entry (its `status:`, or the whole
entry once every member has shipped) and regenerate the dashboard
(`pyauto-brain intake --apply dashboard`). Auto bundles need no cleanup — they
are recomputed from the backlog on every render and disappear on their own.

## Notes

- A member that turns out to be much larger than its `Difficulty:` said is
  removed from the bundle and finished on its own — never rushed to keep the
  session tidy.
- Bundle membership never rewrites prompt files. `Bundle: <slug>` in a prompt
  header is written by a **human**; the dashboard's proposals stay on the page.
- Report per member at the end: issue, branch, PR, test pass/fail counts, and
  anything left open.
