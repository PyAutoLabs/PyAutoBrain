#!/usr/bin/env bash
#
# clean_slate.sh — start-of-day reset for the PyAuto workspace.
#
# Clears generated test/run cruft and restores shipped datasets to pristine,
# WITHOUT touching source code or untracked real work. Per repo it:
#   1. restores tracked files under any dataset/ dir that a run modified in place
#      — the shipped datasets (cosmos_web_ring, simple, …) go back to their
#      committed state; they are never deleted.
#   1b. removes AUTO-SIMULATED datasets from the workspace/tutorial repos only
#      (see DATASET_REPOS), and warns about oversized committed datasets.
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
# __Why datasets need provenance, not just "is it committed?"__
#
# Every workspace ignores dataset/ wholesale and force-adds the real datasets
# back, so "untracked" does NOT mean "regenerable": some real datasets are
# deliberately never committed because they are DOWNLOADED at runtime rather
# than redistributed (autolens_workspace scripts/cluster/lenstool/data.py fetches
# SMACS J0723 from the GPL-licensed Mahler et al. repo + the STScI RELICS
# archive; dataset/cluster/a2744/data.fits is a hips2fits cutout). Deleting
# those costs a large re-download, and committing them would be a redistribution
# problem. No intrinsic marker separates them from simulated data either — a
# README or a tracer.json sits in both kinds.
#
# So a dataset is removed only when a simulator script in the SAME repo demonstrably
# writes it: both its dataset type and its name appear as string literals in one
# scripts/**/simulator*.py or scripts/**/simulators/*.py. Anything with no such
# provenance is kept. The rule therefore errs toward keeping — datasets written by
# start_here.py-style scripts survive, which is the safe direction.
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
# Repos whose dataset/ dirs are auto-simulated by their own simulator scripts.
# Deliberately excludes autolens_profiling and autolens_jax_joss, whose dataset/
# dirs hold real instrument data (alma/sma/hst inputs, JWST cosmos_web_ring).
DATASET_REPOS=(autolens_workspace autogalaxy_workspace autofit_workspace \
               autocti_workspace HowToLens HowToGalaxy HowToFit)
# Committed dataset files above this size are flagged as repo bloat.
DATASET_WARN_KB=5120
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

is_dataset_repo() {
    local candidate
    for candidate in "${DATASET_REPOS[@]}"; do
        [ "$candidate" = "$1" ] && return 0
    done
    return 1
}

# Print each untracked path under dataset/ that a simulator script in this repo
# writes. Expands git-clean's collapsed entries down to dataset/<type>/<name>
# granularity so a wholly-untracked dataset/ tree is still judged per dataset.
simulated_datasets() {
    local repo="$1" path depth child type name matched
    local -a sims queue found
    mapfile -t sims < <(find "$repo/scripts" -type f -name '*.py' \
        \( -name 'simulator*' -o -path '*/simulators/*' \) 2>/dev/null)
    [ "${#sims[@]}" -eq 0 ] && return 0

    queue=()
    while IFS= read -r path; do
        queue+=("${path#Would remove }")
    done < <(git -C "$repo" clean -ndx -- dataset 2>/dev/null)

    found=()
    while [ "${#queue[@]}" -gt 0 ]; do
        path="${queue[0]%/}"; queue=("${queue[@]:1}")
        depth=$(awk -F/ '{print NF}' <<<"$path")
        if [ -d "$repo/$path" ] && [ "$depth" -lt 3 ]; then
            while IFS= read -r child; do
                queue+=("${child#"$repo"/}")
            done < <(find "$repo/$path" -mindepth 1 -maxdepth 1 2>/dev/null)
            continue
        fi
        # A dataset is a DIRECTORY. Loose untracked files are never candidates:
        # they are usually byproducts sitting inside a committed real dataset
        # (dataset/cluster/a2744/data.fits — a downloaded HST cutout re-ignored
        # by .gitignore; double_einstein_ring/*.png), and their generic names
        # ("data.fits") would match almost any simulator script.
        [ -d "$repo/$path" ] || continue
        # Defence in depth: never touch a directory holding a tracked file.
        # (Do NOT extend this to the parent — a type directory like
        # dataset/imaging/ legitimately holds committed datasets alongside
        # simulated ones, so a parent test would protect everything.)
        [ -z "$(git -C "$repo" ls-files -- "$path" 2>/dev/null)" ] || continue
        type=$(awk -F/ '{print $2}' <<<"$path")
        name="${path##*/}"
        matched=""
        while IFS= read -r hit; do
            grep -qF "\"$type\"" "$hit" 2>/dev/null && { matched=1; break; }
        done < <(grep -lF "\"$name\"" "${sims[@]}" 2>/dev/null)
        [ -n "$matched" ] && found+=("$path")
    done
    [ "${#found[@]}" -gt 0 ] && printf '%s\n' "${found[@]}"
    return 0
}

for dir in */; do
    repo="${dir%/}"
    [ -d "$repo/.git" ] || continue
    header=""

    show() { [ -z "$header" ] && { echo "=== $repo ==="; header=1; }; echo "  ${tag}$*"; }
    # Observations, not pending actions — never carry the [dry-run] tag.
    warn() { [ -z "$header" ] && { echo "=== $repo ==="; header=1; }; echo "  $*"; }

    if [ "$SCOPE" = all ]; then
        # 1. Restore shipped datasets modified in place.
        mapfile -d '' -t moddata < <(git -C "$repo" ls-files -z -m -- 'dataset/*' '*/dataset/*' 2>/dev/null)
        if [ "${#moddata[@]}" -gt 0 ]; then
            show "restore ${#moddata[@]} modified dataset file(s)"
            [ "$DRY_RUN" = 1 ] || printf '%s\0' "${moddata[@]}" | xargs -0 -r git -C "$repo" checkout --
        fi

        # 1b. Remove auto-simulated datasets, and flag oversized committed ones.
        if is_dataset_repo "$repo"; then
            nsim=0; simkb=0
            while IFS= read -r rel; do
                [ -n "$rel" ] || continue
                nsim=$((nsim + 1))
                kb=$(du -sk "$repo/$rel" 2>/dev/null | cut -f1)
                simkb=$((simkb + ${kb:-0}))
                [ "$DRY_RUN" = 1 ] || rm -rf "${repo:?}/${rel:?}"
            done < <(simulated_datasets "$repo")
            [ "$nsim" -gt 0 ] && show "remove $nsim simulated dataset(s) ($((simkb / 1024)) MB)"

            while IFS= read -r -d '' f; do
                kb=$(du -sk "$repo/$f" 2>/dev/null | cut -f1)
                [ "${kb:-0}" -gt "$DATASET_WARN_KB" ] || continue
                warn "WARNING: committed dataset $f is $((kb / 1024)) MB (>$((DATASET_WARN_KB / 1024)) MB)"
            done < <(git -C "$repo" ls-files -z -- 'dataset/*' 2>/dev/null)
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
