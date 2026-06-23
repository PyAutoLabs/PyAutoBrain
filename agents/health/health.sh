#!/usr/bin/env bash
# agents/health/health.sh — the health agent.
#
# Drives the PyAutoPulse monitoring surface. By default it runs one refresh
# cycle and prints the authoritative readiness verdict. Any subcommand is
# forwarded straight to `pyauto-pulse`, so this agent is a thin, named driver
# of Pulse rather than a second implementation of any check.
#
# Usage:
#   health.sh                 # one tick, then print readiness
#   health.sh status          # forward: pyauto-pulse status
#   health.sh watch [secs]    # forward: pyauto-pulse watch (continuous)
#   health.sh <subcommand>... # forward verbatim to pyauto-pulse
#
# Future: several health agents may each consume a different slice of Pulse
# (CI, worktree drift, timing, ...). For now this single agent covers the whole
# surface via pyauto-pulse.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../_common.sh"

pulse="$(resolve_pulse)" || exit $?

if [[ $# -eq 0 ]]; then
  echo "== health agent: refreshing PyAutoPulse state =="
  "$pulse" tick
  echo
  exec "$pulse" readiness
fi

exec "$pulse" "$@"
