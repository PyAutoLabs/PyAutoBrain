#!/usr/bin/env bash
#
# clean_slate.sh — start-of-day reset for the PyAuto workspace.
#
# Clears generated test/run cruft and restores shipped datasets to pristine,
# WITHOUT touching source code or untracked real work. Per repo it:
#   1. restores tracked files under any dataset/ dir that a run modified in place
#      — the shipped datasets (cosmos_web_ring, simple, …) go back to their
#      committed state; they are never deleted.
#   1b. removes REGENERABLE datasets from the workspace/tutorial repos only
#      (see DATASET_REPOS), reports orphans, prunes emptied dataset dirs, and
#      warns about oversized committed datasets.
#   2. clears every output/ and scratch/ directory (model fits, scratch space).
#   3. removes generated test_report.md files, then untracked .ipynb_checkpoints/
#      directories repo-wide.
#   4. removes ignored, fully-untracked top-level *.egg-info/ and build/
#      packaging directories from the managed library repos.
#   5. runs `git gc --auto` per repo to compact the object store.
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
# __The write-site rule__
#
# A dataset is removed only when a script in the SAME repo demonstrably WRITES
# it — a name mention is never enough. bin/dataset_provenance.py parses every
# scripts/**/*.py with `ast` and, in source order, tracks which dataset path each
# variable currently holds and whether that variable reaches an output call
# (output_to_fits, fits_imaging, json.dump, open(..., "w"), a helper whose body
# writes the parameter, …). That order sensitivity is the point:
# scripts/interferometer/start_here.py binds `dataset_path` to the real sdp81
# data (which it only reads), then rebinds it to simulated_lens (which it
# writes) — a grep for the dataset name cannot tell those apart, and the old
# name-literal rule missed every dataset written by a start_here.py (#167).
#
# Three verdicts come back per candidate:
#   REGENERABLE  positive write evidence, no network — deleted.
#   DOWNLOADED   its binding script also fetches over the network — kept
#                silently; this is real data cached rather than redistributed.
#   ORPHAN       no writer found — kept and REPORTED, so a human can look.
# Deletion requires positive evidence; every uncertainty lands on ORPHAN.
#
# Workspace root: PYAUTO_ROOT (default ~/Code/PyAutoLabs).
# Preview without changing anything:  DRY_RUN=1 clean_slate.sh
# Packaging products only:            clean_slate.sh --packaging

set -u
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
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

