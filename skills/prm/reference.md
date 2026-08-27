# /prm — reference

Mechanics for [`prm.md`](prm.md). Lazy-loaded: read it when you actually run the
step. `gh` in this workspace is old (2.4.0) — it has **no `gh search`** and some
newer flags are absent, so everything below sticks to `gh pr` / `gh api`.

> **GitHub surface.** These are the `gh` mechanics. A Claude Code remote
> session has no `gh` and reaches GitHub through the `mcp__github__*` tools
> instead — each snippet below names an *operation* that
> [`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md) maps onto its MCP equivalent.
> Probe once (`command -v gh`) and read this page through that lens.

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

**On a shallow clone this answer is a lie, not a verdict.** A remote session
clones shallow (measured 2026-08-27: PyAutoMind arrived with 78 of 4478
commits), and `--is-ancestor` reports "not an ancestor" for a commit whose
ancestry is merely *absent* — so a merged branch reads `UNMERGED` and the
close-out stops on nothing. `session_bootstrap.sh` unshallows every checkout,
which is one more reason it is the first thing a session runs; if you did not
run it, `git rev-parse --is-shallow-repository` before trusting this step.

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

Do **not** commit yet — the dashboard leg below belongs in the same commit.

`lifecycle.py check` will not catch the partial-ship case: it compares
`active.md` slugs against `complete/` records and knows nothing about how much
of a prompt's scope the merge actually covered. That judgement is yours. Where
the merge covered part of it, write the record for the shipped part and re-file
the rest before committing:

```bash
# the remainder, as a fresh backlog prompt pointing back at the record
cat > draft/<work-type>/<target>/<remainder>.md <<'EOF'
# <remainder title>

- Status: split out of `<slug>` at close-out — phases 1-2 shipped in
  `complete/<YYYY>/<MM>/<slug>.md` (<PR links>); this is what remains.
...
EOF
```

### 4. Mind: leave the page true

`dashboard.md` / `dashboard.html` are generated from `draft/`, `active/` and the
registry files. `dashboard_refresh.yml` re-renders them on any push touching
those paths, so the *render* self-heals — but a prompt the merge finished and
nobody retired renders faithfully, as pickable backlog. That is the drift this
step exists for, and `intake reconcile` measures it: the whole-backlog run on
2026-08-25 ranked **24 suspects of 138 scanned** while the page itself was
current.

**Sweep what this task is named in** — the merge falsifies more than its own
prompt:

```bash
cd $PYAUTO_MAIN/PyAutoMind
grep -rn "<slug>\|<prompt-filename>" draft/ active/ epics.md \
     active.md planned.md parked.md condemned.md
```

Repoint or remove each hit: a `blocked-by:` this PR unblocked, an epic phase now
done, a `superseded-by:` chain that now ends in a record.

**Reconcile the neighbourhood** — folder-scoped, not whole-backlog. Both are
fast (~5s bare, <1s scoped); the cost is *adjudication*, not runtime. The bare
run hands you 24 suspects spanning work this task never touched, none of which
`/prm` has proof for — a backlog chore, and incompatible with running to the end
without asking. A folder is the handful this merge could plausibly have
finished:

```bash
BRAIN=$PYAUTO_MAIN/PyAutoBrain/agents/conductors/intake/_intake.py
python3 "$BRAIN" --mind . reconcile draft/<work-type>/<target>
```

It is **read-only by design**: `--apply` is ignored with *"intake reconcile is
read-only — retiring prompts stays human"*, and the emit closes with the same
rule. Under `/prm` that human authorization is the typed `/prm` — but it extends
only as far as *proof*:

| Evidence | Action |
|---|---|
| The sibling's issue was closed by this PR (`Closes #N`), or its scope sits inside the record you just wrote, or its own body names a now-merged PR | Write its record (`lifecycle.py record …`), `git rm` the prompt, repoint references |
| `shared-identifiers` / `rare-topic-overlap` / `stale-status` only | Leave it filed; name it in the ledger with the prefix to re-run |

`record` serves a `draft/` prompt too, with one catch: `--prompt` resolves under
`active/` only, so the fold does not happen — append the draft's full text under
a `## Original prompt` heading in the `--from-file` body yourself, then `git rm`
the draft. Everything else (`complete/index.md`, the `active.md` prune) is
folded into `record` already.

**Why this is a skill step and not a `record` step.** Two chores that used to sit
here were folded into `lifecycle.py record` precisely because a separate step was
easy to forget — `complete/index.md` and the `active.md` prune, both after their
own drift-alarm email storms. The dashboard cannot follow them: the state is
Mind's but the renderer is Brain's (`agents/conductors/intake/_intake.py`), and a
Mind script importing a Brain module inverts the organ boundary — which is why
`dashboard_refresh.yml` checks out both repos to do it. So the render stays a
step someone has to take, and `/prm` is the door that takes it.

**Regenerate, and commit the render with the record.** Unconditional — the
sweep and the reconcile above may both come back empty, this does not:
`lifecycle.py record` alone changes what the page shows.

```bash
python3 "$BRAIN" --mind . --apply dashboard      # writes dashboard.md + dashboard.html
python3 "$BRAIN" --mind . dashboard --check      # "…are current"; exit 1 = drift
python3 scripts/lifecycle.py check
```

Or through the router, identically — `pyauto-brain intake --apply dashboard` and
`pyauto-brain intake dashboard --check`; use whichever the environment resolves.

Running it on an already-current tree is a **no-op**: the renderer rewrites both
files byte-identically and `git status` stays clean, so there is never a reason
to guess whether it is needed. `--apply` prints
`Wrote: dashboard.md + dashboard.html (<n> prompts, <n> hygiene flag(s))`.

`--check` exits **1** for drift and anything higher for a renderer failure
(Brain/Mind version skew) — a non-1 code is not a stale page, so read the
message rather than re-rendering.

Then commit + push. `prompt_sync_push` runs `git add -A`, so check for unrelated
work first and use explicit pathspecs if any exists:

```bash
git status --short                                            # unrelated work?
source scripts/prompt_sync.sh && prompt_sync_push "complete: <task>"
git show --stat HEAD                                          # names dashboard.md + dashboard.html?
```

That last line is the leg's own check: a close-out commit that does not carry
`dashboard.md` and `dashboard.html` beside the record did not regenerate, and
the ledger's dashboard line would be a claim you cannot back.

One commit carrying the record, the retirements and the regenerated pages is the
goal. The workflow's fallback is strictly worse: its heal commit is made with
`GITHUB_TOKEN`, which triggers no other workflow, so it must dispatch
`pages_dashboard.yml` itself for the Pages site to catch up — and it can only
heal the render, never the retirements from the sweep above.

### 5. Worktree

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

### 6. Branches

Local branches go with the worktree. **The remote branch is not `/prm`'s to
delete, on any surface** — GitHub removes a merged PR's head itself, kept on per
repo by `repo_settings.yml` (`delete_branch_on_merge`), and `branch_sweep.yml` /
`branch_sweep_all.yml` collect whatever escapes that: a head pushed without a
PR, a PR closed unmerged, a repo whose setting is off. `/repo_cleanup` Bucket B
does the same locally. So run no `git push --delete`, and write no branch line
in the ledger — not "deleted", not "deferred", not "blocked". There is nothing
to say.

```bash
git -C <repo> branch -d feature/<task>        # if one survives in the canonical checkout
git -C <repo> fetch --prune                   # drop tracking refs GitHub already deleted
```

Only branches proven merged in step 1.

**Why the remote half was removed rather than made conditional.** It used to be
a step with a probe in front of it, and the probe is what failed. In a proxied
web session a ref deletion dies on the `git-receive-pack` POST:

```
error: RPC failed; HTTP 403 curl 22 The requested URL returned error: 403
send-pack: unexpected disconnect while reading sideband packet
fatal: the remote end hung up unexpectedly
Everything up-to-date
```

Read the last line and the exit status: **`Everything up-to-date`, exit 0.** The
403 goes to stderr and git then reports success, so a close-out that ran the
delete could not tell it had failed — it reported branches deleted that were
still on origin. That 403 is generated in front of GitHub — the ref
advertisement to the same host seconds earlier returns 200 with an
`X-Github-Request-Id`, the 403 carries none — so credentials, `gh` scopes and
branch protection are **not** the cause, and no retry, repo, or token changes
it. The GitHub MCP surface has no delete verb either (`create_branch` exists;
nothing deletes a ref).

A step that is impossible on one surface and silently lies about it there is
worse than no step. And once GitHub deletes the head at merge it is redundant on
the surfaces where it *did* work — on a local CLI it would now fail on an
already-deleted ref, trading one spurious error for another.

If the user **asks** where a branch went: merged heads are deleted by GitHub at
merge; anything still standing belongs to the sweeper, and `branch_sweep.yml` in
`audit` mode lists it per repo without deleting anything.

### 7. The ledger

Report, per line: PR(s) merged (URL + `MERGED`), issue closed (number + state),
record path under `complete/<YYYY>/<MM>/`, `active.md` claim released, the
dashboard regenerated (and any sibling prompt retired, and any suspect left
standing with the prefix to re-run), worktree removed, and **anything skipped**
with the reason. A close-out that quietly skipped a step reads exactly like one
that finished — with one deliberate exception: remote branches are not a line at
all, since step 6 no longer touches them.

The dashboard lines carry the drift, so give them numbers rather than a verb:

```
dashboard: regenerated (dashboard.md + dashboard.html, same commit as the record)
  retired:  draft/bug/priors/15_transformed_message_logpdf_jacobian.md — PyAutoFit#1498 merged, scope inside this record
  standing: draft/bug/priors/14_replace_transform_stack_with_bijectors.md — resemblance only
            → /intake reconcile draft/bug/priors
```
