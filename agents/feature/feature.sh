#!/usr/bin/env bash
# agents/feature/feature.sh — the feature agent (a PyAutoBrain reasoning agent).
#
# The Feature Agent is the *growth function* of PyAutoBrain. It reasons over the
# feature intent stored in PyAutoMind and decides HOW the organism should grow:
# which feature task to work on, how hard it is, whether it must be phased, and
# which development path applies. It does NOT implement code — it produces a
# structured FeatureDecision that the existing workflow consumes:
#
#   Mind (PyAutoMind feature/*)  ->  Feature Agent  ->  start_dev
#                                                    ->  start_library / ship_library
#                                                    ->  start_workspace / ship_workspace
#
# Like the Build Agent, it is a society-of-agents citizen: for risky / multi-repo
# / release-bound work it can consult the sibling Health Agent (and only the
# Health Agent talks to the Heart organ). It consults PyAutoMemory for scientific
# and architectural context — it never invents science when memory has material.
#
# Modes:
#   specific   read a named PyAutoMind prompt and plan it for start_dev.
#   selection  choose the best next feature task (no task named).
#   difficulty-constrained  select under a constraint (--difficulty / --model /
#              --budget / --ambitious / --impact).
#
# Usage:
#   feature.sh <feature/target/name.md>          # specific mode
#   feature.sh select [--difficulty small|medium|large|easy]
#                      [--model weak|strong] [--budget] [--ambitious]
#                      [--impact] [--limit N]
#   feature.sh [--json] ...                       # machine-readable FeatureDecision
#   feature.sh [--check-health] ...               # also consult the Health Agent
#
# The analysis core lives in _feature.py (stdlib-only, never writes). This script
# resolves the PyAutoMind / PyAutoMemory checkouts and, optionally, the verdict.
#
# Exit codes: 0 produced a decision · 4 no prompts / could-not-resolve · 5 bad
# usage (unknown task / flag).

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../_common.sh"

check_health=0
as_json=0
forward=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --check-health) check_health=1; shift ;;
    --json) as_json=1; shift ;;
    *) forward+=("$1"); shift ;;
  esac
done

mind="$(resolve_mind)" || exit 4

# PyAutoMemory is optional: the Feature Agent points at the relevant sub-wikis
# even if the checkout is absent, but degrades gracefully rather than failing.
memory="$(resolve_memory 2>/dev/null || true)"

# Normalise the subcommand. Nothing given -> selection mode. A bare path (or any
# first token that is not a known subcommand or flag) -> specific mode on that
# task, so `feature.sh feature/foo/bar.md` works as the primary entry point.
if [[ ${#forward[@]} -eq 0 ]]; then
  forward=(select)
elif [[ "${forward[0]}" != "select" && "${forward[0]}" != "specific" \
        && "${forward[0]}" != --* ]]; then
  forward=(specific "${forward[@]}")
fi

# Optionally consult the sibling Health Agent up front (society-of-agents). This
# does not gate the decision — it annotates it — so the agent still reasons even
# when Heart is unreachable.
if [[ "$check_health" -eq 1 ]]; then
  echo "== feature agent: consulting Health Agent for tree readiness =="
  verdict="$(consult_health_agent_verdict)"
  echo "   readiness verdict: $verdict"
  echo
fi

json_flag=()
[[ "$as_json" -eq 1 ]] && json_flag=(--json)

exec python3 "$HERE/_feature.py" --mind "$mind" --memory "$memory" \
  "${json_flag[@]}" "${forward[@]}"
