#!/usr/bin/env bash
# board/board.sh — the PyAutoBrain operational board (the morning door).
#
# A generated SURFACE, not an agent: it decides nothing and opines on nothing —
# it reads what the organs already publish (scheduled-run conclusions, the
# Heart's badge, the Mind's registry, the Ears' scan) and renders the one-tap
# page brain_board.yml serves at the Brain's GitHub Pages URL. Read-only:
# no posts, no labels, no writes outside --apply's output directory.
#
# Usage:
#   board.sh                 # markdown digest to stdout (the terminal read)
#   board.sh --html          # the one-tap html page
#   board.sh --json          # the raw surface
#   board.sh --badge         # badge.json (the cross-board headline contract)
#   board.sh --apply [--out DIR]   # write index.html + badge.json +
#                                  #   board.json + board.md (default _site/)

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

exec python3 "$HERE/_board.py" "$@"
