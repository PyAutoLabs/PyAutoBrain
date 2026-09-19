# /prm — PR, CI green, then merge

The last thing you type for a task: watch the feature PR's checks, merge the
moment they are genuinely green, then close the task out — issue closed, prompt
moved `active/` → `complete/`, `dashboard.md` reconciled and regenerated,
worktree and local branches removed — and hand back a ledger.

Load this procedure once. Skip the MCP lane on local CLI; on MCP skip local
command recipes. Read the close-out only after merging. Reuse unchanged
references already loaded. Each step below has a matching section in [`reference.md`](reference.md) carrying
its commands, failure signatures and reasoning (the close-out's sub-steps are its
numbered §1-7); read it when you run the step.
Routing: `PyAutoBrain/skills/COMMANDS.md`. `/prm` sequences owners it never
second-guesses ([`SKILL.md`](SKILL.md)): never re-running the readiness gate,
never editing code to make a check pass, never opening a PR (that is `/ship_*`),
never hand-writing a generated page.

## Usage

```
/prm                      # the PR for the current branch / current task
/prm 380                  # PR #380 in the current or inferred repo
/prm PyAutoArray#42       # or Jammy2211/PyAutoArray#42, or the full PR URL
/prm --no-wait            # judge CI once and report; merge only if already green
/prm --thaw "<why>"       # merge a LIBRARY PR through an active Heart freeze (logged)
```

## Environment: decide your GitHub surface first

Steps below are written as `gh` commands because that names each operation most
clearly; without `gh` they are the *operation*, not the command. Probe once, and
remember the answer — it is the only probe this run needs:

```bash
command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1 \
    && echo "gh" || echo "mcp"
```

- **`gh`** (local CLI) — `$PYAUTO_ROOT` (`bin/_pyauto_root.sh`) holds the
  sibling repos; branch detection and worktree cleanup are available.
- **`mcp`** (a session without authenticated `gh`) — when no local multi-repo
  checkout is available, GitHub is the `mcp__github__*` surface, mapped step by step in
  [`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md). Drive every step through it,
  **skip the local-only cleanup** with a one-line note, never `cd` into a repo
  that isn't there, and never report the close-out blocked for want of `gh`.
  `/prm` **deletes no remote branch on any surface** (step 5.6), so nothing here
  needs the second probe that step used to carry.

On MCP, read [mcp.md](mcp.md) for the exact calls; do not load local recipes.

## 1. Resolve the target PR(s)

In order: explicit argument → current branch (`gh pr view --json`) → the claimed
task in `PyAutoMind/active.md` (its `library-pr:` / `workspace-pr:` entries; with
no checkout read it through `gh api` or `get_file_contents`) → `gh pr list`
across the claimed repos. If more than one candidate survives, **list them
numbered and ask once** — never guess which PR to merge. Report each as
`owner/repo#N — title — branch` first. A task that shipped both a library and a
workspace PR is **one** `/prm` run over both, merged in gate order (step 4).

## 2. Judge CI honestly — every run, every leg

A head sha triggers **two** runs of each workflow (`push` and `pull_request`),
each with its own matrix legs, so one green row is not "CI green": enumerate
every run for the sha and every job in it, and treat anything not `completed` as
*not ready* — not "green so far". An empty run list is not green either. Read
`mergeable` / `mergeStateStatus` too: `UNSTABLE` is pending-or-red, and
`CONFLICTING` / `BEHIND` / `BLOCKED` stops the run whatever the checks say.

## 3. Wait, or stop

- **Pending** — wait only by a mechanism that ends with this turn. That is an
  in-turn poll on a local CLI, and nothing at all on mobile or web. Under
  `--no-wait`, do not even poll: judge once, report and stop — which on
  mobile and web is now the only behaviour the flag or its absence can produce.

  - **Stop (mobile, web — required there).** Report where each target PR
    stands — per-leg counts, `2/4 legs done`, red or pending named — then
    **end the turn** and tell the human to re-run `/prm` once CI is green.
    Never `subscribe_pr_activity`, never `send_later`, never a routine, cron
    or wake-up: **sessions end at their deliverable**
    (`PyAutoMind/policy/end_at_deliverable.md`). A mobile `/prm` that armed a
    subscription and an hourly check-in kept renewing it all night with no task
    active and drained a day's usage (2026-09-03, 02:39 → 12:11 UTC); five
    batch members did the same on 2026-08-31. Waiting for CI is the human's
    next `/prm`, not a timer this session leaves running.
  - **Poll (local CLI).** Every ~90s, one compact line per poll
    (`3/4 legs done`), capped at ~30 min — the poll must finish **inside this
    turn**, and that cap is what guarantees it does. Then report where it
    stands rather than spinning. No mechanism may outlive the turn: if the cap
    is reached, stop and hand back, exactly as the mobile lane does.
- **Red** — **fetch the failing job's log immediately** (GitHub purges the blob;
  once purged the failure is unnameable forever), quote the failing step, and
  stop. Do not merge, do not re-run, do not "wait for the flake to pass". Offer
  `/bug`, or a named re-run if the user judges it a flake — their call, not yours.
