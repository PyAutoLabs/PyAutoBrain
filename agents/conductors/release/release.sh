#!/usr/bin/env bash
# agents/release/release.sh — the release conductor.
#
# Two jobs:
#   release rehearse|validate      — release-VALIDATION orchestration, this
#                                    conductor's own machinery (rehearse.sh /
#                                    validate.sh).
#   release [--force] [--accept-red=<reason>]... [-- <args>]
#                                  — the release door: delegates the readiness
#                                    gate AND execution to the Build Agent's
#                                    release mode (build.sh --mode release),
#                                    the single gate implementation. GREEN
#                                    proceeds, YELLOW needs --force, RED
#                                    blocks unless every current RED reason is
#                                    authorized verbatim via --accept-red (an
#                                    explicit, per-invocation human decision
#                                    that does NOT alter Heart's verdict);
#                                    <args> forward to pre_build.
#
# This conductor holds no second copy of the gate logic — one gate
# implementation lives in the Build Agent; this door routes through it.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

# `release rehearse ...` drives the M2 release-VALIDATION rehearsal (Stage 2
# alone: dispatch the TestPyPI rehearsal, ingest the report into Heart, consult
# the vitals faculty) — distinct from the real-release delegation below.
if [[ "${1:-}" == "rehearse" ]]; then
  shift
  exec bash "$HERE/rehearse.sh" "$@"
fi

# `release validate ...` drives the M4 FULL Stages 0-3 release-validation
# orchestrator (preflight -> unit -> rehearse -> integrate -> ingest -> verdict).
# It sequences rehearse.sh's Stage-2 pieces and adds Stage 0/1 preflight + Stage 3.
if [[ "${1:-}" == "validate" ]]; then
  shift
  exec bash "$HERE/validate.sh" "$@"
fi

# `release nightly ...` is the scheduled-nightly driver — the activity-gated,
# Heart-GREEN-gated unattended live-release path (design:
# PyAutoHands/docs/nightly_release_design.md; standing grant: ../../AUTONOMY.md).
# Local runs default to dry-run; the cron lives in
# .github/workflows/nightly-release.yml.
if [[ "${1:-}" == "nightly" ]]; then
  shift
  exec bash "$HERE/nightly.sh" "$@"
fi

force=0
forward=()
accept_red=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) force=1; shift ;;
    --accept-red)
      [[ $# -ge 2 ]] || { echo "release conductor: --accept-red needs a verbatim RED reason" >&2; exit 5; }
      accept_red+=("$2"); shift 2 ;;
    --accept-red=*) accept_red+=("${1#*=}"); shift ;;
    --) shift; forward=("$@"); break ;;
    *) forward+=("$1"); shift ;;
  esac
done

echo "== release conductor: delegating gate + execution to the Build Agent (release mode) =="

# One gate implementation, not two: the Build Agent's release mode refreshes
# health via the vitals faculty, applies GREEN / YELLOW(--force) / RED, and on
# a pass runs `autohands pre_build` (which dispatches release.yml).
args=(--mode release)
[[ "$force" -eq 1 ]] && args+=(--force)
for _a in ${accept_red[@]+"${accept_red[@]}"}; do args+=("--accept-red=$_a"); done
exec bash "$HERE/../build/build.sh" "${args[@]}" -- "${forward[@]}"
