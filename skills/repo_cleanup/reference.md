# repo_cleanup — reference detail

Factored out of `SKILL.md`. The body is authoritative for the flow; this holds
the audit commands, the dashboard layout, the per-bucket execution recipes, the
recap, and the execution-environment fallback.

## Audit canonical checkouts

For each in-scope repo at `$PYAUTO_MAIN/<repo>`:

```bash
repo_path="$PYAUTO_MAIN/<repo>"
[[ -d "$repo_path/.git" ]] || { echo "skip: $repo_path (not a git repo)"; continue; }
current=$(git -C "$repo_path" branch --show-current)
dirty=$(git -C "$repo_path" status --porcelain | head)
git -C "$repo_path" fetch --prune --quiet origin
gone=$(git -C "$repo_path" for-each-ref --format='%(refname:short) %(upstream:track)' refs/heads | grep '\[gone\]' | awk '{print $1}')
merged=$(git -C "$repo_path" branch --merged origin/main --format='%(refname:short)' | grep -vE '^(main|master)$')
stashes=$(git -C "$repo_path" stash list)
```

Per non-`main`/`master` local branch: ahead/behind origin
(`git -C "$repo_path" rev-list --left-right --count <branch>...origin/<branch>`),
open PR? (`gh pr list --repo <owner>/<repo> --head <branch> --state open --json number,url --jq 'length'`),
and — the load-bearing one for "is it safe to delete?" — **does it contribute
any content not already in `origin/main`?** Use the blessed tool, never a
hand-rolled ahead-count or `git cherry`/`merge-tree` one-off (those were wrong
three times — docs/agent_failure_modes.md D1/D2):
```bash
source PyAutoBrain/bin/branch_contribution.sh
branch_contribution "$repo_path" <branch> origin/main   # MERGED/ABSORBED = safe; CONTRIBUTES = keep/inspect; UNKNOWN = never delete
```
An ahead-count alone over-reports (a squash-/cherry-merged branch is "ahead" yet
contributes nothing); `branch_contribution` distinguishes MERGED/ABSORBED (safe
to condemn) from CONTRIBUTES (has unique content) and is honest about the one
case git 2.34.1 cannot disambiguate (a multi-commit squash reads as CONTRIBUTES).
Record per repo: current branch + dirty; full local branch list with ahead/behind
+ open-PR flag; `[gone]` upstreams; stash list (oldest first, subjects);
prune candidates (`git remote prune --dry-run origin`).

## Audit worktrees

Reuse the `/health worktrees` procedure logic (don't duplicate it) to get: every real worktree
under `$PYAUTO_WT_ROOT/<task>/<repo>`; which task each belongs to per `active.md`;
orphan roots; missing roots; dirty/unpushed counts. Collect the set of
`(repo, branch)` pairs checked out in any worktree — **protected**, excluded from
all delete buckets. Surface orphans/missing/mismatches under Warnings; don't fix
them here (point at `worktree_remove`/`worktree_create`/editing `active.md`).

## Protection sets

- `CLAIMED` — `(repo, branch)` pairs in `worktree_list_claimed` output.
- `IN_WORKTREE` — pairs actually checked out in a worktree on disk.
- `OPEN_PR` — pairs with ≥1 open PR per `gh pr list`.

A branch is **protected** iff it is in any of the three sets — reported, never
proposed for deletion.

## Dashboard layout

```
Repo Cleanup — Audit
====================
Summary
  6 libraries, 8 workspaces, 3 worktree roots scanned
  12 branches flagged across 5 repos · 4 stashes across 2 repos
  1 dirty canonical checkout · 0 orphan worktrees

Bucket A — Auto-deletable local branches (merged to origin/main, no PR, no claim, not in any worktree)
Bucket B — Auto-deletable remote branches (same criteria, branch exists on origin)
Bucket C — Stale tracking refs ([gone] upstreams / prune candidates)
Bucket D — Unmerged local branches (per-branch decision)
Bucket E — Stashes (per-stash decision)
Warnings  — DIRTY / NON-MAIN / OPEN PR / IN WT / ORPHAN (not cleaned — investigate manually)
```

One section per repo per bucket. Omit empty buckets; always print the Summary
counts even if zero.

## Per-bucket execution (fixed order)

Branches can't be deleted while a worktree holds them, so resolve worktree
Warnings first. Print the exact commands and get approval before each step.

1. **Warnings** (orphan/missing worktrees, dirty canonical) — auto-run nothing;
   tell the user the fix (`worktree_remove <task>`, edit `active.md`, commit/stash
   the dirty checkout). Ask whether to continue.
2. **Bucket C** — `git -C "$repo_path" remote prune origin` (show `--dry-run`
   first; one batch confirm).
3. **Bucket A** — `git -C "$repo_path" branch -d <branch>` (batch confirm). Only
   `-d`, never `-D`. If a branch refuses, re-classify into Bucket D — never
   escalate to `-D` silently.
4. **Bucket B** — `git -C "$repo_path" push origin --delete <branch>` (separate
   batch confirm). Only branches merged to `origin/main` **and** backed by a local
   ref (don't enumerate collaborator branches).
5. **Bucket D** — per-branch: show ahead/behind + `log --oneline origin/main..<branch>`;
   ask keep/force-delete/skip. Force-delete requires the user to type
   `yes, force delete <branch>` verbatim before `git branch -D <branch>`.
6. **Bucket E** — per-stash: `git stash show -p <id> | head -100`; ask
   keep/apply/drop. Apply uses `git stash apply` (never `pop`); drop needs
   explicit confirmation.

## Recap

```
Repo Cleanup — Recap
  Pruned tracking refs in N repos
  Deleted N local merged branches (M failed)
  Deleted N remote merged branches
  Force-deleted N unmerged branch(es)
  Dropped/Kept stashes ...
  Skipped N dirty canonical checkout(s) — commit or stash before next sweep
```

List anything the user opted to keep so the next sweep resumes from there.

## Execution environments

In a web-github / analysis-only session (no local checkout) destructive git ops
are unavailable — degrade to a **remote audit only**: skip all `git -C`; for each
in-scope repo enumerate remote branches
(`gh api repos/<owner>/<repo>/branches --jq '.[].name' --paginate`), cross-check
open PRs (`gh pr list --head <branch> --state open`), and report branches with no
open PR that are merged to `main`
(`gh api repos/<owner>/<repo>/compare/main...<branch>` → `ahead_by == 0`) as
**candidates** only. Do not delete remotely; recommend running on a local-dev
checkout to complete the sweep (which re-audits against local state). Skip
stash/dirty sections. Owner mapping: PyAutoConf/PyAutoFit → `rhayes777`, else
`Jammy2211`.
