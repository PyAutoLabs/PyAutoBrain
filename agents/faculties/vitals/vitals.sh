#!/usr/bin/env bash
# agents/faculties/vitals/vitals.sh — the vitals faculty (a PyAutoBrain
# read-only reasoning capability). It reads the Heart's pulse.
#
# Reasons over the PyAutoHeart monitoring surface. By default it runs one
# refresh cycle and renders the unified dashboard card (the same board every
# other surface shows — the authoritative readiness verdict at its head, plus
# every check and the release-validation state). Any subcommand
# is forwarded straight to `pyauto-heart`, so this faculty is a thin, named
# driver of Heart rather than a second implementation of any check. The Brain
# reasons about health; PyAutoHeart measures it. This faculty only *opines* —
# it never dispatches or mutates; it is the single component that talks to Heart,
# and the conductors (build, release, feature, health) consult it.
#
# Usage:
#   vitals.sh                 # one tick, then render the unified dashboard card
#   vitals.sh status          # forward: pyauto-heart status
#   vitals.sh watch [secs]    # forward: pyauto-heart watch (continuous)
#   vitals.sh --scope <repo>[,...]     # verdict scoped to those repos (+ --json)
#   vitals.sh <subcommand>... # forward verbatim to pyauto-heart
#
# WITHOUT THE HEART CLI. A web/mobile session never holds the PyAutoHeart
# checkout, so `resolve_heart` failed and this faculty exited — the ship gate
# then ran with no verdict at all, which is worse than a qualified one. When the
# CLI cannot be resolved we read the Heart's PUBLISHED board instead
# (`_vitals.py`, the same Pages JSON the Brain board reads). It is not a live
# tick and says so on every line.
#
# --scope ALWAYS reads the published board, CLI or no CLI: the per-repo
# blockers live in the Heart's `board.json`, and that is the surface that can
# say a RED belongs to some other repo's workspace smoke and not to the library
# branch asking. The output names its source so the two are never confused.
#
# The no-arg card is the SAME unified board every other surface shows (one
# renderer in heart/dashboard.py) — verdict, score, top blockers, and the
# release-validation state — not raw verdict JSON. On a phone the reasoning
# agent pulls `pyauto-heart dashboard --json` / `--md` for the same card.
#
# Future: several vitals faculties may each read a different slice of Heart
# (CI, worktree drift, timing, ...). For now this single faculty covers the whole
# surface via pyauto-heart.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

PAGES_READER="$HERE/_vitals.py"

# This faculty's OWN flags (--scope/--json), recognised only when they are the
# whole argument list. Anything else — `dashboard --json`, `readiness --json` —
# is a pyauto-heart subcommand line and is forwarded verbatim, unread: stripping
# a `--json` that belonged to Heart would silently turn a machine card into a
# human one.
scope=""; want_json=0; ours=1; rest=("$@")
while [[ $# -gt 0 ]]; do
  case "$1" in
    --scope)   scope="${2:-}"; shift; shift || true ;;
    --scope=*) scope="${1#--scope=}"; shift ;;
    --json)    want_json=1; shift ;;
    *)         ours=0; break ;;
  esac
done
if [[ "$ours" -eq 0 ]]; then scope=""; want_json=0; else rest=(); fi

pages_read() {
  local args=()
  [[ -n "$scope" ]] && args+=(--scope "$scope")
  [[ "$want_json" -eq 1 ]] && args+=(--json)
  python3 "$PAGES_READER" "${args[@]}"
}

# A scoped read is a published-board question by construction — answer it and
# stop, so a scoped verdict is never half live and half published.
if [[ -n "$scope" ]]; then
  pages_read; exit $?
fi

if ! heart="$(resolve_heart)"; then
  echo "== vitals faculty: no pyauto-heart here — reading the published Heart board ==" >&2
  pages_read; exit $?
fi

# A bare `--json` with the CLI here is a live machine card, not a published one.
if [[ "$want_json" -eq 1 ]]; then exec "$heart" dashboard --json; fi

set -- "${rest[@]+"${rest[@]}"}"

if [[ $# -eq 0 ]]; then
  echo "== vitals faculty: refreshing PyAutoHeart state =="
  "$heart" tick
  echo
  # Render the ONE unified board (readiness verdict + every check + the
  # release-validation state), not just the raw verdict. Same renderer as the
  # web page and the mobile card, so the surfaces cannot disagree.
  "$heart" dashboard
  # ...and, under it, the release freeze window if one is open. It is NOT part
  # of the verdict (a freeze is not a health problem) and Heart is its only
  # writer — this faculty reads the line Heart prints and passes it on. An
  # older Heart without the verb prints nothing, which is not an error.
  "$heart" freeze --show 2>/dev/null | grep '^FROZEN:' || true
  exit 0
fi

exec "$heart" "$@"
