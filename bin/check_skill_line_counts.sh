#!/usr/bin/env bash
# Report any *primary* skill .md file over the line limit (default 200).
#
# Claude skill guidance keeps primary skill files short; long background,
# templates and examples belong in supporting docs (`reference.md`, shared
# `WORKFLOW.md`), which are exempt here. A "primary" file is a skill's `SKILL.md`
# or its command body `<dirname>.md`.
#
# Scans the same discovery roots as install.sh. Exit 0 = all within limit,
# exit 1 = at least one primary file is over the limit.
#
# Usage:
#   bash PyAutoBrain/bin/check_skill_line_counts.sh [limit]

set -euo pipefail

LIMIT="${1:-200}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYAUTO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

ROOTS=(
  "$PYAUTO_ROOT/admin_jammy/skills"         # vestigial (hosts no skills)
  "$PYAUTO_ROOT/PyAutoMind/skills"
  "$PYAUTO_ROOT/PyAutoBrain/skills"
  "$PYAUTO_ROOT/PyAutoHeart/skills"
  "$PYAUTO_ROOT/PyAutoBuild/skills"
  "$PYAUTO_ROOT/autolens_profiling/skills"
)

over=0
checked=0

for root in "${ROOTS[@]}"; do
  [ -d "$root" ] || continue
  for dir in "$root"/*/; do
    [ -d "$dir" ] || continue
    name="$(basename "$dir")"
    # Primary files: SKILL.md (dispatcher/frontmatter) and the command/body
    # <dirname>.md. Supporting docs (reference.md, examples, etc.) are exempt.
    for primary in "$dir/SKILL.md" "$dir/$name.md"; do
      [ -f "$primary" ] || continue
      checked=$((checked + 1))
      lines=$(wc -l < "$primary")
      if [ "$lines" -gt "$LIMIT" ]; then
        echo "OVER  ${lines}  ${primary#$PYAUTO_ROOT/}"
        over=$((over + 1))
      fi
    done
  done
done

echo ""
if [ "$over" -eq 0 ]; then
  echo "OK: all $checked primary skill files are within $LIMIT lines."
  exit 0
else
  echo "FAIL: $over primary skill file(s) exceed $LIMIT lines — factor detail into reference.md."
  exit 1
fi
