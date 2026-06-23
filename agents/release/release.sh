#!/usr/bin/env bash
# agents/release/release.sh — the release agent.
#
# Call chain: Agent -> Pulse (gate) -> Build (execute).
#
#   1. Ask PyAutoPulse for the authoritative readiness verdict.
#   2. Block unless it is green (red = a real blocker; yellow = caution).
#   3. On green, delegate to the PyAutoBuild executor (`autobuild pre_build`,
#      which prepares the workspaces and dispatches release.yml).
#
# This agent contains NO gate logic and NO release mechanics of its own — it
# reads Pulse's verdict and delegates to Build. Everything it decides is decided
# by Pulse; everything it executes is executed by Build.
#
# Usage:
#   release.sh [--force] [-- <args forwarded to `autobuild pre_build`>]
#
#   --force   Proceed on a YELLOW verdict (cautions acknowledged). RED always
#             blocks. Use only when you know what you are doing.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../_common.sh"

force=0
forward=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) force=1; shift ;;
    --) shift; forward=("$@"); break ;;
    *) forward+=("$1"); shift ;;
  esac
done

echo "== release agent: gating on pyauto-pulse readiness =="

pulse="$(resolve_pulse)" || exit $?

# Refresh the verdict from a fresh tick so the gate is not stale, then read it.
"$pulse" tick >/dev/null 2>&1 || echo "  (warning: tick failed; using last cached state)" >&2

verdict="$(readiness_verdict)" || { echo "release agent: could not obtain readiness verdict" >&2; exit 1; }

# Show the human-readable readiness block too.
"$pulse" readiness || true

case "$verdict" in
  green)
    echo "== readiness GREEN — delegating to PyAutoBuild executor =="
    ;;
  yellow)
    if [[ "$force" -eq 1 ]]; then
      echo "== readiness YELLOW — proceeding (--force) =="
    else
      echo "release agent: readiness is YELLOW (caution). Re-run with --force to proceed." >&2
      exit 2
    fi
    ;;
  red)
    echo "release agent: readiness is RED — release blocked. Fix the blockers above." >&2
    exit 3
    ;;
  *)
    echo "release agent: unknown readiness verdict '$verdict' — refusing to release." >&2
    exit 4
    ;;
esac

autobuild="$(resolve_autobuild)" || exit $?
echo "== exec: autobuild pre_build ${forward[*]:-} =="
exec "$autobuild" pre_build "${forward[@]}"
