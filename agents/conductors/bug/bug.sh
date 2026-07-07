#!/usr/bin/env bash
# agents/conductors/bug/bug.sh — the Bug Agent (a PyAutoBrain conductor).
#
# The Bug Agent is the *immune system* of PyAutoBrain. It recognises a pathogen (a
# bug, regression, failing test or PyAutoHeart finding), tells it from benign self,
# types the threat, recalls prior cases (PyAutoMemory), and mounts a *targeted*
# response — a repair plan the existing workflow executes. It does NOT edit source:
#
#   report/finding  ->  Bug Agent  ->  start_dev
#                                   ->  start_library / ship_library
#                                   ->  start_workspace / ship_workspace
#
# Like the Feature Agent it consults the sibling *vitals* faculty (and only the
# vitals faculty talks to the Heart organ); it never queries Heart directly. Its
# fundamental principle is a precise response with NO AUTOIMMUNITY: user-facing
# workspace scripts are documentation, so it prefers a general library-source fix.
#
# Modes:
#   specific   classify a named PyAutoMind bug prompt and plan the fix.
#   selection  choose the best next bug (no task named) — severity-first.
#   difficulty-constrained  select under a constraint (--difficulty/--model/…).
#   health     read the live vitals verdict AND scan filed PyAutoHeart issues.
#
# Usage:
#   bug.sh <bug/target/name.md>                   # specific mode
#   bug.sh select [--difficulty small|medium|large|easy]
#                 [--model weak|strong] [--budget] [--ambitious]
#                 [--impact] [--limit N]
#   bug.sh health                                 # vitals verdict + Heart issue scan
#   bug.sh [--json] ...                           # machine-readable BugDecision
#   bug.sh [--check-health] ...                   # also annotate with the vitals verdict
#
# The analysis core lives in _bug.py (stdlib-only, never writes; reuses _feature.py).
#
# Exit codes: 0 produced a decision · 4 no prompts / could-not-resolve · 5 bad usage.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

# The GitHub repo where PyAutoHeart files its health findings (health-issue mode).
HEART_ISSUES_REPO="${PYAUTO_HEART_REPO:-PyAutoLabs/PyAutoHeart}"

check_health=0
as_json=0
forward=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --check-health) check_health=1; shift ;;
    --json) as_json=1; shift ;;
    *) forward+=("$1"); shift ;;
  esac
done

mind="$(resolve_mind)" || exit 4
memory="$(resolve_memory 2>/dev/null || true)"

# Normalise the subcommand. Nothing given -> selection. A bare path (or any first
# token that is not a known subcommand or flag) -> specific mode on that task.
if [[ ${#forward[@]} -eq 0 ]]; then
  forward=(select)
elif [[ "${forward[0]}" != "select" && "${forward[0]}" != "specific" \
        && "${forward[0]}" != "health" && "${forward[0]}" != --* ]]; then
  forward=(specific "${forward[@]}")
fi

json_flag=()
[[ "$as_json" -eq 1 ]] && json_flag=(--json)

# --- health-issue mode: the two health inputs --------------------------------
# (1) the live vitals verdict (via the vitals faculty, never Heart directly), and
# (2) the durable findings Heart *filed* as GitHub issues. Both feed _bug.py, which
# classifies each and routes real defects to PyAutoMind/bug/health_fixes/.
if [[ "${forward[0]}" == "health" ]]; then
  echo "== bug agent: health-issue mode =="
  verdict="$(consult_vitals_verdict)"
  echo "   live vitals verdict: $verdict"
  issues_json="$(mktemp)"
  trap 'rm -f "$issues_json"' EXIT
  if command -v gh >/dev/null 2>&1; then
    echo "   scanning filed PyAutoHeart issues: https://github.com/$HEART_ISSUES_REPO/issues"
    gh issue list --repo "$HEART_ISSUES_REPO" --state open --limit 50 \
       --json number,title,labels,url > "$issues_json" 2>/dev/null \
       || echo "[]" > "$issues_json"
  else
    echo "   (gh not available — skipping the filed-issue scan)"
    echo "[]" > "$issues_json"
  fi
  echo
  exec python3 "$HERE/_bug.py" --mind "$mind" --memory "$memory" \
    "${json_flag[@]}" health --verdict "$verdict" --heart-issues "$issues_json"
fi

# Optionally annotate a specific/selection decision with the vitals verdict
# (society-of-agents). This does not gate the decision — it informs it.
if [[ "$check_health" -eq 1 ]]; then
  echo "== bug agent: consulting vitals faculty for tree readiness =="
  echo "   readiness verdict: $(consult_vitals_verdict)"
  echo
fi

exec python3 "$HERE/_bug.py" --mind "$mind" --memory "$memory" \
  "${json_flag[@]}" "${forward[@]}"
