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

An empty run list is not green — it means no workflow fired for that sha. The
usual causes, in order of likelihood: **the PR is `CONFLICTING`/`DIRTY`**, so
GitHub cannot build the merge ref and no `pull_request` run is created (observed
2026-08-23 on this very skill's PR — merge `main` in, and the runs appear on the
new head); a path filter excluded the change; the branch's workflow only fires on
`main`; or Actions is degraded. Say which one it is rather than reporting
"no failures".

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

## The close-out

### 1. Prove every branch merged (before recording anything)

A `complete/` record is a write-up, not a merge receipt — a task that shipped in
waves gets its record on the first wave while later branches keep living on
origin. Prove it per repo, never from the record and never from a clean
`git status`:

```bash
git -C <repo> fetch origin --quiet
git merge-base --is-ancestor origin/feature/<task> origin/main && echo MERGED || echo UNMERGED
git rev-list --count origin/main..origin/feature/<task>          # want 0
```

`UNMERGED` with no open PR → stop the close-out and report which repo. Squash
merges break `--is-ancestor`; fall back to the PR's `state=MERGED`.

### 2. Issue: comment, then close

`gh issue close` prints its usage string and exits non-zero in this gh (2.4.0) —
use the REST path:

```bash
gh issue comment <n> -R <owner>/<repo> --body "$(cat <<'EOF'
## Shipped
<summary, PR links, what changed>
EOF
)"
gh api -X PATCH repos/<owner>/<repo>/issues/<n> -f state=closed --jq .state   # → "closed"
```

### 3. Mind: active/ → complete/

```bash
cd $PYAUTO_MAIN/PyAutoMind
git rev-parse --abbrev-ref HEAD          # must be main — check BEFORE writing
python3 scripts/lifecycle.py record <slug>   --date <YYYY-MM-DD> --from-file <body.md> --prompt <prompt.md> --apply
```

`--prompt` takes a **bare filename** (it resolves as `active/<prompt>`); a path
like `active/foo.md` becomes `active/active/foo.md`, **exits 0 anyway**, and
leaves you with a record missing `## Original prompt` plus an orphan in
`active/`. Success prints `(+folds active/<name>)`. Verify all three effects —
none of them is announced on failure:

```bash
grep -c "## Original prompt" complete/<YYYY>/<MM>/<slug>.md   # want 1
ls active/<prompt>.md                                         # want "No such file"
grep -n "^## <task>" active.md                                # want no match
python3 scripts/lifecycle.py check                            # want clean exit
```

Then commit + push. `prompt_sync_push` runs `git add -A`, so check for unrelated
work first and use explicit pathspecs if any exists:

```bash
git status --short                                            # unrelated work?
source scripts/prompt_sync.sh && prompt_sync_push "complete: <task>"
```

### 4. Worktree

Removal deletes the whole task root — **including gitignored `output/`,
`cache/`, and downloaded data** that only live there (a reduced dataset + a
55-frame archive cache were destroyed this way on 2026-07-09). Look before you
remove, and ask once if anything real is there:

```bash
root=${PYAUTO_WT_ROOT:-$HOME/Code/PyAutoLabs-wt}/<task>    # worktree_root_path
du -sh "$root"/*/output "$root"/*/cache 2>/dev/null
git -C "$root/<repo>" status --porcelain --ignored | grep '^!!' | head -20
```

Then remove it properly — never `rm -rf`:

```bash
export PYAUTO_MAIN=$HOME/Code/PyAutoLabs
source PyAutoBrain/bin/worktree.sh && worktree_remove <task>
```

It **refuses** on a dirty repo, and on a merged task whose `active.md` claim is
still registered — that refusal means step 3 has not finished, so fix the cause.
`PYAUTO_WT_FORCE=1` exists for abandoned/unmerged work only; a close-out never
needs it. A `PyAutoLabs-wt/<task>/` dir whose worktrees are already gone survives as a shell
of symlinks + `activate.sh` and `git worktree list` will not name it — a
directory listing is the only way to find it.

### 5. Branches

Local branches go with the worktree; the remote ones do not. **First establish
whether this environment may delete remote refs at all** — one probe, once per
run, before any repo:

```bash
curl -sf "$HTTPS_PROXY/__agentproxy/status" >/dev/null && echo "ref deletes blocked"
```

An answer means a proxied web session (Claude Code on the web). There, a ref
deletion dies on the `git-receive-pack` POST:

```
error: RPC failed; HTTP 403 curl 22 The requested URL returned error: 403
send-pack: unexpected disconnect while reading sideband packet
```

That 403 is generated in front of GitHub — the ref advertisement to the same host
seconds earlier returns 200 with an `X-Github-Request-Id`, the 403 carries none —
so credentials, `gh` scopes and branch protection are **not** the cause, and no
retry, repo, or token changes it. The GitHub MCP surface has no delete verb
either (`create_branch` exists; nothing deletes a ref). So in that environment
**this whole sub-step is out of scope**: run no delete, and write no line about
branches in the ledger — not "deferred", not "blocked", not "see /repo_cleanup".
The step is structurally impossible there and would say the same thing on every
close-out, so it is noise, not a finding.

Nothing is lost by the silence: `/repo_cleanup` Bucket B enumerates origin
branches directly (`gh api repos/<owner>/<repo>/branches`), so it rediscovers
these on the next local sweep without being told. Repo-side, "Automatically
delete head branches" (Settings → General → Pull Requests) removes the need for
the sub-step altogether.

Report a blocked delete only if the user **asks** where a branch went.

Otherwise — local CLI, mobile, Codex — delete as usual:

```bash
git -C <repo> push origin --delete feature/<task>
git -C <repo> branch -d feature/<task>        # if one survives in the canonical checkout
git -C <repo> fetch --prune
```

Only branches proven merged in step 1. `git ls-remote --heads origin feature/<task>`
is the ground truth that the delete landed. If a delete 403s where you expected it
to work, treat it as the proxied case from that point on: **stop after the first
refusal** and drop the sub-step — do not repeat the push per repo, and do not
narrate the failure.

### 6. The ledger

Report, per line: PR(s) merged (URL + `MERGED`), issue closed (number + state),
record path under `complete/<YYYY>/<MM>/`, `active.md` claim released, worktree
removed, branches deleted, and **anything skipped** with the reason. A close-out
that quietly skipped a step reads exactly like one that finished — with one
deliberate exception: a sub-step the environment makes impossible (step 5 behind
the proxy) is omitted outright rather than reported as skipped.
