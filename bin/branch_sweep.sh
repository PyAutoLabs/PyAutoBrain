#!/usr/bin/env bash
# branch_sweep.sh — the executable half of the repo_cleanup sweep, in a form
# that runs where the *session* cannot.
#
# WHY THIS EXISTS. A cloud/web Claude session (phone, claude.ai/code) can read
# every repo but cannot delete a remote ref: `git push origin --delete` comes
# back 403 from GitHub, and the GitHub tool surface exposed to those sessions
# has no delete-ref call at all. The proxy is not the blocker (it logs no relay
# failure) — the session credential simply is not allowed to remove refs. That
# left branch cleanup a laptop-only task, which is why 233 branches had piled
# up across Mind and Brain by 2026-08-25.
#
# A workflow's GITHUB_TOKEN is a different credential with `contents: write` —
# the same class that already self-heals dashboard.md straight onto main. So
# the sweep runs *inside the repo* on Actions, and any surface that can
# dispatch a workflow (mobile chat included) can drive it.
#
# WHAT IT WILL NOT DO. Deletion is irreversible from the branch's point of
# view, so the safety gates from skills/repo_cleanup/SKILL.md are enforced here
# rather than assumed of the caller:
#
#   * `main`, `master`, and the default branch          — never a candidate
#   * `archive/condemned/*`                             — PyAutoGut transit refs;
#     voiding these before their sweep-after date destroys the recovery path
#     the Gut exists to provide. The Gut voids them, not us.
#   * any branch that is the head of an OPEN pull request
#   * any branch git cannot prove is already contained in the base
#
# Containment is decided by branch_contribution.sh — the blessed tool, never a
# hand-rolled ahead-count (see docs/agent_failure_modes.md D1/D2: that question
# was got wrong three times in one day). MERGED and ABSORBED are certain. A
# CONTRIBUTES branch is deleted ONLY if it clears the squash check below.
#
# THE SQUASH CHECK. git 2.34 cannot see through a squash-merge: the branch
# reads CONTRIBUTES even though main holds every line of it. Rather than trust
# that, we prove it — find the first-parent commit on the base whose subject
# ends `(#N)` for a PR N whose head SHA is this branch's tip, and require its
# patch-id to equal the branch's own diff. Same content, arrived by a different
# route. Anything short of an exact match stays.
#
# Usage:
#   branch_sweep.sh --repo <path> --owner <o> --name <n> [--mode audit|delete]
#                   [--base origin/main] [--limit N]
#
# Exit: 0 clean · 1 usage/setup error · 2 one or more deletions failed.

set -uo pipefail

REPO="" OWNER="" NAME="" MODE="audit" BASE="origin/main" LIMIT=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)  REPO="$2";  shift 2 ;;
        --owner) OWNER="$2"; shift 2 ;;
        --name)  NAME="$2";  shift 2 ;;
        --mode)  MODE="$2";  shift 2 ;;
        --base)  BASE="$2";  shift 2 ;;
        --limit) LIMIT="$2"; shift 2 ;;
        *) echo "branch_sweep: unknown argument '$1'" >&2; exit 1 ;;
    esac
done
[[ -n "$REPO" && -n "$OWNER" && -n "$NAME" ]] || {
    echo "usage: branch_sweep.sh --repo <path> --owner <o> --name <n> [--mode audit|delete]" >&2
    exit 1
}
[[ "$MODE" == "audit" || "$MODE" == "delete" ]] || {
    echo "branch_sweep: --mode must be 'audit' or 'delete' (got '$MODE')" >&2; exit 1
}

g() { git -C "$REPO" "$@"; }

# --- prerequisites, before anything is touched -------------------------------
# Checked up front, and deliberately before the fetches below: without gh we
# cannot see open PRs, so we would refuse to sweep anyway — and refusing after
# rewriting the caller's clone (an unshallow is not free and not undoable)
# would be a rude way to say no.
command -v gh >/dev/null 2>&1 || {
    echo "branch_sweep: gh not found — cannot rule out open PRs, refusing to sweep" >&2
    exit 1
}
open_prs=$(gh pr list --repo "$OWNER/$NAME" --state open --limit 500 \
               --json headRefName --jq '.[].headRefName' 2>/dev/null)
