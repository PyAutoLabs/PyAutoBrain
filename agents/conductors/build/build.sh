#!/usr/bin/env bash
# agents/build/build.sh — the build agent (the 2nd canonical PyAutoBrain agent).
#
# The Build Agent is the executive / orchestration layer for execution work. It
# does NOT build software itself — PyAutoHands does. The Build Agent decides
# whether building should happen, what to build, which PyAutoHands capability to
# invoke, and whether to proceed or stop. It reasons; PyAutoHands executes.
#
# Call chain (the Brain coordinating multiple organs):
#
#   Mind -> Build Agent -> vitals faculty -> Heart -> GREEN/YELLOW/RED
#                       -> Build Agent -> PyAutoHands (execute)
#
# Note the consult step goes through the *sibling vitals faculty*, not Heart
# directly: Brain agents consult one another (a society of reasoning agents),
# and only the vitals faculty talks to the Heart organ.
#
# Modes (one agent now, clean seam for a future Release Agent):
#   build    generic execution (generate notebooks, run scripts, aggregate).
#            Lenient gate: GREEN/YELLOW proceed, RED aborts.
#   deploy   publish generated artifacts. Cautious gate: GREEN proceeds,
#            YELLOW needs --force, RED aborts.
#   release  high-stakes release execution (pre_build, tag, release notes).
#            Strict gate: refreshes health first; GREEN proceeds, YELLOW needs
#            --force, RED aborts. Release reasoning is isolated here so it can
#            later split into its own PyAutoBrain Release Agent.
#
# Usage:
#   build.sh [--mode build|deploy|release] [--force] [--accept-red=<reason>]...
#            [--dry-run] [--json] [<action>] [-- <args forwarded to autobuild>]
#
#   --force            proceed on a YELLOW verdict (deploy/release).
#   --accept-red=<r>   authorize proceeding despite the RED reason <r>. Repeatable.
#                      Each <r> must match a readiness red_reason VERBATIM; any
#                      RED reason not covered by an --accept-red still blocks, so
#                      an override authorized for one problem never silently
#                      waives a different one that appeared later. Heart's verdict
#                      is NOT changed — it still reports RED; this records that a
#                      human accepted those exact reasons. Never ambient: it must
#                      be passed explicitly per invocation.
#   --dry-run          reason + plan only; emit the BuildDecision, do not execute.
#   --json             emit the BuildDecision as JSON only (machine-readable).
#
# Exit codes: 0 proceeded/delegated (or dry-run) · 2 yellow blocked (use
# --force) · 3 red blocked · 4 unknown/could-not-consult · 5 invalid mode/action.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

# ----- mode -> allowed actions, default action, gate strictness -----
# Actions are PyAutoHands capabilities. The Build Agent calls them; it never
# reimplements them. Health-shim commands (verify_install, url_check, watch,
# status, tick, fix) are deliberately NOT routable here — those are Heart's
# surface, reached through the vitals faculty, never re-owned by Build.
BUILD_ACTIONS="generate run run_python run_all script_matrix aggregate_results slow_skip_check repro_command bump_colab_urls"
DEPLOY_ACTIONS="generate bump_colab_urls"
RELEASE_ACTIONS="pre_build tag_and_merge generate_release_notes create_analysis_issue aggregate_results"
HEALTH_SHIMS="verify_install url_check watch status tick fix"

mode="build"
force=0
dry_run=0
json_only=0
action=""
forward=()
accept_red=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      [[ $# -ge 2 ]] || { echo "build agent: --mode needs a value (build|deploy|release)" >&2; exit 5; }
      mode="$2"; shift 2 ;;
    --mode=*) mode="${1#*=}"; shift ;;
    --force) force=1; shift ;;
    --accept-red)
      [[ $# -ge 2 ]] || { echo "build agent: --accept-red needs a verbatim RED reason" >&2; exit 5; }
      accept_red+=("$2"); shift 2 ;;
    --accept-red=*) accept_red+=("${1#*=}"); shift ;;
    --dry-run) dry_run=1; shift ;;
    --json) json_only=1; shift ;;
    -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --) shift; forward=("$@"); break ;;
    -*) echo "build agent: unknown flag '$1'" >&2; exit 5 ;;
    *) if [[ -z "$action" ]]; then action="$1"; else forward+=("$1"); fi; shift ;;
  esac
