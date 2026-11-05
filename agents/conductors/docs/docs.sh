#!/usr/bin/env bash
# agents/conductors/docs/docs.sh — the Documentation Agent (a PyAutoBrain
# reasoning conductor). Owns skills/WRITING_STYLE.md: classifies a docs request
# by surface and emits a DocsDecision; audit mode scores one page against the
# style guide's checklist. Read-only — authoring runs through start_dev, and
# tutorial science prose is deferred to the Workspace conductor.
#
# Usage:
#   docs.sh "<raw intent text>"           # plan (default mode)
#   docs.sh <PyAutoMind prompt path>      # plan from a filed prompt
#   docs.sh audit <page> [--kind K]       # read-only style audit
#   docs.sh --json ...                    # machine-readable output

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

exec python3 "$HERE/_docs.py" "$@"
