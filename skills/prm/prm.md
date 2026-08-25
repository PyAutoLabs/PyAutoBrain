# /prm — PR, CI green, then merge

The end-of-task shortcut for "PR CI green then merge" — and the **full task
close-out**: the last thing you type for a task. It watches the feature PR's
checks, merges the moment they are genuinely green, then closes the task out
completely — issue closed, PyAutoMind moved `active/` → `complete/`, the Mind's
`dashboard.md` reconciled and regenerated, worktree removed, branches deleted —
and hands back a ledger of what it did.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.
gh mechanics + snippets: [`reference.md`](reference.md).

## Principle: compose, don't recompute

Every rule here already has an owner. The merge gates belong to
[`../ship_library/ship_library.md`](../ship_library/ship_library.md) and
[`../ship_workspace/ship_workspace.md`](../ship_workspace/ship_workspace.md)
(library-first gate, issue completion, Mind state); the verdict belongs to GitHub
Actions; the lifecycle moves belong to `PyAutoMind/scripts/lifecycle.py` and the
dashboard render to [`../intake/intake.md`](../intake/intake.md). `/prm` only
sequences them. It never re-runs the readiness gate, never edits code to make a
check pass, never opens a PR — that is `/ship_*` — and never hand-writes a
generated page.

## Usage

```
/prm                      # the PR for the current branch / current task
/prm 380                  # PR #380 in the current or inferred repo
/prm PyAutoArray#42       # or Jammy2211/PyAutoArray#42, or the full PR URL
/prm --no-wait            # judge CI once and report; merge only if already green
```

## Environment: runs anywhere gh is authenticated

Local CLI, mobile Claude Code chat, and Codex all work — every step is `gh`, no
checkout required. Detect which you are in:

- **Local** — `$PYAUTO_ROOT` (default `~/Code/PyAutoLabs`) holds the sibling
  repos. Branch detection and post-merge worktree cleanup are available.
- **Remote (mobile/codex)** — no multi-repo checkout. Resolve the PR from the
  argument or by listing candidates (below), and **skip the local-only cleanup**
  with a one-line note. Never `cd` into a repo that isn't there.
- **Proxied web session (Claude Code on the web)** — remote as above, **plus it
  cannot delete remote branches at all**: the egress proxy refuses ref deletions.
  Probe once, before the close-out, and remember the answer for the whole run:

  ```bash
  curl -sf "$HTTPS_PROXY/__agentproxy/status" >/dev/null && echo "ref deletes blocked"
  ```

  An answer means every `git push origin --delete` in this run will fail. Branch
  cleanup is then **out of scope for the run**: don't attempt it, and don't
  mention it — see step 5.

## The routine

### 1. Resolve the target PR(s)

In order: explicit argument → current branch (`gh pr view --json` in the repo you
are in) → the claimed task in `PyAutoMind/active.md` (its `library-pr:` /
`workspace-pr:` entries; on mobile read it with `gh api`) → `gh pr list` across
the claimed repos. If more than one candidate survives, **list them numbered and
ask once** — never guess which PR to merge. Report each target as
`owner/repo#N — title — branch` before doing anything.

A task that shipped both a library and a workspace PR is **one** `/prm` run over
both, merged in gate order (step 4).

### 2. Judge CI honestly — every run, every leg

A head sha triggers **two** runs of each workflow (`push` and `pull_request`),
each with its own matrix legs. One green row is not "CI green". Enumerate every
run for the head sha and every job inside it (snippets in `reference.md`), and
treat any run that is not `completed` as *not ready* — not "green so far".
`mergeStateStatus=UNSTABLE` is the tell that something is still pending or red.

Also read `mergeable` and `mergeStateStatus`: `CONFLICTING` / `BEHIND` /
`BLOCKED` stops the run with the reason, whatever the checks say.

### 3. Wait, or stop

- **Pending** — poll every ~90s, one compact line per poll (`3/4 legs done`).
  Cap at ~30 min; then report where it stands and stop rather than spinning.
  Under `--no-wait`, skip the loop: report and stop.
- **Red** — **fetch the failing job's log immediately** (GitHub purges the blob;
  once purged you can never name what broke), quote the failing step, and stop.
  Do not merge, do not re-run, do not "wait for the flake to pass". Offer the
  next door: `/bug` for a real failure, or a named re-run if the user judges it a
  known flake — their call, not yours.
