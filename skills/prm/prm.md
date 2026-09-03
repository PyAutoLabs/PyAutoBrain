# /prm — PR, CI green, then merge

The last thing you type for a task: watch the feature PR's checks, merge the
moment they are genuinely green, then close the task out — issue closed, prompt
moved `active/` → `complete/`, `dashboard.md` reconciled and regenerated,
worktree and local branches removed — and hand back a ledger.

Each step below has a matching section in [`reference.md`](reference.md) carrying
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
- **`mcp`** (mobile, web, Codex) — no multi-repo checkout and **no `gh` at
  all**: GitHub is the `mcp__github__*` surface, mapped step by step in
  [`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md). Drive every step through it,
  **skip the local-only cleanup** with a one-line note, never `cd` into a repo
  that isn't there, and never report the close-out blocked for want of `gh`.
  `/prm` **deletes no remote branch on any surface** (step 5.6), so nothing here
  needs the second probe that step used to carry.

### The `mcp` lane, step by step

Every GitHub call a close-out makes, so a mobile run reads this page and the
mapping page only if something here is missing. Names take the
`mcp__github__` prefix; `ToolSearch` fetches a schema that is not loaded.

| Step | Call |
|---|---|
| 1 resolve | `list_pull_requests` (state `open`), or `pull_request_read` `get` for a known number. Mind's `active.md` via `get_file_contents` |
| 2 judge CI | `pull_request_read` `get_check_runs` — every check on the head commit, in one call. Then `pull_request_read` `get` for `mergeable` / `merge_state_status` |
| 2 by workflow | `actions_list` `list_workflow_runs` **has no `head_sha` filter** (`workflow_runs_filter` is actor/branch/event/status only): filter by `branch`, then match `head_sha` yourself, or you will judge a stale run. Legs: `actions_list` `list_workflow_jobs`, `resource_id` = run id |
| 3 stop | **No call.** On this surface step 3 is judge-once-then-stop: no `subscribe_pr_activity`, no `send_later`. Report where each PR stands and end the turn; the human re-runs `/prm` when CI is green |
| 3 red | `get_job_logs` with `run_id`, `failed_only: true`, `return_content: true` — **before** anything else, the blob is purged |
| 4 merge | `merge_pull_request` (`merge_method: "merge"`), then `pull_request_read` `get` to confirm `MERGED`; `unsubscribe_pr_activity` only to clear a stale subscription an older run left |
| 5.2 issue | `add_issue_comment`, then `issue_write` `update` with `state: "closed"` and `state_reason: "completed"` — an unset reason is what leaves an issue reading "closed as not planned" |
| 5.1 proof | git, not GitHub — and `--is-ancestor` needs an unshallowed clone (`reference.md` §1) |

Steps 5.3-5.7 touch no GitHub API at all; what they need is a checkout, and the
note at the foot of step 5 says what to do without one.

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

1. **The Heart freeze window — library PRs only.** A release validation is a
   window in which the library `main`s must not move: a merge landing inside it
   invalidates the evidence and restales the rehearsal (~75 minutes, measured
   2026-08-29). Heart's flag says whether one is open:

   ```bash
   pyauto-heart freeze --show      # exit 3 = frozen; 0 = clear or expired
   ```

   Active **and** a target PR is in a **library** repo (the `category: library`
   entries of `PyAutoMind/repos.yaml`) → stop, report the `FROZEN: …` line
   verbatim, and say when it expires. Organ and workspace repos are not gated;
   a workspace PR whose library half is held waits on the library-first gate
   below anyway. Where Heart is not installed (mobile, web, CI) there is
   nothing to read — say so in one line; an absent flag is not a freeze.

   **`--thaw "<why>"` is the only way past**, and it is loggable by
   construction: merge, then append one row to `PyAutoMind/autonomy_log.md`
   under a `## Freeze overrides` heading (create the section, with this header,
   on first use) —

   ```
   | date | task / PR | freeze reason | until | thawed by | why |
   ```

   — in the same Mind push the close-out already makes (step 5.4). The override
   exists because a freeze is advice about evidence, not a protected branch,
   and an unloggable override is one people route around instead of recording.
   Never thaw silently, and never thaw to get past a red check: this gate is
   about *when*, and step 2 is about *whether*.
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

Typing `/prm` authorized all of this; the only questions are the guards in step
6. Order is forced by the tooling, so do not reorder:

1. **Prove every branch merged, per repo** — a `complete/` record is a write-up,
   not a merge receipt, and a task may have shipped in waves. Ask git, per repo
   the task claims, never the record. Any repo with unmerged commits and no open
   PR **stops the close-out**: a half-merged task must not be recorded complete.
