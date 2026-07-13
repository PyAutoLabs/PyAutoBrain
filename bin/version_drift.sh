#!/usr/bin/env bash
#
# version_drift.sh — flag version-stamp inconsistency across the PyAuto stack.
#
# Reference = the latest PyAutoLens release tag (the release anchor). Each repo's
# live version stamp is compared against it. Reads local files when the workspace
# is present ($PYAUTO_ROOT), otherwise fetches them via the `gh` contents API —
# so it runs on the CLI, on mobile Claude Code chat, and in Codex alike.

set -u
command -v gh >/dev/null 2>&1 || { echo "gh not found — cannot resolve versions" >&2; exit 1; }
ROOT="${PYAUTO_ROOT:-$HOME/Code/PyAutoLabs}"
OWNER=PyAutoLabs
VERPAT='[0-9]{4}\.[0-9]+\.[0-9]+\.[0-9]+'

ref=$(gh api "repos/$OWNER/PyAutoLens/releases/latest" -q .tag_name 2>/dev/null)
[ -z "$ref" ] && { echo "could not resolve reference version (PyAutoLens latest release)" >&2; exit 1; }
echo "reference (latest PyAutoLens release): $ref"
echo

# repo:path — the live version-stamp locations
STAMPS=(
  "PyAutoArray:autoarray/__init__.py"
  "PyAutoConf:autoconf/__init__.py"
  "PyAutoFit:autofit/__init__.py"
  "PyAutoGalaxy:autogalaxy/__init__.py"
  "PyAutoLens:autolens/__init__.py"
  "autofit_workspace:version.txt"
  "autogalaxy_workspace:version.txt"
  "autolens_workspace:version.txt"
)

drift=0
for s in "${STAMPS[@]}"; do
    repo="${s%%:*}"; path="${s#*:}"
    if [ -f "$ROOT/$repo/$path" ]; then
        v=$(grep -oE "$VERPAT" "$ROOT/$repo/$path" 2>/dev/null | head -1)
    else
        v=$(gh api "repos/$OWNER/$repo/contents/$path" -q '.content' 2>/dev/null \
            | base64 -d 2>/dev/null | grep -oE "$VERPAT" | head -1)
    fi
    [ -z "${v:-}" ] && v="?"
    if [ "$v" = "$ref" ]; then
        printf '  ✓ %-24s %s\n' "$repo" "$v"
    else
        printf '  ✗ %-24s %s (≠ %s)\n' "$repo" "$v" "$ref"
        drift=$((drift+1))
    fi
done

echo
if [ "$drift" -eq 0 ]; then
    echo "Version pins: consistent at $ref."
else
    echo "Version drift: $drift stamp(s) off $ref."
fi
