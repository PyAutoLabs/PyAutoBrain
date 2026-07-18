#!/usr/bin/env bash
# agents/faculties/sizing/sizing.sh — the sizing faculty (a PyAutoBrain
# read-only reasoning capability). Estimates how hard a PyAutoMind task is.
#
# The difficulty heuristic is defined once in _sizing.py and consulted by both
# the Intake Agent (which persists the Difficulty: header at conception) and the
# Feature Agent (which sizes at selection/planning). This entrypoint is a thin
# read-only wrapper: given a prompt path it prints the SizingSurface (parsed
# prompt + difficulty judgment). Read-only: never writes, never dispatches.
#
# Usage:
#   sizing.sh <prompt-path>          # human-readable SizingSurface
#   sizing.sh <prompt-path> --json   # machine-readable

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

# Degrade gracefully: an absent Mind checkout falls back to the CLI default.
mind="$(_resolve_dir PYAUTO_MIND PyAutoMind 2>/dev/null || true)"

exec python3 "$HERE/_sizing.py" ${mind:+--mind "$mind"} "$@"