- **No checks configured** — say so explicitly and ask before merging.

## 4. Merge

Green on every leg → merge, in this order:

**PRs shipped under the Heart RED development override.** The shipping grant
alone is not merge authority. Require a separate explicit human merge command
and every required GitHub check green; never force, override protection, or
treat Heart RED as cleared. A live message may authorize both shipping and
merge, but that merge grant lasts only for the current turn. If the turn ends
before checks are green, it expires: arm no waiter or auto-merge, stop, and
require the human to invoke `/prm` again. This permission never reaches a
release or release rehearsal.

1. **Library freeze gate:** for library PRs, read [freeze.md](freeze.md) and
   check Heart's freeze flag. Stop when frozen unless the human supplied
   `--thaw "<why>"`; record that override. Never thaw past red CI.
2. **Library PR first.** The workspace PR may not merge until its upstream
   library PR is `MERGED` — the library-first gate
   ([`../ship_workspace/reference.md`](../ship_workspace/reference.md)). Refuse
   otherwise; there is no `--auto`-flag workaround.
3. `gh pr merge <n> --merge` per PR (`-R owner/repo` when you have no checkout),
   then confirm the state is `MERGED` — queued or auto-merge is not merged. Never
   `--delete-branch`: it takes the local branch too, orphaning a task worktree.
4. **Clear anything an older run left armed.** Step 3 arms nothing, so this is
   hygiene: if the harness's routine list shows a subscription or a
   `send_later` reminder on a target PR, drop it (`unsubscribe_pr_activity`,
   cancel the reminder). Never create one.

Never force, never override a protection, never rewrite history. If a merge is
refused by GitHub, report the reason verbatim and stop.

## 5. Close the task out

After every target PR is confirmed merged, **read and execute
[closeout.md](closeout.md)** in order. It retains the complete mandatory
procedure: prove each claimed branch merged, close the issue, move the prompt
with `lifecycle.py close`, retain pending-release obligations, record any
notify-tier shadow row, reconcile references and regenerate the dashboard,
then remove the worktree and local branches. No close-out on partial evidence.
Use the current step's [reference section](reference.md), not the whole file.

## 6. The only guards that stop you

Stop and report instead of pressing on when:

- a branch in the task is **unmerged** with no open PR (step 5.1) — the waves trap;
- Heart's **freeze** is active and a target PR is in a library repo (step 4),
  and no `--thaw "<why>"` was given;
- `worktree_remove` **refuses** (dirty repo, stale claim) — fix the cause, never
  `PYAUTO_WT_FORCE=1` past it;
- the worktree holds **gitignored data products** (reduced datasets, caches,
  `output/` fits) — removal destroys them, and they may not be cheaply
  re-derivable. List them with sizes and **ask once**: delete, or keep the
  worktree and finish the rest. `/prm`'s only question, and only when they exist.

## Notes

- `/prm` merges an **existing** PR. No PR yet → `/ship_library` or
  `/ship_workspace` first; `/prm` will say so rather than opening one. The one
  exception is Mind's own close-out commit, which needs no PR at all: pushing
  the branch is what lands it (step 5.4).
- It never bypasses the Heart readiness gate — that ran at ship time, and a red
  Heart is not something a merge shortcut may re-judge. The **freeze** flag
  (step 4) is a different thing and does not re-run anything: readiness answers
  "is the organism healthy", the freeze answers "is a validation window open
  right now". Nor does merge ever stop
  being human: `/prm` is a human-typed door, never invoked by the `--auto` queue.
- A task with no issue, no Mind prompt, or no worktree (a direct wiring change,
  say) skips those sub-steps and says so — not an error. That licence does **not**
  extend to the dashboard regen, skippable only where the close-out wrote nothing
  to Mind at all: re-rendering a current tree is a clean-`git status` no-op, so
  when in doubt run it.
