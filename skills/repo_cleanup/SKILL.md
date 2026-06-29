---
name: repo_cleanup
description: Periodic hygiene sweep across PyAuto libraries, workspaces, and worktrees. Audits for deletable feature branches (local and remote), stale tracking refs, old stashes, dirty checkouts, and worktree mismatches, then executes per-bucket cleanups after user confirmation. Use for end-of-week tidying or when branch lists have grown unwieldy.
---

# Repo Cleanup

Periodic git-hygiene sweep for the PyAuto workflow. Finds and removes the debris
that accumulates between `/start_dev` → `/ship_library` / `/ship_workspace`
cycles: feature branches left behind when post-merge cleanup was skipped, stashes
from abandoned sessions, `[gone]` remote-tracking refs, dirty canonical
checkouts, and orphan worktrees.

A **PyAutoBrain dev-workflow** hygiene skill — the between-tasks counterpart to
`start_*` / `ship_*`. Like those, it **reasons** about what to do and then runs
its own git mechanics: Heart *observes* the hygiene signal (open PRs, worktree /
dirty state — see "protection sets"), Brain *decides* what is safe to remove and
*executes* the cleanup. That is why this is a Brain skill, not a Heart one —
Heart is an observer that never mutates other repos, whereas removing
branches/stashes is dev-workflow git execution (the same kind `ship_*` does).
Cleanup is not release work, so it never touches PyAutoBuild. It reads the
PyAutoMind registry (`active.md`) to know what's claimed. Organ boundary +
execution-environment model: [`../WORKFLOW.md`](../WORKFLOW.md).

> **Future Cleanup Agent.** This skill is the inline form; the natural home for
> the reasoning is a dedicated PyAutoBrain **Cleanup Agent** (alongside the
> Feature / Build / Health agents) that generalises hygiene across the organism.
> Until it exists, run the reasoning here per this file and record the agent as a
> follow-up — the same pattern WORKFLOW.md describes for the other skills.

**Distinct from:** `worktree_status` (Heart read-only diagnostic — consulted here,
but this also mutates); post-merge cleanup in `CLAUDE.md` (once per shipped task —
this covers residue when that flow is skipped); `plan_branches` (task start — this
is between-tasks hygiene).

## Safety principles (non-negotiable)

1. **Audit first, act second.** Phase 1 is a read-only report. Nothing
   destructive runs without an explicit per-bucket confirmation.
2. **Never touch claimed work.** A branch is off-limits if it is checked out in a
   worktree under `$PYAUTO_WT_ROOT`, claimed in `PyAutoMind/active.md`, or has an
   open GitHub PR.
3. **Never `-D` / `push --delete` an unmerged branch** without per-branch
   confirmation (the user types `yes, force delete <name>`). Default deletes use
   `git branch -d`; remote deletes target only branches merged to `origin/main`.
4. **Never `stash drop` without showing the diff** (`git stash show -p`) and
   getting a keep/apply/drop decision.
5. **Never auto-resolve dirty canonical checkouts** — report and stop for that repo.
6. **Conservative on remote branches** — only propose deleting remote branches you
   have a local ref for; never enumerate origin-only (collaborator) branches.

## Scope

**Always swept:** library canonical checkouts under `$PYAUTO_MAIN` (PyAutoConf,
PyAutoFit, PyAutoArray, PyAutoGalaxy, PyAutoLens, PyAutoBuild); workspaces incl.
`_test`/`_developer` variants (autofit/autogalaxy/autolens families, HowToLens);
and worktree roots under `$PYAUTO_WT_ROOT`.

**Never touched:** `z_projects*`, `z_staging`, `bad`, `priors`,
`euclid_strong_lens_modeling_pipeline`, `autolens_assistant`, and anything not
listed above. Skip any entry that is missing, not a git repo, or a bare symlink.

## Steps

### 1. Setup

```bash
source admin_jammy/software/worktree.sh
```

Provides `worktree_list_claimed`, `worktree_root_path`, `PYAUTO_LIBS`,
`PYAUTO_MAIN`, `PYAUTO_WT_ROOT`. Confirm `gh auth status` (needed for the open-PR
cross-check); if unauthenticated, stop. If `$PYAUTO_MAIN` has no repos, fall to
the execution-environments fallback in [`reference.md`](reference.md).

### 2. Audit

Audit the canonical checkouts and the worktrees, then build the protection sets
(`CLAIMED` / `IN_WORKTREE` / `OPEN_PR`). Commands and protection rules:
[`reference.md`](reference.md) → "Audit canonical checkouts", "Audit worktrees",
"Protection sets".

### 3. Dashboard

Present the audit grouped into fixed buckets A–E plus Warnings (omit empty
buckets; always print the Summary counts). Layout: [`reference.md`](reference.md)
→ "Dashboard layout".

### 4. Per-bucket confirmation + execution

Work the buckets in the fixed order (resolve worktree Warnings first, since
branches can't be deleted while a worktree holds them), printing exact commands
and getting approval before each destructive step. Recipes:
[`reference.md`](reference.md) → "Per-bucket execution".

### 5. Recap

Print what happened and what was kept, so the next sweep resumes from there.
Format: [`reference.md`](reference.md) → "Recap".

## Notes

- Destructive commands run against canonical checkouts (`$PYAUTO_MAIN/<repo>`),
  **never** worktrees — the `ship_*` flow + post-merge cleanup handle those.
- Skip missing / non-git / detached-HEAD repos with a one-line note.
- Never skip hooks, never force-push — these are read/prune/delete operations only.
- Suggest `/worktree_status` first if unsure whether tasks are in flight.
- Execution-environment fallback (remote-audit-only when there's no local tree)
  is in [`reference.md`](reference.md).
