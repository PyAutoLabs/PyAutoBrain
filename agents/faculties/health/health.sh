#!/usr/bin/env bash
# agents/health/health.sh — the health agent (a PyAutoBrain reasoning agent).
#
# Reasons over the PyAutoHeart monitoring surface. By default it runs one
# refresh cycle and renders the unified dashboard card (the same board every
# other surface shows — the authoritative readiness verdict at its head, plus
# every check and the release-validation state). Any subcommand
# is forwarded straight to `pyauto-heart`, so this agent is a thin, named driver
# of Heart rather than a second implementation of any check. The Brain reasons
# about health; PyAutoHeart measures it.
#
# Usage:
#   health.sh                 # one tick, then render the unified dashboard card
#   health.sh status          # forward: pyauto-heart status
#   health.sh watch [secs]    # forward: pyauto-heart watch (continuous)
#   health.sh <subcommand>... # forward verbatim to pyauto-heart
#
# The no-arg card is the SAME unified board every other surface shows (one
# renderer in heart/dashboard.py) — verdict, score, top blockers, and the
# release-validation state — not raw verdict JSON. On a phone the reasoning
# agent pulls `pyauto-heart dashboard --json` / `--md` for the same card.
#
# Future: several health agents may each reason over a different slice of Heart
# (CI, worktree drift, timing, ...). For now this single agent covers the whole
# surface via pyauto-heart.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

heart="$(resolve_heart)" || exit $?

if [[ $# -eq 0 ]]; then
  echo "== health agent: refreshing PyAutoHeart state =="
  "$heart" tick
  echo
  # Render the ONE unified board (readiness verdict + every check + the
  # release-validation state), not just the raw verdict. Same renderer as the
  # web page and the mobile card, so the surfaces cannot disagree.
  exec "$heart" dashboard
fi

exec "$heart" "$@"
