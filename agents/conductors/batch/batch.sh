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
#
#   batch.sh collect                     # score the newest batch record; offline
#   batch.sh collect --slot 2026-09-03-pm
#   batch.sh collect --evidence ev.json  # PR state the session gathered (MCP surface)
#   batch.sh collect --fetch             # laptop only: one `gh pr view` per PR
#   batch.sh collect --integration       # laptop only: merge every member's head per repo
#   batch.sh collect --evidence ev.json --apply [--stamp ISO]   # the form that writes
#   batch.sh collect --out report.md --json
#
# collect reads and prints; only --apply writes (the packet page and the
# record's stamps). Exit: 0 all delivered, 1 a member needs the human,
# 2 usage, 4 no Mind.
#
# --integration builds a throwaway worktree root under $PYAUTO_WT_ROOT, one
# repo per affected library/workspace on integration/<slot> off origin/main
# with every member's head merged in. It writes no remote: it fetches and
# merges locally, pushes nothing and opens no PR. A member whose merge
# conflicts is left out and named with the conflicting files -- that report
# is the product, and it does not move the exit code.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

exec python3 "$HERE/_batch.py" "$@"
