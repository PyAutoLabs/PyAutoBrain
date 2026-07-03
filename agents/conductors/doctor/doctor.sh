#!/usr/bin/env bash
# agents/conductors/doctor/doctor.sh — the doctor conductor (SKELETON).
#
# The doctor is the organism's clinician: the brain's vagus-nerve link to the
# Heart. It runs the health loop *with a human* — assess -> triage -> (on your
# go-ahead) dispatch a validation leg -> re-judge -> repeat — until PyAutoHeart
# goes GREEN. It is a CONDUCTOR: it decides and drives, delegating every action
# to the agent that owns it, and reimplements no check of its own.
#
# Boundaries (this cut):
#   * It CONSULTS the health faculty for every verdict (read-only). Only the
#     health faculty / Heart measures; the doctor never re-derives a verdict.
#   * It DELEGATES all GitHub dispatch to the release conductor
#     (`pyauto-brain release validate ...`), which owns the MCP boundary. The
#     doctor never dispatches or mutates a repo itself.
#   * Scope = validation + recommend. It runs the *assess* step deterministically
#     and RECOMMENDS the next dispatch; it does NOT auto-run it. Every dispatch is
#     a human checkpoint (you confirm, then the Brain session drives the leg).
#     Repo-editing fixes are a deliberate FOLLOW-UP, not in this skeleton.
#
# The conversational fix loop itself is mediated by the Brain reasoning layer on
# top of this scaffold; doctor.sh supplies the deterministic footing: the current
# verdict + card, and the single recommended next checkpoint.
#
# Usage:
#   doctor.sh            # assess: render the card, read the verdict, recommend
#   doctor.sh assess     # same as the no-arg assess
#   doctor.sh -h|--help  # this header
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
    echo "doctor: unknown subcommand '${1:-}' (this skeleton supports: assess)" >&2
    exit 2
    ;;
esac

echo "== doctor: assessing organism health (consulting the health faculty) =="

# 1. Show the human the unified board (the health faculty renders Heart's card).
health="$(_agents_dir)/faculties/health/health.sh"
if [[ -f "$health" ]]; then
  bash "$health" || true
else
  echo "doctor: health faculty not found at $health" >&2
fi

echo
# 2. Read the authoritative verdict *through* the faculty — never re-derived here.
verdict="$(consult_health_agent_verdict --refresh)"
echo "== doctor: adopted verdict = ${verdict} =="
echo

# 3. Triage -> the single recommended next checkpoint. The doctor RECOMMENDS;
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
checkpoint (needs your go-ahead — the doctor will NOT run it for you):

    pyauto-brain release validate        # Stage 0-3: TestPyPI rehearsal +
                                         # wheel integration -> ingest -> re-judge

After that leg lands, re-run `pyauto-brain doctor` to re-assess. Repeat until
GREEN. For a specific warning, ask the doctor to map it to its capability and,
where Heart offers one, the `pyauto-heart fix <ci|dirty|drift|timing>` entry
point (validation+recommend scope — code-editing fixes are a follow-up).
EOF
    exit 2
    ;;
  red)
    cat <<'EOF'
RED — a real blocker. Do NOT dispatch a release. Ask the doctor to map each
blocking reason to its capability and the remediation entry point; resolve the
blockers (outside this validation+recommend skeleton), then re-run
`pyauto-brain doctor` to re-assess.
EOF
    exit 3
    ;;
  *)
    echo "UNKNOWN — could not obtain a verdict from the health faculty."
    echo "  Recommended: 'pyauto-brain health' to refresh, then re-run the doctor."
    exit 4
    ;;
esac