# Print every untracked dataset/<type>/<name> DIRECTORY worth judging. Expands
# git-clean's collapsed entries down to dataset/<type>/<name> granularity so a
# wholly-untracked dataset/ tree is still judged per dataset. Provenance itself
# is decided by dataset_provenance.py — this only produces the candidate list.
dataset_candidates() {
    local repo="$1" path depth child
    local -a queue found

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
        found+=("$path")
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

        # 1b. Classify untracked datasets by write site, remove the regenerable
        # ones, report orphans, and flag oversized committed ones.
        if is_dataset_repo "$repo"; then
            mapfile -t candidates < <(dataset_candidates "$repo")
            if [ "${#candidates[@]}" -gt 0 ]; then
                errfile=$(mktemp)
                verdicts=$(python3 "$SCRIPT_DIR/dataset_provenance.py" \
                    --repo "$repo" "${candidates[@]}" 2>"$errfile")
                status=$?
                # No fallback: guessing provenance is exactly what this replaced.
                if [ "$status" -ne 0 ]; then
                    cat "$errfile" >&2
                    rm -f "$errfile"
                    echo "clean_slate: dataset_provenance.py failed for $repo (exit $status)" >&2
                    exit 1
                fi
                [ -s "$errfile" ] && cat "$errfile" >&2
                rm -f "$errfile"

                nsim=0; simkb=0
                while read -r verdict rel; do
                    [ -n "$rel" ] || continue
                    case "$verdict" in
                        REGENERABLE)
                            nsim=$((nsim + 1))
                            kb=$(du -sk "$repo/$rel" 2>/dev/null | cut -f1)
                            simkb=$((simkb + ${kb:-0}))
                            [ "$DRY_RUN" = 1 ] || rm -rf "${repo:?}/${rel:?}"
                            ;;
                        ORPHAN)
                            # Never deleted — surfaced so a human can decide
                            # whether it is real data or forgotten cruft.
                            warn "orphan dataset (no writer): $rel ($(du -sh "$repo/$rel" 2>/dev/null | cut -f1))"
                            ;;
                        DOWNLOADED) ;;  # real data, cached not redistributed — keep, silently
                    esac
                done <<<"$verdicts"
                [ "$nsim" -gt 0 ] && show "remove $nsim simulated dataset(s) ($((simkb / 1024)) MB)"
            fi

            # Prune directories the sweep just emptied (and any that were
            # already empty). An empty directory is never tracked by git, so
            # this can never touch committed content.
            nempty=$(find "$repo/dataset" -mindepth 1 -type d -empty 2>/dev/null | wc -l)
            if [ "$nempty" -gt 0 ]; then
                show "remove $nempty empty dataset director$([ "$nempty" -eq 1 ] && echo y || echo ies)"
                [ "$DRY_RUN" = 1 ] || find "$repo/dataset" -mindepth 1 -type d -empty -delete 2>/dev/null
            fi

            # Bloat warning aggregated per dataset DIRECTORY, not per file: a
            # dataset is many .fits files and one line per file buries the
            # signal. Tracked bytes only — untracked cruft is not repo bloat.
            while IFS=$'\t' read -r dir kb; do
                warn "WARNING: committed dataset $dir is $((kb / 1024)) MB (>$((DATASET_WARN_KB / 1024)) MB)"
            done < <(git -C "$repo" ls-files -z -- 'dataset/*' 2>/dev/null \
                | (cd "$repo" && xargs -0 -r du -k --apparent-size --) 2>/dev/null \
                | awk -F'\t' -v warn="$DATASET_WARN_KB" '
                    NF == 2 {
                        n = split($2, part, "/")
                        dir = (n >= 3) ? part[1] "/" part[2] "/" part[3] : $2
                        total[dir] += $1
                    }
                    END { for (d in total) if (total[d] > warn) printf "%s\t%d\n", d, total[d] }' \
                | sort)
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

        # 3b. Remove untracked .ipynb_checkpoints/ — Jupyter autosave copies of
        # notebooks, which go stale the moment the real notebook is regenerated.
        # __pycache__ is DELIBERATELY left alone: it is an import-speed cache
        # that costs seconds of every subsequent run to rebuild.
        while IFS= read -r -d '' d; do
            rel="${d#"$repo"/}"
            n=$(git -C "$repo" clean -ndx -- "$rel" 2>/dev/null | wc -l)
            [ "$n" -eq 0 ] && continue
            show "remove $rel/"
            [ "$DRY_RUN" = 1 ] || git -C "$repo" clean -qfdx -- "$rel"
        done < <(find "$repo" -type d -name .ipynb_checkpoints -not -path '*/.git/*' -print0 2>/dev/null)
    fi

    # 4. Remove ignored, fully-untracked packaging products at managed library
    # roots. Keep assistant/workspace build products outside this narrow scope.
    # Never match nested domain directories named build, and never clean a
    # candidate containing tracked files even though git clean would retain them.
    if is_packaging_repo "$repo"; then
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
    fi

    # 5. Compact the object store. `--auto` makes this a no-op until git's own
    # loose-object threshold is crossed, so it is cheap to run every morning.
    # Housekeeping must never break the sweep: warn and carry on.
    if [ "$DRY_RUN" != 1 ]; then
        git -C "$repo" gc --auto --quiet 2>/dev/null || warn "WARNING: git gc failed"
    fi
done

echo
if [ "$DRY_RUN" = 1 ]; then
    echo "Dry run only — nothing changed. Run without DRY_RUN to apply."
else
    echo "Clean slate done."
fi
