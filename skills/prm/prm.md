# /prm — PR, CI green, then merge

The last thing you type for a task: judge the feature PR's checks, merge when
they are genuinely green, then close the task out — issue closed, prompt moved
`active/` → `complete/`, `dashboard.md` regenerated, worktree and local
branches removed — and hand back a ledger.

Each step has a matching section in [`reference.md`](reference.md) (the
close-out's sub-steps are its §1-7); read it when you run the step, and the
close-out only after merging. `/prm` sequences owners it never second-guesses
([`SKILL.md`](SKILL.md)): it never re-runs the readiness gate, edits code to
make a check pass, opens a PR (that is `/ship_*`) or hand-writes a generated
page. Routing: `PyAutoBrain/skills/COMMANDS.md`.

## Usage

```
/prm                      # the PR for the current branch / current task
/prm 380                  # PR #380 in the current or inferred repo
/prm PyAutoArray#42       # or Jammy2211/PyAutoArray#42, or the full PR URL
/prm --no-wait            # judge CI once and report; merge only if already green
/prm --thaw "<why>"       # merge a LIBRARY PR through an active Heart freeze (logged)
```

## Environment: decide your GitHub surface first

Probe once and remember the answer:

```bash
command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1 \
    && echo "gh" || echo "mcp"
```

- **`gh`** (local CLI) — `$PYAUTO_ROOT` (`bin/_pyauto_root.sh`) holds the
  sibling repos; branch detection and worktree cleanup are available.
- **`mcp`** — GitHub is the `mcp__github__*` surface, mapped in
  [`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md): read [mcp.md](mcp.md) for the
  exact calls (not the local recipes), skip the local-only cleanup with a
  one-line note, never `cd` into a repo that isn't there, and never report the
  close-out blocked for want of `gh`. `/prm` deletes no remote branch on any
  surface (step 5.6).

## Tiered merge — the shipping session runs this procedure

Since 2026-10-02 `ship_*` hands a declared-`notify` or witnessed-`glance` task
here after PR-open, authorized by its approved plan or launch (`AUTONOMY.md`
"Merge authority follows Consequence"). Run from step 2, with the bounded wait,
extra refusals and bare merge call in [`reference.md`](reference.md) → "Tiered
merge".

## 1. Resolve the target PR(s)

Explicit argument → current branch (`gh pr view --json`) → the claimed task's
`library-pr:` / `workspace-pr:` in `PyAutoMind/active.md` → `gh pr list` across
the claimed repos. More than one candidate → **list them numbered and ask
once**; never guess. Report each as `owner/repo#N — title — branch`. A task with
a library and a workspace PR is **one** run over both, in gate order (step 4).

## 2. Judge CI honestly — every run, every leg

A head sha triggers **two** runs per workflow (`push` and `pull_request`), each
with matrix legs: enumerate every run for the sha and every job; anything not
`completed` is *not ready*, and an empty run list is not green. Read
`mergeable` / `mergeStateStatus`: `UNSTABLE` is pending-or-red, and
`CONFLICTING` / `BEHIND` / `BLOCKED` stops the run whatever the checks say. A
test leg `skipped` is **not green** — name it; a tiered merge stops on it.

## 3. Wait, or stop

- **Pending** — wait only by a mechanism that ends with this turn. Under
  `--no-wait`, judge once, report and stop.
  - **Stop (mobile, web — required there).** Report each PR's state (per-leg
    counts, `2/4 legs done`, red or pending named), **end the turn** and tell
    the human to re-run `/prm` once CI is green. Never `subscribe_pr_activity`,
    never `send_later`, never a routine, cron or wake-up: **sessions end at
    their deliverable** (`PyAutoMind/policy/end_at_deliverable.md`; the
    incidents are in [`reference.md`](reference.md) → "Why the wait ends with
    the turn"). Waiting for CI is the human's next `/prm`.
  - **Poll (local CLI).** Every ~90s, one compact line per poll, capped at ~30
    min so it finishes **inside this turn**; at the cap, stop and hand back.
    (A tiered merge's ~60-min watch is the one other in-turn wait.)
- **Red** — **fetch the failing job's log immediately** (GitHub purges it),
  quote the failing step, and stop: no merge, no re-run, no waiting for the
  flake. Offer `/bug`, or a named re-run if the user judges it a flake.
- **No checks configured** — say so explicitly and ask before merging.

## 4. Merge

Green on every leg → merge, in this order.

**PRs shipped under the Heart RED development override:** the shipping grant
is not merge authority. Require a separate explicit human merge command and
every required GitHub check green; never force, override protection, or treat
Heart RED as cleared. A live message may authorize both shipping and merge,
but that merge grant lasts only for the current turn: if the turn ends before
checks are green it expires — arm no waiter or auto-merge, stop, and require
the human to invoke `/prm` again. This never reaches a release or rehearsal.

1. **Library freeze gate:** for library PRs read [freeze.md](freeze.md) and
   check Heart's freeze flag; stop when frozen unless the human supplied
   `--thaw "<why>"` (record it). Never thaw past red CI.
2. **Library PR first.** A workspace PR may not merge until its upstream library
   PR is `MERGED` ([`../ship_workspace/reference.md`](../ship_workspace/reference.md));
   no `--auto`-flag workaround.
3. `gh pr merge <n> --merge` per PR (`-R owner/repo` without a checkout) — one
   bare, unchained call per PR; a denied merge stops the run — then confirm
   `MERGED` (queued or auto-merge is not merged). Never `--delete-branch`: it
   takes the local branch too, orphaning a task worktree.
4. **Clear anything an older run left armed** — a subscription or `send_later`
   reminder on a target PR (`unsubscribe_pr_activity`, cancel it). Never create
   one.

Never force, override a protection or rewrite history. A merge GitHub refuses:
report the reason verbatim and stop.

## 5. Close the task out

After every target PR is confirmed merged, **read and execute
[closeout.md](closeout.md)** in order: prove each claimed branch merged, close
the issue, `lifecycle.py close`, carry pending-release obligations, the
glance-tier shadow row, reconcile and regenerate the dashboard, then remove the
worktree and local branches. No close-out on partial evidence. A task with no
issue, prompt or worktree skips those sub-steps and says so; the dashboard
regen is skipped only when the close-out wrote nothing to Mind.

## 6. The only guards that stop you

- a branch in the task is **unmerged** with no open PR (step 5.1);
- Heart's **freeze** is active for a library PR and no `--thaw "<why>"` was given;
- `worktree_remove` **refuses** (dirty repo, stale claim) — fix the cause, never
  `PYAUTO_WT_FORCE=1`;
- the worktree holds **gitignored data products** (reduced datasets, caches,
  `output/` fits) — list them with sizes and **ask once**: delete, or keep the
  worktree and finish the rest. `/prm`'s only question.

More notes (no PR yet, Mind's own close-out, freeze vs readiness):
[`reference.md`](reference.md) → "Notes (moved from prm.md)".
