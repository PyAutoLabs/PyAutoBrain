#!/usr/bin/env bash
# agents/conductors/community/community.sh — the Community Agent (a PyAutoBrain
# reasoning conductor). Organism-facing name: the Ears — the organism's
# receptive language function: it hears the community (the Discussions hub
# where users ask, plus user-filed GitHub issues and PRs) and drafts what the
# organism says back; the human remains the mouth.
# (Wernicke to the Workspace Agent's Broca — that Voice speaks through
# examples; this agent comprehends and converses.)
#
# The CLI emits deterministic, read-only surfaces; the conversational judgment
# (actionable vs ask-for-more, the reply prose) lives in the /community skill
# session, and every outward message is gated on the human. It never posts,
# labels, edits or writes anything.
#
# Usage:
#   community.sh                       # scan (default): the hub's open
#                                      #   discussions + external issues/PRs,
#                                      #   awaiting-response ranking, review
#                                      #   requests
#   community.sh scan                  # same, explicit
#   community.sh triage <ref>          # one discussion/issue/PR -> context-
#                                      #   sufficiency surface (+ PR change-shape
#                                      #   block); <ref> = a discussion/issue/PR
#                                      #   URL or owner/repo#N
#   community.sh ... --json            # machine-readable output

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

exec python3 "$HERE/_community.py" "$@"
