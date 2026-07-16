#!/usr/bin/env bash
# agents/conductors/workspace/workspace.sh — the Workspace Agent (a PyAutoBrain
# reasoning conductor). Organism-facing name: the Voice — the organism's
# expressive function: how it speaks to practitioners (workspace examples) and
# teaches first-time learners (the howto register).
#
# v0 is DECISION ONLY: plan mode emits a WorkspaceDecision (target repo,
# register, placement, sibling to mirror, format checklist, routing); survey
# mode inventories a workspace repo's example catalogue. It writes nothing —
# authoring runs through start_dev → start_workspace → ship_workspace.
#
# Usage:
#   workspace.sh "<raw intent text>"                # plan (default mode)
#   workspace.sh <PyAutoMind prompt path>           # plan from a filed prompt
#   workspace.sh survey <repo> [--against <repo>]   # catalogue inventory/diff
#   workspace.sh --json ...                         # machine-readable output

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

exec python3 "$HERE/_workspace.py" "$@"
