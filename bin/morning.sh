#!/usr/bin/env bash
#
# morning.sh — the local half of the morning routine, as ONE terminal command.
#
# The Brain board (https://<org>.github.io/PyAutoBrain/ — rendered by
# board/_board.py, published by brain_board.yml) carries every remote signal
# the old /wake_up skill assembled: overnight runs, readiness, community,
# resume, upkeep. The two steps a cloud render cannot do are the ones that
# touch YOUR checkout — sync and clean-slate. This script is exactly those two
# steps, so the morning is: run this in a terminal, then open the board.
#
#   bash PyAutoBrain/bin/morning.sh            # sync + clean + publish,
#                                              #   then board URL
#   bash PyAutoBrain/bin/morning.sh --digest   # also print the board's
#                                              #   markdown digest (needs gh)
#   bash PyAutoBrain/bin/morning.sh --no-publish  # skip the dev-box publish
#   DRY_RUN=1 bash PyAutoBrain/bin/morning.sh  # preview clean-slate only
#
# To run overnight automatically (so the board is fresh on waking), schedule
# it on this machine once: bash PyAutoBrain/bin/morning_timer.sh install
#
# Both steps are the recoverable, git-aware ones /wake_up auto-ran (its
# guardrail): sync skips any repo with real uncommitted work; clean-slate
# deletes only untracked REGENERABLE artifacts and reports orphans instead of
# removing them. Nothing else is deleted, edited, or bumped here.

set -u

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

echo "== morning: sync every repo to main (ff-only; real work is skipped) =="
bash "$HERE/pull_all_main.sh"

echo
echo "== morning: clean slate (untracked regenerable artifacts + cruft) =="
bash "$HERE/clean_slate.sh"

if [ "${1:-}" != "--no-publish" ]; then
    echo
    echo "== morning: publish the dev-box observation (hygiene + worktrees) =="
    # Best-effort: the board just shows an older stamp if this leg fails.
    # The push itself triggers brain_board.yml, so the board refreshes with
    # this morning's local observations a minute later.
    bash "$HERE/../board/board.sh" publish \
        || echo "morning: dev-box publish skipped (see above) — the board keeps its last stamp"
fi

echo
echo "== morning: done — the rest of the routine is on the board =="
# Board URL from the checkout's own remote (no hardcoded org).
origin="$(git -C "$HERE/.." remote get-url origin 2>/dev/null || true)"
owner="$(printf '%s' "$origin" | sed -E 's#\.git$##; s#.*[:/]([^/:]+)/[^/]+$#\1#')"
if [ -n "$owner" ]; then
    echo "   https://$(printf '%s' "$owner" | tr '[:upper:]' '[:lower:]').github.io/PyAutoBrain/"
fi

if [ "${1:-}" = "--digest" ]; then
    echo
    bash "$HERE/../board/board.sh" || echo "morning: board digest unavailable (gh auth?)"
fi
