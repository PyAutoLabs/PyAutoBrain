#!/usr/bin/env bash
# agents/health/health.sh — the health agent (a PyAutoBrain reasoning agent).
#
# Reasons over the PyAutoHeart monitoring surface. By default it runs one
# refresh cycle and prints the authoritative readiness verdict. Any subcommand
# is forwarded straight to `pyauto-heart`, so this agent is a thin, named driver
# of Heart rather than a second implementation of any check. The Brain reasons
# about health; PyAutoHeart measures it.
#
# Usage:
#   health.sh                 # one tick, then print readiness
#   health.sh status          # forward: pyauto-heart status
#   health.sh watch [secs]    # forward: pyauto-heart watch (continuous)
#   health.sh <subcommand>... # forward verbatim to pyauto-heart
#
# Future: several health agents may each reason over a different slice of Heart
# (CI, worktree drift, timing, ...). For now this single agent covers the whole
# surface via pyauto-heart.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../_common.sh"

heart="$(resolve_heart)" || exit $?

if [[ $# -eq 0 ]]; then
  echo "== health agent: refreshing PyAutoHeart state =="
  "$heart" tick
  echo
  exec "$heart" readiness
fi

exec "$heart" "$@"
