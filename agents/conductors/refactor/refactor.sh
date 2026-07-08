#!/usr/bin/env bash
# agents/conductors/refactor/refactor.sh — the refactor agent (a PyAutoBrain
# reasoning conductor). The renewal function.
#
# Plans behaviour-preserving internal restructuring from PyAutoMind's
# refactor/* backlog and emits a RefactorDecision for start_dev [--auto].
# Reuses the Feature Agent's core by import (see _refactor.py); consults the
# sizing faculty through it. It does NOT implement code, files nothing, and
# never bypasses a gate — `safe` changes who approves, never what is verified
# (AUTONOMY.md).
#
# Usage:
#   refactor.sh                                    # selection: best next refactor task
#   refactor.sh refactor/<target>/<name>.md        # specific: plan a named task
#   refactor.sh candidates                         # mine backlog + ideas.md (read-only)
#   refactor.sh --json ...                         # machine-readable RefactorDecision

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

mind="$(resolve_mind)" || exit $?

json_flag=()
forward=()
for arg in "$@"; do
  case "$arg" in
    --json) json_flag=(--json) ;;
    *) forward+=("$arg") ;;
  esac
done

exec python3 "$HERE/_refactor.py" --mind "$mind" "${json_flag[@]}" "${forward[@]+"${forward[@]}"}"
