#!/usr/bin/env bash
#
# pull_all_main.sh — checkout the default branch (main/master) in every git repo
# in the PyAuto workspace and fast-forward pull it from origin.
#
# Regenerated dataset/ artifacts (tracked .fits/.png/.json rewritten by running
# tutorials/scripts locally) are discarded so they don't block the pull. Any
# repo that still has tracked local modifications after that — i.e. real work —
# is skipped and left completely untouched. Untracked files never block a pull.
#
# Workspace root: PYAUTO_ROOT (default ~/Code/PyAutoLabs) — override to point at
# a different checkout, mirroring bin/pyauto-brain's sibling resolution.

set -u

ROOT="${PYAUTO_ROOT:-$HOME/Code/PyAutoLabs}"
cd "$ROOT" || { echo "workspace root not found: $ROOT" >&2; exit 1; }

for dir in */; do
    repo="${dir%/}"
    [ -d "$repo/.git" ] || continue

    printf '\n=== %s ===\n' "$repo"

    # Discard regenerated dataset/ noise (tracked modifications only) so it
    # doesn't block the checkout/pull. Untracked files in dataset/ are left be.
    if [ -d "$repo/dataset" ] && \
       [ -n "$(git -C "$repo" status --porcelain --untracked-files=no -- dataset/)" ]; then
        echo "  discarding regenerated dataset/ changes"
        git -C "$repo" checkout -- dataset/
    fi

    # If tracked modifications remain, that's real work -> skip, untouched.
    if [ -n "$(git -C "$repo" status --porcelain --untracked-files=no)" ]; then
        echo "  SKIP: uncommitted work (not dataset noise)"
        continue
    fi

    # Pick the default branch: prefer main, fall back to master.
    if git -C "$repo" show-ref --verify --quiet refs/heads/main; then
        branch=main
    elif git -C "$repo" show-ref --verify --quiet refs/heads/master; then
        branch=master
    else
        echo "  SKIP: no main/master branch"
        continue
    fi

    git -C "$repo" checkout "$branch" || { echo "  checkout failed"; continue; }
    git -C "$repo" pull --ff-only origin "$branch" || echo "  pull failed"
done

echo
echo "Done."
