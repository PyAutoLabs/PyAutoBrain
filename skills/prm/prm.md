# /prm — PR, CI green, then merge

The end-of-task shortcut for "PR CI green then merge" — three keystrokes instead
of the sentence. It watches the feature PR's checks, merges the moment they are
genuinely green, and finishes the ship (Mind record, issue comment, cleanup).

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.
gh mechanics + snippets: [`reference.md`](reference.md).

## Principle: compose, don't recompute

Every rule here already has an owner. The merge gates belong to
[`../ship_library/ship_library.md`](../ship_library/ship_library.md) and
[`../ship_workspace/ship_workspace.md`](../ship_workspace/ship_workspace.md)
(library-first gate, issue completion, Mind state); the verdict belongs to GitHub
Actions. `/prm` only sequences them. It never re-runs the readiness gate, never
edits code to make a check pass, and never opens a PR — that is `/ship_*`.

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

### 5. Finish the ship

Hand back to the ship skills' completion steps — do not re-invent them:

- Post the "Shipped" comment on the issue (templates: `../ship_library/reference.md`
  → "Issue comments + Mind state").
- Write the dated completion record — `PyAutoMind/scripts/lifecycle.py record`
  (also refreshes the index and prunes the `active.md` entry) — and push Mind.
- **Ask before closing the issue.** Merging is what `/prm` was typed for; closing
  is a separate decision the human makes.
- **Local only:** offer the post-merge cleanup (worktree removal, local branch
  deletion) per the ship skills; on mobile/codex note it as still pending.

## Notes

- `/prm` merges an **existing** PR. No PR yet → `/ship_library` or
  `/ship_workspace` first; `/prm` will say so rather than opening one.
- It never bypasses the Heart readiness gate — that gate ran at ship time, and a
  red Heart is not something a merge shortcut may re-judge.
- Under a `--auto` workflow run, merge stays human: `/prm` is a human-typed door
  and is never invoked by the autonomous queue.
