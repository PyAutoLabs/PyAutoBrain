#!/usr/bin/env bash
# agents/conductors/cortex/cortex.sh — the Cortex Agent (a PyAutoBrain
# reasoning conductor). The learning function — where the organism finds out
# what is true.
#
# Reasons over PyAutoCortex, the organ that holds the science body map, the
# pre-registered phases and the rulings of record: renders the Cortex board
# (dashboard.md + dashboard.html, published to Pages), grades the gates that
# hold a phase back, and admits ready phases into a laptop slot. It never
# submits a run and never writes a ruling — the run is the human's act and
# the verdict is theirs.
#
# Usage:
#   cortex.sh                          # census (default)
#   cortex.sh census --json            # machine-readable
#   cortex.sh dashboard --check        # exit 1 if the pages are stale
#   cortex.sh dashboard --apply        # write dashboard.md + dashboard.html
#   cortex.sh gates [--grade] [--apply]  # the refs; grade them; write the flips
#   cortex.sh plan [--budget 45]       # which ready phases fit the slot
#   cortex.sh <verb> --cortex <dir>    # point at another PyAutoCortex checkout

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

exec python3 "$HERE/_cortex.py" "$@"
