#!/usr/bin/env bash
# ensure_workspace_labels.sh — idempotently assert the canonical `pending-release`
# label on every PUBLISHED library repo (the only repos whose PRs carry it).
#
# The published set is defined once, as PUBLISHED_REPOS in
# PyAutoMind/scripts/lifecycle.py (it mirrors the PyPI `release` job matrix of
# PyAutoHands/.github/workflows/release.yml); REPOS below must equal it.
# Workspace, _test, HowTo, euclid, CTI and organ repos used to be listed here,
# but nothing ever publishes them, so no release could clear the label there:
# 1500+ merged PRs accumulated it before 2026-10-07. Their existing label
# definitions are harmless and left alone — this script just stops asserting them.
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
# Every repo below is under PyAutoLabs/ — the pre-migration rhayes777/ and
# Jammy2211/ homes are gone. Owners come from the body map's `github:` field
# (PyAutoMind/repos.yaml); never hardcode a legacy owner default.

set -euo pipefail

CANONICAL_COLOR="0E8A16"
CANONICAL_DESC="PR queued for the next release build"
LABEL_NAME="pending-release"

# Owner/name pairs must match PyAutoMind/repos.yaml (the body map);
# `python3 PyAutoMind/scripts/repos_sync.py --check` flags drift.
REPOS=(
    PyAutoLabs/PyAutoNerves
    PyAutoLabs/PyAutoFit
    PyAutoLabs/PyAutoArray
    PyAutoLabs/PyAutoGalaxy
    PyAutoLabs/PyAutoLens
)

. "$(dirname "${BASH_SOURCE[0]}")/_gh.sh"
if ! have_gh; then
    echo "ensure_workspace_labels: skipping label sweep — $(gh_unavailable_reason)." >&2
    echo "  Run it where gh is available, or apply the labels via the MCP surface" >&2
    echo "  (PyAutoBrain/skills/GITHUB_ACCESS.md)." >&2
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