2. **Issue** — post the "Shipped" comment (template: `../ship_library/reference.md`
   → "Issue comments + Mind state"), then close it. `gh issue close` is broken in
   this gh; use the REST path.
3. **Mind: `active/` → `complete/`** — draft the completion body, then
   `lifecycle.py record … --prompt <bare-filename> --apply`. A *path* there
   silently no-ops, so verify all three effects rather than the exit code.

   **Record the scope you merged, not the scope you filed.** On a partial merge,
   record what shipped and re-file the remainder as a fresh
   `draft/<work-type>/<target>/` prompt pointing back at the record. Recording a
   prompt whole on a partial merge is what leaves half-done work on the dashboard
   as pickable backlog.
4. **Mind: leave the page true** — the close-out is finished when `dashboard.md`
   stops offering this work, not when the claim is released.
   `dashboard_refresh.yml` heals a stale *render*, never a stale *prompt*, so
   this leg belongs to `/prm` and to nothing else.

   1. **Sweep** — grep the slug and the prompt filename across `draft/`,
      `active/`, `epics.md` and the registry files; repoint or remove every hit
      the merge falsified (an unblocked `blocked-by:`, a finished epic phase, a
      `superseded-by:` chain that now ends in a record).
   2. **Reconcile** — `pyauto-brain intake reconcile draft/<work-type>/<target>`
      over the shipped prompt's folder plus any the merged diff lands in;
      folder-scoped, never whole-backlog. **Proof retires, resemblance reports**:
      a sibling this merge provably covers gets its own record and `git rm` under
      the same `/prm` authorization; one that merely *looks* alike gets a ledger
      line and the `/intake reconcile` door — never a second question (step 6
      owns the only one).
   3. **Regenerate — always**, whatever 1 and 2 found; moving a prompt into
      `complete/` changes the page by itself, so this leg has no "nothing
      changed" exit, only a `--check` that says the render is current:

      ```bash
      pyauto-brain intake --apply dashboard     # writes dashboard.md + dashboard.html
      pyauto-brain intake dashboard --check     # must print "…are current"
      ```

   Never hand-edit either page. Commit the render **with** the record, then
   `lifecycle.py check` and push Mind. `git show --stat HEAD` must name both
   dashboard files beside the record, or leg 3 did not happen.

   **Push the branch you are on — never force `main`.** On a laptop that branch
   *is* `main`. On a branch-scoped surface (the phone, claude.ai/code, any
   `claude/**` flow) it is the session's branch, and pushing it is the whole
   job: a close-out diff is ledger by construction, so
   `mind_ledger_merge.yml` merges it into `main` and deletes the branch within
   a minute — no PR, and no "merge that branch too" left for the human. Say in
   the ledger that the Mind branch was pushed and will land itself. Two things
   change that: the close-out also touched `scripts/`, `.github/`, `skills/` or
   another code path (then the branch waits for a human — say so plainly), or
   `lifecycle.py check` fails (then it was never going to merge; fix the drift).
   `python3 scripts/ledger_merge.py classify --base origin/main` in the Mind
   checkout tells you which of the three you are in.
5. **Worktree** — `worktree_remove <task>`, never `rm -rf`. It refuses on a dirty
   repo and on a claim still registered in `active.md` — which is exactly why
   step 3 comes first.
6. **Local branches only** — delete a local `feature/<task>` left in the
   canonical checkout, never one whose merge you did not prove in sub-step 1.
   **The remote branch is not yours to delete**: GitHub removes a merged head
   itself, and `branch_sweep*.yml` / `/repo_cleanup` collect what escapes.
   Nothing to do, and no ledger line — not "deferred", not "blocked".
7. **Report the ledger** — PRs merged, issue closed, record path, `active.md`
   released, **dashboard regenerated** (plus any sibling retired, any suspect
   left standing with its `/intake reconcile` prefix), worktree removed, and
   anything skipped. That dashboard line is not prose: if you cannot write it,
   leg 4.3 did not run — go back and run it.

**On `mcp`:** 1 and 2 run as usual; 3 works if PyAutoMind is checked out, else
the record is pending. Leg 4 needs **both** checkouts (state is Mind's, renderer
is Brain's): with only Mind, sweep and reconcile and leave the render to
`dashboard_refresh.yml`; with neither, call the leg pending rather than implying
the page is true. 5 and 6 are local-only — name 5 outstanding, say nothing of 6.

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
