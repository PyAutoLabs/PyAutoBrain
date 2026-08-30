#!/usr/bin/env bash
# agents/conductors/batch/batch.sh — the Batch Agent (a PyAutoBrain conductor).
#
# Composes what goes into one unattended shift. Thin by construction: every
# judgement it uses — consequence tier, review-minutes, readiness, difficulty —
# belongs to the sizing faculty. This agent decides MEMBERSHIP, which is an act
# rather than an opinion, which is what makes it a conductor.
#
# It proposes; it never dispatches. Approving the proposal in a slot is what
# launches a batch (AUTONOMY.md, "What a batch launch is") — the schedule may
# carry the timing, never the authority.
#
# Usage:
#   batch.sh plan                        # the BatchDecision for this session's lane
#   batch.sh plan --budget 45            # review-minutes available in the slot
#   batch.sh plan --awaiting-review 6    # backpressure input
#   batch.sh plan --json

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

exec python3 "$HERE/_batch.py" "$@"
