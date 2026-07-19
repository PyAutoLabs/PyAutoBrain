#!/usr/bin/env bash
#
# version_drift.sh — flag version-stamp INCONSISTENCY across the coupled PyAuto
# stack.
#
# What "drift" means here (reframed 2026-07): the release design deliberately
# FREEZES the committed source version stamp. release.yml stamps the wheel at
# build time and does NOT commit the bump back — daily "Update version to X"
# commits to every library main were the noise engine behind the June/July 2026
# accidental-release cascade (PyAutoBuild#118 / #120). pip users get the version
# from the stamped wheel; source checkouts stay frozen and uniform.
#
# So the meaningful invariant is no longer "source stamp == latest release tag"
# (that would report drift after every release, forever) but "every coupled repo
# carries the SAME stamp as its siblings". This script flags a repo whose stamp
# is out of step with the consensus of the set. The latest PyAutoLens release
# tag is shown for context only — a consensus that trails the tag is the
# expected freeze, not drift.
#
# Reads local files when the workspace is present ($PYAUTO_ROOT); otherwise
# fetches them via the `gh` contents API. `gh` is optional — without it the
# reference tag is skipped and the consensus check runs on the local stamps.

set -u
ROOT="${PYAUTO_ROOT:-$HOME/Code/PyAutoLabs}"
OWNER=PyAutoLabs
VERPAT='[0-9]{4}\.[0-9]+\.[0-9]+\.[0-9]+'

have_gh=0
command -v gh >/dev/null 2>&1 && have_gh=1

ref=""
[ "$have_gh" -eq 1 ] && ref=$(gh api "repos/$OWNER/PyAutoLens/releases/latest" -q .tag_name 2>/dev/null)
if [ -n "$ref" ]; then
    echo "reference (latest PyAutoLens release, for context): $ref"
else
    echo "reference (latest PyAutoLens release): unavailable (no gh / no release)"
fi
echo

# repo:path — the coupled release-train stamps (libraries + user workspaces).
# PyAutoCTI is intentionally excluded: it is not on the coupled train and
# carries its own version line.
STAMPS=(
  "PyAutoNerves:autonerves/__init__.py"
  "PyAutoArray:autoarray/__init__.py"
  "PyAutoFit:autofit/__init__.py"
  "PyAutoGalaxy:autogalaxy/__init__.py"
  "PyAutoLens:autolens/__init__.py"
  "autofit_workspace:version.txt"
  "autogalaxy_workspace:version.txt"
  "autolens_workspace:version.txt"
)

repos=()
vers=()
for s in "${STAMPS[@]}"; do
    repo="${s%%:*}"; path="${s#*:}"
    if [ -f "$ROOT/$repo/$path" ]; then
        v=$(grep -oE "$VERPAT" "$ROOT/$repo/$path" 2>/dev/null | head -1)
    elif [ "$have_gh" -eq 1 ]; then
        v=$(gh api "repos/$OWNER/$repo/contents/$path" -q '.content' 2>/dev/null \
            | base64 -d 2>/dev/null | grep -oE "$VERPAT" | head -1)
    else
        v=""
    fi
    [ -z "${v:-}" ] && v="?"
    repos+=("$repo")
    vers+=("$v")
done

# Consensus = the most common stamp among the resolved (non-"?") values.
consensus=$(printf '%s\n' "${vers[@]}" | grep -v '^?$' | sort | uniq -c | sort -rn | head -1 | awk '{print $2}')

drift=0
unknown=0
for i in "${!repos[@]}"; do
    repo="${repos[$i]}"; v="${vers[$i]}"
    if [ "$v" = "?" ]; then
        printf '  ? %-24s (stamp unresolved)\n' "$repo"
        unknown=$((unknown+1))
    elif [ -z "$consensus" ] || [ "$v" = "$consensus" ]; then
        printf '  \342\234\223 %-24s %s\n' "$repo" "$v"
    else
        printf '  \342\234\227 %-24s %s (\342\211\240 consensus %s)\n' "$repo" "$v" "$consensus"
        drift=$((drift+1))
    fi
done

echo
if [ -z "$consensus" ]; then
    echo "No stamps resolved — cannot assess consistency."
elif [ "$drift" -eq 0 ]; then
    echo "Version stamps: consistent at $consensus across the coupled set."
    if [ -n "$ref" ] && [ "$consensus" != "$ref" ]; then
        echo "  (consensus trails release tag $ref — expected: the committed source"
        echo "   stamp is deliberately frozen; wheels are stamped at build time.)"
    fi
else
    echo "Version drift: $drift stamp(s) out of step with consensus $consensus."
fi
[ "$unknown" -gt 0 ] && echo "($unknown stamp(s) unresolved.)"
exit 0
