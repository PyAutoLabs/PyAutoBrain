#!/usr/bin/env bash
# ensure_workspace_labels.sh — idempotently assert the canonical `pending-release`
# label on every PyAutoLabs workspace, _test, HowTo, euclid, and library repo.
#
# Usage: bash PyAutoBrain/bin/ensure_workspace_labels.sh
#
# For each repo: probes `gh api repos/$ORG/$REPO/labels/pending-release`.
#   - 404                                 → POST creates it (canonical color/desc)
#   - exists with drifted color or desc   → PATCH updates it
#   - already canonical                   → no-op
#
# Canonical color: 0E8A16   (matches autofit_workspace and autogalaxy_workspace
# pre-this-script — chosen because two repos already had it, minimising churn).
# Canonical description: "PR queued for the next release build".
#
# Exits 0 on success, 1 if any API call fails.
#
# Repos with non-PyAutoLabs orgs:
#   - Jammy2211/euclid_strong_lens_modeling_pipeline
#   - rhayes777/PyAutoConf, rhayes777/PyAutoFit
# All others are under PyAutoLabs/.

set -euo pipefail

CANONICAL_COLOR="0E8A16"
CANONICAL_DESC="PR queued for the next release build"
LABEL_NAME="pending-release"

# Owner/name pairs must match PyAutoMind/repos.yaml (the body map);
# `python3 PyAutoMind/scripts/repos_sync.py --check` flags drift.
REPOS=(
    PyAutoLabs/autolens_workspace
    PyAutoLabs/autogalaxy_workspace
    PyAutoLabs/autofit_workspace
    PyAutoLabs/HowToLens
    PyAutoLabs/HowToGalaxy
    PyAutoLabs/HowToFit
    PyAutoLabs/autolens_workspace_test
    PyAutoLabs/autogalaxy_workspace_test
    PyAutoLabs/autofit_workspace_test
    PyAutoLabs/euclid_strong_lens_modeling_pipeline
    PyAutoLabs/PyAutoArray
    PyAutoLabs/PyAutoGalaxy
    PyAutoLabs/PyAutoLens
    PyAutoLabs/PyAutoNerves
    PyAutoLabs/PyAutoFit
    PyAutoLabs/PyAutoCTI
    PyAutoLabs/autocti_workspace
    PyAutoLabs/autocti_workspace_test
)

if ! command -v gh >/dev/null 2>&1; then
    echo "ensure_workspace_labels: 'gh' CLI not installed; skipping label sweep." >&2
    exit 0
fi

failed=0

for repo in "${REPOS[@]}"; do
    api_path="repos/$repo/labels/$LABEL_NAME"
    # NOTE: on 404, `gh api --jq` exits non-zero AND prints "null|" (the jq
    # filter runs against the error body where .color and .description are null).
    # We branch on exit code, not stdout, so the 404 is correctly routed to POST.
    if current=$(gh api "$api_path" --jq '"\(.color)|\(.description // "")"' 2>/dev/null); then
        color="${current%%|*}"
        desc="${current#*|}"

        if [ "$color" = "$CANONICAL_COLOR" ] && [ "$desc" = "$CANONICAL_DESC" ]; then
            printf "  %-55s ok\n" "$repo"
            continue
        fi

        if gh api -X PATCH "$api_path" \
                -f "color=$CANONICAL_COLOR" \
                -f "description=$CANONICAL_DESC" >/dev/null 2>&1; then
            printf "  %-55s PATCHED (was: %s | %s)\n" "$repo" "$color" "$desc"
        else
            printf "  %-55s FAILED (could not patch label)\n" "$repo" >&2
            failed=1
        fi
    else
        if gh api -X POST "repos/$repo/labels" \
                -f "name=$LABEL_NAME" \
                -f "color=$CANONICAL_COLOR" \
                -f "description=$CANONICAL_DESC" >/dev/null 2>&1; then
            printf "  %-55s CREATED\n" "$repo"
        else
            printf "  %-55s FAILED (could not create label)\n" "$repo" >&2
            failed=1
        fi
    fi
done

if [ "$failed" -ne 0 ]; then
    exit 1
fi
