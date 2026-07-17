#!/usr/bin/env bash
# branch_contribution.sh — the ONE tested answer to "does this branch contribute
# any content not already in <base>?" (docs/agent_failure_modes.md item 4, the
# D1/D2 failure class).
#
# This question was hand-rolled three times in one day, two ways wrong:
#   D1: `git merge-tree --write-tree` needs git >=2.38; on 2.34.1 it failed for
#       all 57 branches and the null result rendered as a tidy `?? INSPECT`
#       column — a null result mistaken for a finding.
#   D2: `git cherry` reported `+` ("not upstream") for a branch that provably
#       contributed nothing — patch-id cannot see a squash-merge.
# The habit that DID work was D2's antidote: validate the instrument against a
# case whose answer you already know. So this tool ships with a self-test
# (`--self-test`) that constructs known-answer repos and asserts each verdict —
# the mitigation embodied, not merely documented.
#
# It is honest about what git can and cannot prove on this version:
#   MERGED      — branch tip is an ancestor of base: fully in base. CERTAIN.
#   ABSORBED    — every commit's patch-id is already in base (rebase/cherry-pick
#                 landed it): base contains the content. CERTAIN up to patch-id.
#   CONTRIBUTES — base+branch differ AND at least one commit's patch is not in
#                 base. Usually real; the ONE false-positive git cannot rule out
#                 on 2.34.1 is a squash-merge (content in base under a new
#                 patch-id) — flagged in the caveat, verify the PR before delete.
#   UNKNOWN     — branch or base missing / unfetched. NEVER treated as "safe to
#                 delete" by callers (fail-safe).
#
# (There is deliberately no EMPTY verdict: a branch with no commits ahead of
# base is an ancestor of it, which MERGED already reports.)
#
# Exit codes (so callers can branch): 0 CONTRIBUTES · 1 MERGED · 2 ABSORBED ·
# 4 UNKNOWN. The verdict word is also printed to stdout.

branch_contribution() {
    local repo="$1" branch="$2" base="${3:-origin/main}"
    if [[ -z "$repo" || -z "$branch" ]]; then
        echo "usage: branch_contribution <repo> <branch> [base=origin/main]" >&2
        return 4
    fi
    git -C "$repo" rev-parse --verify --quiet "$branch^{commit}" >/dev/null 2>&1 || {
        echo "UNKNOWN (branch '$branch' not found in $repo)"; return 4; }
    git -C "$repo" rev-parse --verify --quiet "$base^{commit}" >/dev/null 2>&1 || {
        echo "UNKNOWN (base '$base' not found in $repo — fetch first)"; return 4; }

    # Fully merged: branch tip is reachable from base. Certain, squash-proof-safe.
    if git -C "$repo" merge-base --is-ancestor "$branch" "$base" 2>/dev/null; then
        echo "MERGED (branch tip is an ancestor of $base — fully contained)"
        return 1
    fi

    # is-ancestor was false, so there is at least one commit ahead of base.
    local ahead
    ahead=$(git -C "$repo" rev-list --count "$base..$branch" 2>/dev/null)

    # Patch-id comparison: `git cherry` marks each ahead-commit `-` (an equivalent
    # patch is already in base) or `+` (no equivalent found).
    local plus
    plus=$(git -C "$repo" cherry "$base" "$branch" 2>/dev/null | grep -c '^+' || true)
    if [[ "${plus:-0}" -eq 0 ]]; then
        echo "ABSORBED ($ahead commit(s) ahead, but every patch is already in $base)"
        return 2
    fi

    echo "CONTRIBUTES ($plus of $ahead ahead-commit(s) not in $base by patch-id;" \
         "if this was SQUASH-merged the content is in $base under a new patch-id" \
         "— verify the PR before deleting)"
    return 0
}

