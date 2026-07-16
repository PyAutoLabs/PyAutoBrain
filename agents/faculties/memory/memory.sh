#!/usr/bin/env bash
# agents/faculties/memory/memory.sh — the memory faculty (a PyAutoBrain
# read-only reasoning capability). It recalls what the organism knows.
#
# Greps the knowledge surfaces — PyAutoMemory sub-wikis, autolens_assistant
# skills/wiki, PyAutoMind complete/ records — and emits a cited digest (ranked pages
# + matching snippets). The consulting agent reads only the listed pages and
# synthesises. Read-only: never writes, never dumps whole pages, never invents
# context when the surfaces are empty. Privacy seam: PyAutoMemory citations
# never reach public user-facing output (see AGENTS.md here).
#
# Usage:
#   memory.sh "<topic or question>"        # ranked cited digest
#   memory.sh --json "<topic>"             # machine-readable
#   memory.sh --limit 12 "<topic>"         # more pages

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

# Degrade gracefully: absent surfaces are reported, not fatal.
memory="$(resolve_memory 2>/dev/null || true)"
mind="$(resolve_mind 2>/dev/null || true)"
assistant="$(_resolve_dir AUTOLENS_ASSISTANT autolens_assistant 2>/dev/null || true)"

exec python3 "$HERE/_memory.py" \
  ${memory:+--memory "$memory"} \
  ${assistant:+--assistant "$assistant"} \
  ${mind:+--mind "$mind"} \
  "$@"
