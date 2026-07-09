#!/usr/bin/env bash
# agents/conductors/profiling/profiling.sh — the Profiling Agent (a PyAutoBrain
# reasoning conductor). The proprioceptive function — the organism's sense
# of its own effort.
#
# Owns the organism's performance-data lifecycle with autolens_profiling as
# its workspace: diffs the campaign grid against the results tree and emits
# the dispatch plan (campaign), turns probe JSONs + unpinned results into a
# table/pin/baseline plan (ingest), and classifies pinned-value drift
# findings from Heart's profiling_drift leg (triage). It reasons and
# delegates — it never runs sweeps or edits source itself, and it honours
# the CPU-usability policy (autolens_profiling/results/notes/design_lock_in.md).
#
# Usage:
#   profiling.sh                       # campaign, local tier (default)
#   profiling.sh campaign --tier a100  # A100 dispatch plan (RAL submits)
#   profiling.sh ingest                # probe/pin/baseline ingest plan
#   profiling.sh triage                # drift-flag classification
#   profiling.sh --json ...            # machine-readable ProfilingDecision

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

exec python3 "$HERE/_profiling.py" "$@"
