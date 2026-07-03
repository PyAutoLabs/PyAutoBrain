#!/usr/bin/env bash
# agents/conductors/health/health.sh — the health conductor (SKELETON).
#
# The health conductor is the organism's clinician: the brain's vagus-nerve link
# to the Heart. It runs the health loop *with a human* — assess -> triage -> (on
# your go-ahead) dispatch a validation leg -> re-judge -> repeat — until
# PyAutoHeart goes GREEN. It is a CONDUCTOR: it decides and drives, delegating
# every action to the agent that owns it, and reimplements no check of its own.
#
# Boundaries (this cut):
#   * It CONSULTS the vitals faculty for every verdict (read-only). Only the
#     vitals faculty / Heart measures; this conductor never re-derives a verdict.
#   * It DELEGATES all GitHub dispatch to the release conductor
#     (`pyauto-brain release validate ...`), which owns the MCP boundary. It
#     never dispatches or mutates a repo itself.
#   * Scope = validation + recommend. It runs the *assess* step deterministically
#     and RECOMMENDS the next dispatch; it does NOT auto-run it. Every dispatch is
#     a human checkpoint (you confirm, then the Brain session drives the leg).
#     Repo-editing fixes are a deliberate FOLLOW-UP, not in this skeleton.
#
# The conversational fix loop itself is mediated by the Brain reasoning layer on
# top of this scaffold; health.sh supplies the deterministic footing: the current
# verdict + card, and the single recommended next checkpoint.
#
# Usage:
#   health.sh            # assess: render the card, read the verdict, recommend
#   health.sh assess     # same as the no-arg assess
#   health.sh -h|--help  # this header
#
# Exit codes mirror the verdict so a caller can branch: 0 green · 2 yellow ·
# 3 red · 4 unknown.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

case "${1:-assess}" in
  -h|--help)
    sed -n '2,33p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  assess) : ;;
  *)
    echo "health: unknown subcommand '${1:-}' (this skeleton supports: assess)" >&2
    exit 2
    ;;
esac

echo "== health: assessing organism health (consulting the vitals faculty) =="

# 1. Show the human the unified board (the vitals faculty renders Heart's card).
vitals="$(_agents_dir)/faculties/vitals/vitals.sh"
if [[ -f "$vitals" ]]; then
  bash "$vitals" || true
else
  echo "health: vitals faculty not found at $vitals" >&2
fi

echo
# 2. Read the authoritative verdict *through* the faculty — never re-derived here.
verdict="$(consult_vitals_verdict --refresh)"
echo "== health: adopted verdict = ${verdict} =="
echo

# 3. Triage -> the single recommended next checkpoint. This conductor RECOMMENDS;
#    the human confirms; the Brain session then drives the leg. Nothing is
#    dispatched from here.
case "$verdict" in
  green)
    echo "GREEN — the organism is release-healthy. No action needed."
    echo "  (A conductor such as 'pyauto-brain release' may now proceed.)"
    exit 0
    ;;
  yellow)
    cat <<'EOF'
YELLOW — mostly healthy; something is unknown or cautionary. Typical first-run
cause: no fresh release-validation for the current source. Recommended next
checkpoint (needs your go-ahead — the health conductor will NOT run it for you):

    pyauto-brain release validate        # Stage 0-3: TestPyPI rehearsal +
                                         # wheel integration -> ingest -> re-judge

After that leg lands, re-run `pyauto-brain health` to re-assess. Repeat until
GREEN. For a specific warning, ask the health conductor to map it to its
capability and, where Heart offers one, the
`pyauto-heart fix <ci|dirty|drift|timing>` entry point (validation+recommend
scope — code-editing fixes are a follow-up).
EOF
    exit 2
    ;;
  red)
    cat <<'EOF'
RED — a real blocker. Do NOT dispatch a release. Ask the health conductor to map
each blocking reason to its capability and the remediation entry point; resolve
the blockers (outside this validation+recommend skeleton), then re-run
`pyauto-brain health` to re-assess.
EOF
    exit 3
    ;;
  *)
    echo "UNKNOWN — could not obtain a verdict from the vitals faculty."
    echo "  Recommended: 'pyauto-brain vitals' to refresh, then re-run the health conductor."
    exit 4
    ;;
esac
