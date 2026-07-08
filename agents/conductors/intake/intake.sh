#!/usr/bin/env bash
# agents/conductors/intake/intake.sh — the Intake Agent (Conception Agent).
#
# Intake is where a task is CONCEIVED: it turns raw input — a text-vomit idea, a
# bug report, an ideas.md bullet — into a formal, grouped, headed PyAutoMind
# prompt under <work-type>/<target>/<name>.md. It sits BEFORE create_issue /
# start_dev: it files a prompt, it never starts development.
#
#   raw input  ->  Intake Agent  ->  PyAutoMind <work-type>/<target>/<name>.md
#
# Boundary: /route infers a work-type and DISPATCHES (starts dev now); intake
# infers a work-type and FILES a prompt (defers). Low-confidence classification
# lands in triage/ (the existing unclassified bucket, reused). Difficulty is
# owned here and persisted into the header via the shared sizing faculty, so the
# Feature Agent later trusts the same number.
#
# Modes:
#   intake "<raw text>"          classify raw text (bare text => classify mode)
#   intake classify --file P     classify the contents of a file
#   intake ideas                 scan ideas.md; propose one prompt per bullet
#
# Flags (place before the subcommand; both default OFF):
#   --apply    write the formal prompt file(s); without it, dry-run only
#   --json     emit the machine-readable IntakeDecision
#
# The analysis core lives in _intake.py (stdlib-only). It writes ONLY under
# --apply; every other path is read-only.
#
# Exit codes: 0 produced a decision · 4 no input / could-not-resolve mind ·
# 5 bad usage.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

as_json=0
apply=0
forward=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) sed -n '2,34p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --json) as_json=1; shift ;;
    --apply) apply=1; shift ;;
    *) forward+=("$1"); shift ;;
  esac
done

mind="$(resolve_mind)" || exit 4

if [[ ${#forward[@]} -eq 0 ]]; then
  echo "intake: nothing to do — give raw text, 'classify --file P', or 'ideas'." >&2
  exit 5
fi
# A bare first token that is not a known subcommand -> classify mode on the rest,
# so `intake "raw idea"` and `intake --file p.md` both work as the front door.
if [[ "${forward[0]}" != "classify" && "${forward[0]}" != "ideas" ]]; then
  forward=(classify "${forward[@]}")
fi

flags=()
[[ "$as_json" -eq 1 ]] && flags+=(--json)
[[ "$apply" -eq 1 ]] && flags+=(--apply)

exec python3 "$HERE/_intake.py" --mind "$mind" "${flags[@]}" "${forward[@]}"
