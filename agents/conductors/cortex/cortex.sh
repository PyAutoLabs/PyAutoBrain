#!/usr/bin/env bash
# agents/conductors/cortex/cortex.sh — the Cortex Agent (a PyAutoBrain
# reasoning conductor). The learning function — where the organism finds out
# what is true.
#
# Reasons over PyAutoCortex, the organ that holds the science body map, the
# pre-registered phases and the rulings of record: renders the Cortex board
# (dashboard.md + dashboard.html, published to Pages), lists what each gated
# phase is waiting on, and scores what a pull brought back. Its verbs never
# submit a run and never write a ruling — a run is submitted only on the
# human's ask, and the verdict is theirs.
#
# Usage:
#   cortex.sh                          # census (default)
#   cortex.sh census --json            # machine-readable
#   cortex.sh dashboard --check        # exit 1 if the pages are stale
#   cortex.sh dashboard --apply        # write dashboard.md + dashboard.html
#   cortex.sh gates                    # every gated phase and its refs
#   cortex.sh collect --pull --apply   # the check-in: pull, score, move on
#   cortex.sh <verb> --cortex <dir>    # point at another PyAutoCortex checkout

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

exec python3 "$HERE/_cortex.py" "$@"