- **No checks configured** — say so explicitly and ask before merging.

### 4. Merge

Green on every leg → merge, in this order:

1. **Library PR first.** The workspace PR may not merge until its upstream
   library PR is `MERGED` — the library-first gate
   ([`../ship_workspace/reference.md`](../ship_workspace/reference.md)). Refuse
   otherwise; there is no `--auto`-flag workaround.
2. `gh pr merge <n> --merge` per PR (add `-R owner/repo` when you have no
   checkout), then confirm the resulting state is `MERGED` — a queued or
   auto-merge state is not a merge. Do **not** pass `--delete-branch`: it deletes
   the local branch too, which fails or orphans a task worktree. Branch deletion
   belongs to the post-merge cleanup in step 5.

Never force, never override a protection, never rewrite history. If a merge is
refused by GitHub, report the reason verbatim and stop.

### 5. Close the task out

Typing `/prm` authorizes the whole close-out — merge **and** issue close **and**
cleanup. Run all of it without asking again; the only questions are the guards in
step 6. Order is forced by the tooling, so do not reorder:

1. **Prove every branch merged, per repo.** The task may have shipped in waves —
   a completion record is a write-up, not a merge receipt. For each repo the task
   claims, `merge-base --is-ancestor origin/feature/<task> origin/main` and
   `rev-list --count origin/main..origin/feature/<task>` (want 0). Any repo with
   unmerged commits and no open PR → **stop the close-out** and report it; a
   half-merged task must not be recorded complete.
2. **Issue** — post the "Shipped" comment (template: `../ship_library/reference.md`
   → "Issue comments + Mind state"), then close it. `gh issue close` is broken in
   this gh; use the REST path in [`reference.md`](reference.md).
3. **Mind: `active/` → `complete/`** — draft the completion body, then
   `lifecycle.py record <slug> --date … --from-file … --prompt <bare-filename>
   --apply`. The `--prompt` argument is a **bare filename**; a path silently
   no-ops. Verify all three effects (record has `## Original prompt`, the
   `active/` prompt is gone, the `## <task>` entry left `active.md`).

   **Record the scope you merged, not the scope you filed.** Where the merged
   PRs cover only part of what the prompt asked for — one phase of a campaign,
   three of five findings — neither recording the whole prompt complete nor
   leaving the whole prompt in `active/` is true. Record what shipped, and
   re-file the remainder as a fresh `draft/<work-type>/<target>/` prompt whose
   header points back at the record. A prompt recorded whole on a partial merge
   is exactly what puts a half-done task on the dashboard as pickable backlog.
4. **Mind: leave the page true** — the close-out is not finished when the claim
   is released; it is finished when `dashboard.md` stops offering this work.
   `dashboard_refresh.yml` self-heals a stale *render*, never a stale *prompt*,
   so this leg belongs to `/prm` and to nothing else — skipping it is how
   shipped and half-shipped tasks accumulate on the page.

   Legs 1 and 2 are judgement and may find nothing. **Leg 3 is a command, and it
   runs on every close-out that touched Mind at all** — including the ordinary
   one where the sweep is clean and no sibling is retired. Moving a prompt
   `active/` → `complete/` changes the page by itself; a close-out that recorded
   the task and did not re-render has left the page wrong. There is no "nothing
   changed" exit from leg 3, only a `--check` that says the render is current.

   1. **Sweep what this task is named in.** Grep the slug and the prompt
      filename across `draft/`, `active/`, `epics.md` and the registry files.
      Repoint or remove every hit the merge falsified: a `blocked-by:` this PR
      unblocked, an epic phase now done, a `superseded-by:` chain that now ends
      in a record.
   2. **Reconcile the neighbourhood.** Run `pyauto-brain intake reconcile
      draft/<work-type>/<target>` over the folder the shipped prompt came from,
      plus any folder the merged diff lands in — folder-scoped it is a handful
      of prompts, not the 130-odd of the whole backlog. Then: **proof retires,
      resemblance reports.** A sibling the merge provably covers — its issue
      closed by this PR, its scope inside the record you just wrote, a merged PR
      named in its own body — gets its own record and `git rm` under the same
      `/prm` authorization. One that merely *looks* alike gets a ledger line
      naming it and the `/intake reconcile` door; never retire on resemblance,
      and never turn this sweep into a second question (step 6 owns the only one).
   3. **Regenerate — always.** Two commands, in this order, no condition on
      either:

      ```bash
      pyauto-brain intake --apply dashboard     # writes dashboard.md + dashboard.html
      pyauto-brain intake dashboard --check     # must print "…are current"
      ```

      Never hand-edit `dashboard.md` / `dashboard.html`. Commit the render
      **with** the record, in one commit: the workflow's heal commit is made
      with `GITHUB_TOKEN`, which triggers no other workflow and has to
      re-dispatch `pages_dashboard.yml` by hand, so a self-healed page reaches
      Pages later than a correctly-committed one — and heals nothing you retired
      in 1 and 2.

   Then `lifecycle.py check` and push Mind — on `main`, and note that
   `prompt_sync_push` stages `-A`, so check for unrelated work first. The push
   is not the end of the leg: `git show --stat HEAD` must name `dashboard.md`
   and `dashboard.html` alongside the record, or leg 3 did not happen.
