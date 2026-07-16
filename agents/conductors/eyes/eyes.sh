#!/usr/bin/env bash
# agents/conductors/eyes/eyes.sh — the Eyes Agent (a PyAutoBrain reasoning
# conductor). The perceptive function — the organism's sense of its own
# appearance.
#
# Surveys a visualization workspace's figure surface (inventory, render
# staleness, gallery currency, never-rendered gaps) and prepares the review
# surface the agentic critique loop consumes. It reasons and delegates — it
# never renders (the workspace's scripts/gallery/gallery_run.sh does) and
# never edits plot source (accepted critiques route via intake/start_dev).
# The workspace root is always an argument; this agent names no repos
# (tenant firewall).
#
# Usage:
#   eyes.sh survey <workspace-root>            # EyesSurvey
#   eyes.sh review <workspace-root> [--batch N] # EyesReviewSurface
#   eyes.sh --json ...                         # machine-readable decision

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

exec python3 "$HERE/_eyes.py" "$@"
