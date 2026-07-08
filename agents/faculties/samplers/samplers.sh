#!/usr/bin/env bash
# agents/faculties/samplers/samplers.sh — the samplers faculty (a PyAutoBrain
# read-only reasoning capability). The organism's motor faculty: expertise in
# how it moves through parameter space.
#
# Emits the SamplerSurface digest — an inventory of the three sampler script
# tiers (searches_minimal prototypes, the removed-sampler archive, the
# workspace_test integration scripts) plus the PyAutoFit search catalogue and
# the latest minimal-tier benchmark table, with tier-gap findings (prototyped
# but never promoted; promoted but never integration-tested). The consulting
# agent reads the digest and reasons with AGENTS.md's judgment tables
# (sampler<->likelihood match, gradient/JAX constraints, initialization
# chaining). Read-only: never runs a sampler, never writes, never dispatches.
#
# Usage:
#   samplers.sh                  # human-readable SamplerSurface
#   samplers.sh --json           # machine-readable

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

# Degrade gracefully: absent surfaces are reported, not fatal.
autofit="$(_resolve_dir PYAUTO_FIT PyAutoFit 2>/dev/null || true)"
developer="$(_resolve_dir PYAUTO_FIT_DEVELOPER autofit_workspace_developer 2>/dev/null || true)"
test_ws="$(_resolve_dir PYAUTO_FIT_TEST autofit_workspace_test 2>/dev/null || true)"

exec python3 "$HERE/_samplers.py" \
  ${autofit:+--autofit "$autofit"} \
  ${developer:+--developer "$developer"} \
  ${test_ws:+--test "$test_ws"} \
  "$@"