5. **Worktree** — `worktree_remove <task>` (source `bin/worktree.sh`, `PYAUTO_MAIN`
   set), never `rm -rf`. It refuses on a dirty repo and on a claim still
   registered in `active.md` — which is exactly why step 3 comes first.
6. **Branches** — delete the remote `feature/<task>` per proven-merged repo, plus
   any local branch left in the canonical checkout. Never delete a branch whose
   merge you did not prove in sub-step 1. **Where the environment cannot delete
   remote refs** (proxied web session, above), this sub-step does not exist:
   attempt nothing, and report nothing about it. `/repo_cleanup` finds those
   branches on origin by itself, so silence here loses nothing.
7. **Report the ledger** — PRs merged, issue closed, record path, `active.md`
   released, **dashboard regenerated** (plus any sibling prompt retired, and any
   suspect left standing with its `/intake reconcile` prefix), worktree removed,
   branches deleted, and anything skipped. Branches are simply absent from the
   ledger where sub-step 6 did not apply. The dashboard line is not optional
   prose: if you cannot write it, leg 4.3 did not run — go back and run it.

**Remote (mobile/codex):** sub-steps 1 and 2 run over `gh`/`git ls-remote` as
usual. Mind (3) works if PyAutoMind is checked out; otherwise say the record is
pending. The dashboard leg (4) needs **both** checkouts — the state is Mind's,
the renderer is Brain's; with only Mind, do its sweep and reconcile legs and say
the render
is left to `dashboard_refresh.yml`; with neither, say the whole leg is pending
rather than implying the page is true. The worktree (5) is local-only — name it
as outstanding rather than implying it ran. Branches (6) delete normally from
mobile and Codex; a proxied web session drops the sub-step silently.

### 6. The only guards that stop you

Stop and report instead of pressing on when:

- a branch in the task is **unmerged** with no open PR (step 5.1) — the waves trap;
- `worktree_remove` **refuses** (dirty repo, stale claim) — fix the cause, never
  `PYAUTO_WT_FORCE=1` your way past it;
- the worktree holds **gitignored data products** (reduced datasets, caches,
  `output/` fits) — removal destroys them and they may not be cheaply
  re-derivable. List them with sizes and **ask once**: delete, or keep the
  worktree and finish everything else. This is the one question `/prm` asks, and
  only when such files exist.

## Notes

- `/prm` merges an **existing** PR. No PR yet → `/ship_library` or
  `/ship_workspace` first; `/prm` will say so rather than opening one.
- It never bypasses the Heart readiness gate — that gate ran at ship time, and a
  red Heart is not something a merge shortcut may re-judge.
- Under a `--auto` workflow run, merge stays human: `/prm` is a human-typed door
  and is never invoked by the autonomous queue.
- A task with no issue, no Mind prompt, or no worktree (a direct wiring change,
  say) simply skips those sub-steps and says so — it is not an error. That
  licence does **not** extend to the dashboard regen: it is skippable only where
  the close-out wrote nothing to Mind at all. Re-rendering an already-current
  tree is a no-op that leaves `git status` clean, so when in doubt, run it —
  the cheap mistake is the redundant render, not the stale page.
