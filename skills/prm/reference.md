# /prm — reference

Mechanics for [`prm.md`](prm.md). Lazy-loaded: read it when you actually run the
step. `gh` in this workspace is old (2.4.0) — it has **no `gh search`** and some
newer flags are absent, so everything below sticks to `gh pr` / `gh api`.

## Resolving the PR

```bash
# From the current branch (local checkout)
gh pr view --json number,url,title,headRefName,state,labels

# Explicit target, no checkout needed (mobile / Codex)
gh pr view <n> -R <owner>/<repo> --json number,url,title,headRefName,state

# Candidates when nothing is claimed: open PRs in one repo
gh pr list -R <owner>/<repo> --state open --json number,title,headRefName,labels

# The claimed task's PRs, read straight from Mind without a checkout
gh api repos/PyAutoLabs/PyAutoMind/contents/active.md --jq '.content' \
  | base64 -d | grep -iE 'library-pr:|workspace-pr:|issue:|  - '
```

Feature PRs from `/ship_*` carry the `pending-release` label — a useful filter,
never a merge blocker (the label describes the release state of the change, not
the mergeability of the PR).

## CI: every run, every leg

A single head sha gets **two** runs of each workflow (`push` + `pull_request`,
created seconds apart), each with its own matrix legs (e.g. py3.12 + py3.13). So
one `success` row is 1 of 4 signals. Enumerate all of them:

```bash
repo=<owner>/<repo>; pr=<n>
sha=$(gh api repos/$repo/pulls/$pr --jq '.head.sha')

# Every run for the sha
gh api "repos/$repo/actions/runs?head_sha=$sha" \
  --jq '.workflow_runs[] | "\(.name) [\(.event)]: \(.status)/\(.conclusion)"'

# Every job within every run
for run in $(gh api "repos/$repo/actions/runs?head_sha=$sha" --jq '.workflow_runs[].id'); do
  gh api repos/$repo/actions/runs/$run/jobs --jq '.jobs[] | "  \(.name)=\(.conclusion)"'
done

# Not-ready test: non-zero means keep waiting, NOT "green so far"
gh api "repos/$repo/actions/runs?head_sha=$sha" \
  --jq '[.workflow_runs[] | select(.status!="completed")] | length'
```

Cross-check the PR's own view — mergeability is independent of the checks:

```bash
gh pr view $pr -R $repo --json state,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup
```

- `mergeStateStatus`: `CLEAN` → mergeable · `UNSTABLE` → a check is pending or
  failed · `BLOCKED` → protection rule / review missing · `BEHIND` → base moved ·
  `DIRTY` → conflicts. Only `CLEAN` merges without a human decision.
- `mergeable`: `CONFLICTING` stops the run regardless of check colour.

An empty run list is not green — it means no workflow fired for that sha (a
docs-only path filter, a skipped event, or Actions being down). Say which.

## A red leg: grab the log *now*

GitHub purges job logs; once purged, `BlobNotFound` leaves the failure
unnameable forever. Fetch before reporting:

```bash
job=$(gh api repos/$repo/actions/runs/$run/jobs --jq '.jobs[] | select(.conclusion=="failure") | .id')
gh api repos/$repo/actions/jobs/$job/logs > /tmp/prm-failing-job.log
grep -nE 'FAILED|Error|assert|Traceback' /tmp/prm-failing-job.log | tail -40
```

Report the failing job name, the failing step, and the quoted error. A failure
that matches a known flake is still a failure — the user decides whether to
re-run; `/prm` does not decide that for them.

## Merging in gate order

```bash
# 1. library PR
gh pr merge <lib_n> -R <owner>/<lib_repo> --merge
gh pr view <lib_n> -R <owner>/<lib_repo> --json state --jq '.state'   # must print MERGED

# 2. only then the workspace PR
gh pr view <ws_n> -R <owner>/<ws_repo> --json body --jq '.body' | grep -iE 'PyAuto[A-Za-z]+/pull/[0-9]+'
gh pr merge <ws_n> -R <owner>/<ws_repo> --merge
```

The library-first gate is `../ship_workspace/reference.md` → "Library-first merge
gate": a workspace PR linked to an upstream library PR may only merge once that
PR reads `MERGED`. There is no workaround — not `--auto`, not `--admin`.

## Finishing

Completion is the ship skills' contract, unchanged:

- "Shipped" comment template → `../ship_library/reference.md` → "Issue comments +
  Mind state".
- `python3 PyAutoMind/scripts/lifecycle.py record --prompt <bare-filename>` —
  the argument is the **bare prompt filename**, not a path — then commit and push
  Mind (on `main`, and check that first).
- Closing the issue is a separate human decision: ask, don't assume.
- Local post-merge cleanup (worktree removal, local + remote branch deletion) →
  the `ship_library` / `ship_workspace` cleanup sections. On mobile/Codex, say
  it is still pending rather than pretending it ran.