if [[ -z "$open_prs" ]] && ! gh auth status >/dev/null 2>&1; then
    echo "branch_sweep: gh is not authenticated — cannot rule out open PRs" >&2
    exit 1
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=branch_contribution.sh
source "$here/branch_contribution.sh"

# --- history the verdicts depend on -----------------------------------------
# A shallow clone makes every ancestry question wrong in the same direction:
# nothing looks contained, so a MERGED branch reports CONTRIBUTES and the sweep
# silently protects everything. Deepen before asking anything.
#
# Ask git the question directly. Testing for a `shallow` file under
# `rev-parse --git-dir` does NOT work: with `-C` that path comes back relative
# to *our* cwd, not the repo's, so the answer is really "is the process's own
# directory a shallow clone?" — which on an Actions runner (whose checkout is
# shallow by default) is a confident yes about entirely the wrong repository.
if [[ "$(g rev-parse --is-shallow-repository 2>/dev/null)" == "true" ]]; then
    echo "→ unshallowing (verdicts are meaningless on a truncated history)"
    g fetch --unshallow --quiet origin || { echo "branch_sweep: unshallow failed" >&2; exit 1; }
fi
g fetch --prune --quiet origin || { echo "branch_sweep: fetch failed" >&2; exit 1; }
# PR head refs let us match a branch tip to the PR that carried it.
g fetch --quiet origin '+refs/pull/*/head:refs/remotes/pr/*' 2>/dev/null || true
g rev-parse --verify --quiet "$BASE^{commit}" >/dev/null || {
    echo "branch_sweep: base '$BASE' not found" >&2; exit 1; }

# --- PR tip index: branch tip SHA -> PR numbers ------------------------------
declare -A PR_FOR_SHA
while read -r sha ref; do
    PR_FOR_SHA[$sha]="${PR_FOR_SHA[$sha]:-} ${ref#refs/remotes/pr/}"
done < <(g for-each-ref --format='%(objectname) %(refname)' refs/remotes/pr)

# Squash-merge commits land on the base as first-parent subjects ending `(#N)`.
mapfile -t landed < <(g log --first-parent --format='%s' "$BASE" \
                        | sed -nE 's|.*\(#([0-9]+)\)$|\1|p' | sort -u)
landed_set=" ${landed[*]} "

# The authoritative answer, when the runner can reach the API: ask GitHub
# whether a MERGED pull request carried exactly this branch at exactly this
# tip. Nothing local can beat this — the patch-id proof below exists only for
# the offline case, and it is strictly more conservative (on the 2026-08-25
# sweep it cleared 13 of PyAutoMind's 19 squash-merges; this cleared all 19).
merged_pr_for() {
    local branch="$1" tip
    tip=$(g rev-parse "$branch")
    gh api "repos/$OWNER/$NAME/commits/$tip/pulls" \
       --jq ".[] | select(.merged_at != null and .head.ref == \"${branch#origin/}\") | .number" \
       2>/dev/null | head -1
}

# Returns 0 and echoes the proving commit when `branch` is a confirmed squash
# of a PR already on the base; returns 1 otherwise.
squash_proof() {
    local branch="$1" tip commit base_of pid_branch pid_commit n
    tip=$(g rev-parse "$branch")
    for n in ${PR_FOR_SHA[$tip]:-}; do
        [[ "$landed_set" == *" $n "* ]] || continue
        commit=$(g log --first-parent --format='%H %s' "$BASE" \
                   | awk -v n="$n" '$0 ~ "\\(#"n"\\)$" {print $1; exit}')
        [[ -n "$commit" ]] || continue
        base_of=$(g merge-base "$commit^" "$tip") || continue
        pid_branch=$(g diff "$base_of" "$tip"       | git patch-id --stable | cut -d' ' -f1)
        pid_commit=$(g diff "$commit^" "$commit"    | git patch-id --stable | cut -d' ' -f1)
        if [[ -n "$pid_branch" && "$pid_branch" == "$pid_commit" ]]; then
            echo "$n:${commit:0:8}"; return 0
        fi
    done
    return 1
}

default_branch=$(g symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)
default_branch="${default_branch#origin/}"
default_branch="${default_branch:-main}"