done

case "$mode" in
  build)   allowed="$BUILD_ACTIONS";   default_action="run_all" ;;
  deploy)  allowed="$DEPLOY_ACTIONS";  default_action="generate" ;;
  release) allowed="$RELEASE_ACTIONS"; default_action="pre_build" ;;
  *) echo "build agent: unknown mode '$mode' (build|deploy|release)" >&2; exit 5 ;;
esac
[[ -z "$action" ]] && action="$default_action"

# Reject health-shim commands with a pointer to the right organ.
if [[ " $HEALTH_SHIMS " == *" $action "* ]]; then
  echo "build agent: '$action' is a health concern owned by PyAutoHeart, not a" >&2
  echo "  build action. Consult it via:  pyauto-brain vitals $action" >&2
  exit 5
fi
if [[ " $allowed " != *" $action "* ]]; then
  echo "build agent: action '$action' is not valid in '$mode' mode." >&2
  echo "  Allowed: $allowed" >&2
  exit 5
fi

# ----- consult the sibling vitals faculty (not Heart directly) -----
[[ "$json_only" -eq 1 ]] || echo "== build agent ($mode): consulting vitals faculty for readiness =="
if [[ "$mode" == "release" ]]; then
  verdict="$(consult_vitals_verdict --refresh)"
else
  verdict="$(consult_vitals_verdict)"
fi

# ----- reason: map (mode, verdict) -> decision -----
# An unknown verdict collapses to YELLOW (caution), never to GREEN or RED.
eff="$verdict"
[[ "$eff" == "unknown" ]] && eff="yellow"

decision="" ; decision_code=0
warnings=() ; blockers=() ; follow_up=()

[[ "$verdict" == "unknown" ]] && warnings+=("Readiness verdict unknown; treated as YELLOW. Run 'pyauto-brain vitals' to refresh.")

