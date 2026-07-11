#!/usr/bin/env bash
# agents/conductors/hygiene/hygiene.sh — the Hygiene Agent (a PyAutoBrain
# reasoning conductor). The maintenance function — the organism's sense of its
# own upkeep: the code-quality debt that neither proves it works (that is Heart)
# nor measures the speed of modelling (that is profiling).
#
# Owns code-quality upkeep across the organism and emits a HygieneDecision the
# human/session executes, delegating the actual fixes to the dev-flow conductors
# (refactor/bug/feature) via ship_*. It reasons; it never edits source itself,
# and (like profiling) it stays stdlib/bash so it never drags the JAX stack into
# the Brain.
#
# Usage:
#   hygiene.sh                 # audit across modes -> prioritised worklist (default)
#   hygiene.sh perf            # dev-loop timing: unit tests / integration scripts / imports (phase 3)
#   hygiene.sh tidy            # git debris: the repo_cleanup sweep (phase 2)
#   hygiene.sh noise           # CLI noise: the cli_noise_clean audit (phase 2)
#   hygiene.sh deps            # dependency-cap drift: dep_audit vs PyPI (phase 2)
#   hygiene.sh docs            # stale API docs: audit_docs over docs/api/*.rst (phase 2)
#   hygiene.sh <mode> --json   # machine-readable HygieneDecision
#
# PHASE 1 SCAFFOLD: the conductor is real, routable and bounded, but the modes
# are staged stubs — each reports where it lands. Per-mode behaviour and
# exit-code semantics arrive with the modes (phases 2-3).

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

MODE_ORDER=(perf tidy noise deps docs)
declare -A MODE_PHASE=(
  [perf]="phase 3" [tidy]="phase 2" [noise]="phase 2" [deps]="phase 2" [docs]="phase 2"
)
declare -A MODE_DESC=(
  [perf]="dev-loop timing — unit tests / integration-mode scripts / import cost; route to refactor/bug"
  [tidy]="git debris — the repo_cleanup sweep"
  [noise]="CLI noise — the cli_noise_clean audit"
  [deps]="dependency-cap drift — dep_audit vs PyPI"
  [docs]="stale API docs — audit_docs over docs/api/*.rst"
)

mode="default"
json=0
for arg in "$@"; do
  case "$arg" in
    perf|tidy|noise|deps|docs) mode="$arg" ;;
    default) mode="default" ;;
    --json) json=1 ;;
    -h|--help|help) mode="help" ;;
    *) echo "hygiene: unknown argument '$arg' (modes: ${MODE_ORDER[*]}, --json)" >&2; exit 2 ;;
  esac
done

if [[ "$mode" == "help" ]]; then
  # Print the "# Usage:" block from this script's own header (robust to the
  # header moving — no hard-coded line numbers).
  awk '/^# Usage:/{u=1;next} u{ if($0 ~ /^#   /){sub(/^#   /,"  "); print} else exit }' "$HERE/hygiene.sh"
  exit 0
fi

# --- JSON footing (staged): a HygieneDecision shell the Brain session can read.
if [[ "$json" -eq 1 ]]; then
  if [[ "$mode" == "default" ]]; then
    printf '{"decision":"HygieneDecision","status":"staged-phase-1","mode":"default","modes":['
    sep=""
    for m in "${MODE_ORDER[@]}"; do
      printf '%s{"mode":"%s","status":"staged","lands":"%s"}' "$sep" "$m" "${MODE_PHASE[$m]}"
      sep=","
    done
    printf ']}\n'
  else
    printf '{"decision":"HygieneDecision","status":"staged-phase-1","mode":"%s","lands":"%s"}\n' \
      "$mode" "${MODE_PHASE[$mode]}"
  fi
  exit 0
fi

# --- Human footing.
echo "== HygieneDecision (phase-1 scaffold — modes staged) =="
echo "The hygiene conductor owns code-quality upkeep: developer-loop cost and repo"
echo "tidiness, distinct from Heart (proof-of-works) and profiling (modelling speed)."
echo "It finds and prioritises debt, then delegates the fix to refactor/bug/feature."
echo
if [[ "$mode" == "default" ]]; then
  printf '  %-6s %-9s %s\n' "MODE" "LANDS" "SCOPE"
  for m in "${MODE_ORDER[@]}"; do
    printf '  %-6s %-9s %s\n' "$m" "${MODE_PHASE[$m]}" "${MODE_DESC[$m]}"
  done
  echo
  echo "Run 'pyauto-brain hygiene <mode>' for a mode once it lands; --json for the"
  echo "machine footing. Design: PyAutoMind research/pyautobrain/hygiene_agent_decision.md."
else
  echo "  mode:  $mode"
  echo "  scope: ${MODE_DESC[$mode]}"
  echo "  lands: ${MODE_PHASE[$mode]} — not yet implemented (phase-1 scaffold)."
fi
exit 0