# Trunk names are protected whether or not they are THIS repo's default.
# A repo migrated main<-master keeps the old trunk as an ordinary branch, and
# once it is fully contained in main the sweep would happily delete it —
# breaking every stale clone, bookmark and doc that still points at it. The
# skill's own recipe has always excluded both names (`grep -vE
# '^(main|master)$'`); protecting only the default silently dropped half of
# that. Found by the first org-wide audit, where one repo's `master` survived
# on unique content alone.
is_trunk() { [[ "$1" == "$default_branch" || "$1" == "main" || "$1" == "master" ]]; }

# --- classify ----------------------------------------------------------------
safe=() keep=() protected=()
while read -r b; do
    [[ -n "$b" && "$b" != "HEAD" ]] || continue
    is_trunk "$b" && continue
    case "$b" in
        archive/condemned/*) protected+=("$b	gut-transit-ref"); continue ;;
    esac
    if [[ -n "$open_prs" ]] && grep -qxF "$b" <<<"$open_prs"; then
        protected+=("$b	open-pr"); continue
    fi
    verdict=$(branch_contribution "$REPO" "origin/$b" "$BASE"); word=${verdict%% *}
    case "$word" in
        MERGED|ABSORBED) safe+=("$b	$word") ;;
        CONTRIBUTES)
            # git says this has unique content. It may still be a squash-merge
            # git 2.34 cannot see through — so ask GitHub, then fall back to
            # proving it locally. Unproven means kept, never deleted.
            if pr=$(merged_pr_for "origin/$b") && [[ -n "$pr" ]]; then
                safe+=("$b	MERGED-PR#$pr")
            elif proof=$(squash_proof "origin/$b"); then
                safe+=("$b	SQUASHED(PR#${proof%%:*})")
            else
                keep+=("$b	unmerged")
            fi ;;
        *) keep+=("$b	$word") ;;   # UNKNOWN is never safe
    esac
    # Full refnames, not `:short`. Git abbreviates refs/remotes/origin/HEAD to
    # bare `origin`, which survives an `origin/` strip and a `!= HEAD` guard,
    # then reads as a branch named "origin" with verdict UNKNOWN — a symbolic
    # ref rendered as an unmerged branch. Harmless (UNKNOWN is never deletable)
    # but it is a null result dressed as a finding, which is the D1 mistake.
done < <(g for-each-ref --format='%(refname)' refs/remotes/origin \
           | sed 's|^refs/remotes/origin/||')

echo
echo "Branch sweep — $OWNER/$NAME (mode: $MODE, base: $BASE)"
echo "  ${#safe[@]} contained · ${#keep[@]} unmerged · ${#protected[@]} protected"
echo
[[ ${#protected[@]} -gt 0 ]] && { echo "PROTECTED (never swept)"; printf '  %s\n' "${protected[@]}"; echo; }
[[ ${#keep[@]}      -gt 0 ]] && { echo "KEEP (unique content)";   printf '  %s\n' "${keep[@]}";      echo; }
[[ ${#safe[@]}      -eq 0 ]] && { echo "Nothing to sweep."; exit 0; }

echo "CONTAINED IN $BASE"
printf '  %s\n' "${safe[@]}"
echo

if [[ "$MODE" == "audit" ]]; then
    echo "audit mode — nothing deleted. Re-dispatch with mode=delete to act."
    exit 0
fi

# --- delete ------------------------------------------------------------------
deleted=0 failed=0 n=0
for entry in "${safe[@]}"; do
    b="${entry%%	*}"
    if [[ "$LIMIT" -gt 0 && "$n" -ge "$LIMIT" ]]; then
        echo "  (limit $LIMIT reached — $(( ${#safe[@]} - n )) left for the next run)"; break
    fi
    n=$((n + 1))
    if g push origin --delete "$b" >/dev/null 2>&1; then
        echo "  deleted  $b"; deleted=$((deleted + 1))
    else
        echo "  FAILED   $b"; failed=$((failed + 1))
    fi
done
echo
echo "→ $deleted deleted, $failed failed, ${#keep[@]} kept, ${#protected[@]} protected"
[[ "$failed" -eq 0 ]] || exit 2