# --- self-test: validate the instrument against known ground truth (D2) --------
_bc_selftest() {
    local tmp verdict rc fails=0
    tmp="$(mktemp -d)"
    _bc_mkrepo() {  # <dir> ; leaves a repo with main + feature branches set up
        local d="$1"
        git init -q -b main "$d"
        git -C "$d" config user.email t@t; git -C "$d" config user.name t
        echo base > "$d/f"; git -C "$d" add f; git -C "$d" commit -qm base
    }

    # 1) CONTRIBUTES: a unique commit on feature.
    local r="$tmp/contributes"; _bc_mkrepo "$r"
    git -C "$r" checkout -q -b feat; echo work > "$r/g"; git -C "$r" add g; git -C "$r" commit -qm work
    verdict="$(branch_contribution "$r" feat main)"; rc=$?
    [[ $rc -eq 0 && "$verdict" == CONTRIBUTES* ]] || { echo "FAIL contributes: rc=$rc $verdict"; ((fails++)); }

    # 2) MERGED: feature fast-forward-merged into main (tip is ancestor).
    r="$tmp/merged"; _bc_mkrepo "$r"
    git -C "$r" checkout -q -b feat; echo work > "$r/g"; git -C "$r" add g; git -C "$r" commit -qm work
    git -C "$r" checkout -q main; git -C "$r" merge -q --no-ff -m merge feat
    verdict="$(branch_contribution "$r" feat main)"; rc=$?
    [[ $rc -eq 1 && "$verdict" == MERGED* ]] || { echo "FAIL merged: rc=$rc $verdict"; ((fails++)); }

    # 3) ABSORBED: feature's commit cherry-picked onto main. main must diverge
    # FIRST, else the cherry-pick reproduces feat's exact sha (same parent/tree/
    # author) and feat becomes a true ancestor → MERGED, not the patch-id path.
    r="$tmp/absorbed"; _bc_mkrepo "$r"
    git -C "$r" checkout -q -b feat; echo work > "$r/g"; git -C "$r" add g; git -C "$r" commit -qm work
    local sha; sha="$(git -C "$r" rev-parse feat)"
    git -C "$r" checkout -q main
    echo diverge > "$r/d"; git -C "$r" add d; git -C "$r" commit -qm diverge  # main moves first
    git -C "$r" cherry-pick "$sha" >/dev/null 2>&1                             # new sha, same patch
    verdict="$(branch_contribution "$r" feat main)"; rc=$?
    [[ $rc -eq 2 && "$verdict" == ABSORBED* ]] || { echo "FAIL absorbed: rc=$rc $verdict"; ((fails++)); }

    # 4) SQUASH (the known limitation): feat's TWO commits squashed onto main as
    # ONE commit — whose combined patch-id matches NEITHER original, so git
    # 2.34.1 cannot tell it from a real contribution. The tool must honestly say
    # CONTRIBUTES (with the squash caveat) — pinned so the limitation is a
    # documented, tested fact, not a surprise.
    r="$tmp/squash"; _bc_mkrepo "$r"
    git -C "$r" checkout -q -b feat
    echo one > "$r/g"; git -C "$r" add g; git -C "$r" commit -qm work1
    echo two > "$r/h"; git -C "$r" add h; git -C "$r" commit -qm work2
    git -C "$r" checkout -q main
    git -C "$r" checkout -q feat -- g h; git -C "$r" add g h  # both files, one commit
    git -C "$r" commit -qm "squash of feat (2 commits -> 1)"
    verdict="$(branch_contribution "$r" feat main)"; rc=$?
    [[ $rc -eq 0 && "$verdict" == CONTRIBUTES* ]] || { echo "FAIL squash-limitation: rc=$rc $verdict"; ((fails++)); }

    # 5) UNKNOWN: missing branch.
    r="$tmp/unknown"; _bc_mkrepo "$r"
    verdict="$(branch_contribution "$r" nope main)"; rc=$?
    [[ $rc -eq 4 && "$verdict" == UNKNOWN* ]] || { echo "FAIL unknown: rc=$rc $verdict"; ((fails++)); }

    rm -rf "$tmp"
    if [[ $fails -eq 0 ]]; then echo "branch_contribution self-test: all 5 verdicts correct"; return 0
    else echo "branch_contribution self-test: $fails failure(s)"; return 1; fi
}

# CLI: `branch_contribution.sh <repo> <branch> [base]` or `--self-test`.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [[ "$1" == "--self-test" ]]; then _bc_selftest; exit $?; fi
    branch_contribution "$@"; exit $?
fi
