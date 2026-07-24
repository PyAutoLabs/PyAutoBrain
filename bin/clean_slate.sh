#!/usr/bin/env bash
#
# clean_slate.sh — start-of-day reset for the PyAuto workspace.
#
# Clears generated test/run cruft and restores shipped datasets to pristine,
# WITHOUT touching source code or untracked real work. Per repo it:
#   1. restores tracked files under any dataset/ dir that a run modified in place
#      — the shipped datasets (cosmos_web_ring, simple, …) go back to their
#      committed state; they are never deleted.
#   2. clears every output/ and scratch/ directory (model fits, scratch space).
#   3. removes generated test_report.md files.
#   4. removes ignored, fully-untracked top-level *.egg-info/ and build/
#      packaging directories from the managed library repos.
#
# It is git-aware and conservative:
#   - it never deletes a tracked file (except reverting in-place dataset edits);
#   - outside output/ and scratch/, it removes only the exact ignored top-level
#     packaging names above, and skips a candidate if it contains tracked files.
#
# Workspace root: PYAUTO_ROOT (default ~/Code/PyAutoLabs).
# Preview without changing anything:  DRY_RUN=1 clean_slate.sh
# Packaging products only:            clean_slate.sh --packaging

set -u
ROOT="${PYAUTO_ROOT:-$HOME/Code/PyAutoLabs}"
cd "$ROOT" || { echo "workspace root not found: $ROOT" >&2; exit 1; }
DRY_RUN="${DRY_RUN:-0}"
tag=""; [ "$DRY_RUN" = 1 ] && tag="[dry-run] "
SCOPE="all"
PACKAGING_REPOS=(PyAutoNerves PyAutoFit PyAutoArray PyAutoGalaxy PyAutoLens)
case "${1:-}" in
    --packaging) SCOPE="packaging" ;;
    "") ;;
    *) echo "usage: clean_slate.sh [--packaging]" >&2; exit 2 ;;
esac

is_packaging_repo() {
    local candidate
    for candidate in "${PACKAGING_REPOS[@]}"; do
        [ "$candidate" = "$1" ] && return 0
    done
    return 1
}

for dir in */; do
    repo="${dir%/}"
    [ -d "$repo/.git" ] || continue
    header=""

    show() { [ -z "$header" ] && { echo "=== $repo ==="; header=1; }; echo "  ${tag}$*"; }

    if [ "$SCOPE" = all ]; then
        # 1. Restore shipped datasets modified in place.
        mapfile -d '' -t moddata < <(git -C "$repo" ls-files -z -m -- 'dataset/*' '*/dataset/*' 2>/dev/null)
        if [ "${#moddata[@]}" -gt 0 ]; then
            show "restore ${#moddata[@]} modified dataset file(s)"
            [ "$DRY_RUN" = 1 ] || printf '%s\0' "${moddata[@]}" | xargs -0 -r git -C "$repo" checkout --
        fi

        # 2. Clear output/ and scratch/ dirs (untracked + ignored inside them; tracked kept).
        while IFS= read -r -d '' d; do
            rel="${d#"$repo"/}"
            n=$(git -C "$repo" clean -ndx -- "$rel" 2>/dev/null | wc -l)
            [ "$n" -eq 0 ] && continue
            show "clear $rel/ ($n entr$([ "$n" -eq 1 ] && echo y || echo ies))"
            [ "$DRY_RUN" = 1 ] || git -C "$repo" clean -qfdx -- "$rel"
        done < <(find "$repo" -type d \( -name output -o -name scratch \) -not -path '*/.git/*' -print0 2>/dev/null)

        # 3. Remove generated (untracked) test_report.md files.
        while IFS= read -r -d '' f; do
            rel="${f#"$repo"/}"
            git -C "$repo" ls-files --error-unmatch -- "$rel" >/dev/null 2>&1 && continue  # tracked -> keep
            show "remove $rel"
            [ "$DRY_RUN" = 1 ] || rm -f "$f"
        done < <(find "$repo" -maxdepth 2 -type f -name test_report.md -not -path '*/.git/*' -print0 2>/dev/null)
    fi

    # 4. Remove ignored, fully-untracked packaging products at managed library
    # roots. Keep assistant/workspace build products outside this narrow scope.
    # Never match nested domain directories named build, and never clean a
    # candidate containing tracked files even though git clean would retain them.
    is_packaging_repo "$repo" || continue
    while IFS= read -r -d '' d; do
        rel="${d#"$repo"/}"
        git -C "$repo" check-ignore -q -- "$rel" 2>/dev/null || continue
        [ -z "$(git -C "$repo" ls-files -- "$rel" 2>/dev/null)" ] || continue
        n=$(git -C "$repo" clean -ndx -- "$rel" 2>/dev/null | wc -l)
        [ "$n" -eq 0 ] && continue
        show "remove packaging directory $rel/"
        [ "$DRY_RUN" = 1 ] || git -C "$repo" clean -qfdx -- "$rel"
    done < <(find "$repo" -mindepth 1 -maxdepth 1 -type d \
        \( -name '*.egg-info' -o -name build \) -print0 2>/dev/null)
done

echo
if [ "$DRY_RUN" = 1 ]; then
    echo "Dry run only — nothing changed. Run without DRY_RUN to apply."
else
    echo "Clean slate done."
fi