case "$eff" in
  red)
    if [[ ${#accept_red[@]} -eq 0 ]]; then
      decision="abort"; decision_code=3
      blockers+=("PyAutoHeart reports RED. Resolve the blockers (see 'pyauto-brain vitals') before $mode work.")
      blockers+=("To authorize proceeding anyway, re-run quoting each RED reason verbatim: --accept-red=\"<reason>\".")
    else
      # Verbatim-match every current RED reason against the authorized set. An
      # unmatched reason still blocks: an override is consent to SPECIFIC named
      # problems, never a blanket bypass of whatever RED happens to be current.
      _red_reasons=()
      while IFS= read -r _r; do
        [[ -n "$_r" ]] && _red_reasons+=("$_r")
      done < <(consult_vitals_red_reasons)

      _unaccepted=()
      for _r in ${_red_reasons[@]+"${_red_reasons[@]}"}; do
        _matched=0
        for _a in ${accept_red[@]+"${accept_red[@]}"}; do
          [[ "$_r" == "$_a" ]] && { _matched=1; break; }
        done
        [[ "$_matched" -eq 0 ]] && _unaccepted+=("$_r")
      done

      if [[ ${#_red_reasons[@]} -eq 0 ]]; then
        # RED with no enumerable reasons: nothing to authorize against, so an
        # override cannot be verified. Fail closed.
        decision="abort"; decision_code=3
        blockers+=("PyAutoHeart reports RED but returned no enumerable red_reasons; an --accept-red override cannot be verified. Failing closed.")
      elif [[ ${#_unaccepted[@]} -gt 0 ]]; then
        decision="abort"; decision_code=3
        blockers+=("PyAutoHeart reports RED. ${#_unaccepted[@]} reason(s) are NOT covered by --accept-red:")
        for _r in ${_unaccepted[@]+"${_unaccepted[@]}"}; do blockers+=("  - $_r"); done
        blockers+=("Quote each verbatim with --accept-red=\"<reason>\" to authorize it, or resolve it.")
      else
        decision="proceed-with-override"; decision_code=0
        warnings+=("RED OVERRIDDEN by explicit human authorization ($mode mode).")
        warnings+=("Heart's verdict is UNCHANGED (still RED) — this is a recorded human decision, not a clean bill of health.")
        warnings+=("Accepted RED reason(s):")
        for _r in ${_red_reasons[@]+"${_red_reasons[@]}"}; do warnings+=("  - $_r"); done
        follow_up+=("Record the accepted RED reason(s) in the release notes / release record so the artifact is self-documenting about what it shipped with.")
      fi
    fi
    ;;
  yellow)
    if [[ "$mode" == "build" ]]; then
      decision="proceed-with-caution"; decision_code=0
      warnings+=("Health is YELLOW; build mode proceeds, but review warnings before release-grade work.")
    else
      if [[ "$force" -eq 1 ]]; then
        decision="proceed-with-caution"; decision_code=0
        warnings+=("Health is YELLOW; proceeding under --force ($mode mode).")
      else
        decision="abort"; decision_code=2
        blockers+=("Health is YELLOW and $mode mode requires GREEN. Re-run with --force to accept the caution.")
      fi
    fi
    ;;
  green)
    decision="proceed"; decision_code=0
    ;;
  *)
    decision="abort"; decision_code=4
    blockers+=("Could not obtain a readiness verdict ('$verdict').")
    ;;
esac

# ----- execution plan -----
plan_cmd="autobuild $action"
[[ ${#forward[@]} -gt 0 ]] && plan_cmd+=" ${forward[*]}"
plan=("$plan_cmd")

if [[ "$mode" == "release" ]]; then
  follow_up+=("This release mode is the single gate+execution path; the release conductor delegates plain releases through it and owns rehearse/validate.")
fi

# ----- emit the BuildDecision (structured) -----
summary="$decision via '$plan_cmd' (health=$verdict, mode=$mode)"
[[ "$dry_run" -eq 1 ]] && summary="DRY-RUN: would $summary"

emit_decision() {
  HEALTH="$verdict" MODE="$mode" ACTION="$action" DECISION="$decision" \
  PLAN="${plan[*]}" SUMMARY="$summary" DRYRUN="$dry_run" \
  WARNINGS="$(printf '%s\n' "${warnings[@]:-}")" \
  BLOCKERS="$(printf '%s\n' "${blockers[@]:-}")" \
  FOLLOWUP="$(printf '%s\n' "${follow_up[@]:-}")" \
  python3 -c '
import json, os
def lines(k):
    return [x for x in os.environ.get(k, "").splitlines() if x.strip()]
print(json.dumps({
    "agent": "build",
    "mode": os.environ["MODE"],
    "requested_action": os.environ["ACTION"],
    "health_status": os.environ["HEALTH"],
    "decision": os.environ["DECISION"],
    "execution_plan": [os.environ["PLAN"]] if os.environ.get("PLAN") else [],
    "execution_summary": os.environ["SUMMARY"],
    "warnings": lines("WARNINGS"),
    "blockers": lines("BLOCKERS"),
    "follow_up_recommendations": lines("FOLLOWUP"),
    "dry_run": os.environ.get("DRYRUN") == "1",
}, indent=2))
'
}

if [[ "$json_only" -eq 1 ]]; then
  emit_decision
else
  echo "-- BuildDecision --"
  emit_decision
  echo
fi

# ----- act on the decision -----
if [[ "$decision_code" -ne 0 ]]; then
  [[ "$json_only" -eq 1 ]] || echo "build agent: $decision — not executing." >&2
  exit "$decision_code"
fi

if [[ "$dry_run" -eq 1 ]]; then
  [[ "$json_only" -eq 1 ]] || echo "build agent: dry-run, not executing '$plan_cmd'."
  exit 0
fi

autobuild="$(resolve_autobuild)" || exit $?
[[ "$json_only" -eq 1 ]] || echo "== exec: $plan_cmd =="
exec "$autobuild" "$action" "${forward[@]}"
