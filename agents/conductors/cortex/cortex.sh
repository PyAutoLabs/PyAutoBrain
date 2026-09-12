#!/usr/bin/env bash
# agents/conductors/cortex/cortex.sh — the Cortex Agent (a PyAutoBrain
# reasoning conductor). The learning function — where the organism keeps
# track of what is true.
#
# Reasons over PyAutoCortex, the organ that holds the science body map and one
# ledger per project (Now, Runs, Log): renders the Cortex board (dashboard.md
# + dashboard.html, published to Pages), runs the check-in (each project's own
# sync CLI, its `jobs` output verbatim) and syncs the ledger block onto each
# project's issue. It records cluster facts and the human's words, never a
# verdict of its own — a run is submitted only on the human's ask, and a
# result or lesson is logged only in their words.
#
# Usage:
#   cortex.sh                          # census (default)
#   cortex.sh census --json            # machine-readable
#   cortex.sh dashboard --check        # exit 1 if the pages are stale
#   cortex.sh dashboard --apply        # write dashboard.md + dashboard.html
#   cortex.sh checkin --dry-run        # what it would pull; reaches nothing
#   cortex.sh checkin --apply          # the check-in: pull, jobs, stamp, render, push
#   cortex.sh issue [--apply]          # the ledger block for each project's issue
#   cortex.sh <verb> --cortex <dir>    # point at another PyAutoCortex checkout

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

exec python3 "$HERE/_cortex.py" "$@"
