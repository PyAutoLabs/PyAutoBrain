#!/usr/bin/env bash
# agents/conductors/clone/clone.sh — the Clone Agent (a PyAutoBrain reasoning
# conductor). Organism-facing name: the Mitosis Agent — reproduces a mature
# domain assistant into a new specialised cell.
#
# v0 is DECISION ONLY (see DESIGN.md): analyze mode emits a CloneDecision —
# domain analysis, template-boundary partition (seeded from the reference's
# modes/maintainer.md "Assistant-as-template" section), generation plan, the
# mandatory clone-mode question. It writes nothing; --apply arrives with v1.
#
# Usage:
#   clone.sh <library> --workspace <repo> [--howto <repo>] [--reference <repo>]
#   clone.sh PyAutoFit --workspace autofit_workspace --howto HowToFit
#   clone.sh --json ...                # machine-readable CloneDecision

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

exec python3 "$HERE/_clone.py" "$@"
