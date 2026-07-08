#!/usr/bin/env bash
# agents/faculties/review/review.sh — the review faculty (a PyAutoBrain
# read-only reasoning capability). It reviews the change.
#
# Prepares the ReviewSurface for a task worktree / feature branch: per-repo
# merge-base against origin/main, commits ahead, diff stat, changed files and
# risk flags. The VERDICT (CLEAN / FINDINGS / BLOCKED) is produced by the
# reviewing agent following AGENTS.md in this directory — this script only
# prepares the surface, mirroring how vitals.sh reads Heart and the agent
# reasons over the result. Read-only: it never dispatches or mutates, never
# fixes a finding, and never opines on release readiness (Heart's, via the
# vitals faculty).
#
# Usage:
#   review.sh --task <task-name>            # resolve ~/Code/PyAutoLabs-wt/<task>/
#   review.sh --repo <path> [--repo ...]    # explicit repo checkouts
#   review.sh ... --json                    # machine-readable ReviewSurface

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

exec python3 "$HERE/_review.py" "$@"
