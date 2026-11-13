#!/usr/bin/env bash
# agents/release/rehearse.sh — the release-VALIDATION driver (M2).
#
# This is the Brain Release Agent's dispatch/poll/ingest driver for a release
# *rehearsal*, distinct from `release.sh` (which drives a real release on GREEN).
# It orchestrates the four-stage release-validation pipeline's build+ingest half:
#
#   dispatch M1 TestPyPI rehearsal (Build's release.yml, rehearsal=true)
#     -> poll to completion
#     -> download the `testpypi-rehearsal-version` artifact
#     -> capture the current main HEAD sha of each library
#     -> hand it all to `pyauto-heart validate --ingest`   (Heart measures)
#     -> consult the vitals faculty for the verdict           (vitals judges)
#
# BOUNDARY. Dispatch/poll/download are GitHub actions, done via Brain's MCP
# GitHub tools (cloud/mobile sessions have no `gh`). Bash cannot call MCP, so
# this script owns the *local* half — ingest + consult + decision — and EMITS
# the MCP dispatch/poll/download plan for the agent to execute (see AGENTS.md).
# Heart never dispatches and never mutates a repo; all GitHub credentials/actions
# live here in the Release Agent, never in Heart.
#
# Usage:
#   # 1. print the MCP dispatch/poll/download plan (the agent executes it):
#   rehearse.sh [--ref main] [--minor N] [--json]
#
#   # 2. after the artifacts are downloaded, ingest + get the verdict:
#   rehearse.sh --ingest <artifacts-dir> [--commit-shas FILE] [--profile P]
#               [--force] [--json]
#
# Reuse hooks (used by the M4 full orchestrator, agents/release/validate.sh, so
# Stage 2's dispatch/capture-heads plan is defined here in ONE place):
#   --next-plan-cmd CMD   override the phase-1 plan's final "continue" step
#                         (default: `release rehearse --ingest ...`).
#   --mode-label NAME     stamp the phase-2 verdict JSON's "mode" (default:
#                         "rehearse"; the orchestrator passes "validate").
#
# Exit codes (ingest phase): 0 green · 2 yellow (use --force) · 3 red · 4 unknown
#   · 1 could not ingest. Plan phase always exits 0.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

# The Build repo + workflow the rehearsal is dispatched against (M1).
BUILD_REPO="PyAutoLabs/PyAutoHands"
RELEASE_WORKFLOW="release.yml"
REHEARSAL_ARTIFACT="testpypi-rehearsal-version"
# The 6 libraries (PyAutoCTI joined 2026-11-04, cti-upkeep phase 1) whose main HEADs the rehearsal is built from; readiness
# confirms the ingested report's commit_shas against these. Bare names here
# are intentional: `commit_shas.json` keys (and heart/readiness.py's
# _GATE_SHA_LIBS) are bare repo names, e.g. "PyAutoNerves", not "owner/repo".
# LIBRARIES_OWNER qualifies them ONLY for the get_commit MCP calls below
# (same convention as BUILD_REPO) — all six libraries live under this one
# GitHub org in this ecosystem, but qualifying explicitly removes any
# ambiguity for the agent executing the emitted plan.
LIBRARIES=(PyAutoNerves PyAutoFit PyAutoArray PyAutoGalaxy PyAutoLens PyAutoCTI)
LIBRARIES_OWNER="PyAutoLabs"

ref="main"
minor=""
ingest_dir=""
commit_shas_file=""
profile=""
force=0
json_only=0
# The command the emitted phase-1 plan tells the agent to run once the Stage-2
# artifacts have landed. Default = ingest here (the Stage-2-only path). The M4
# full-orchestrator (`release validate`) overrides it via --next-plan-cmd so the
# same dispatch/poll/download/capture-heads plan continues into Stage 3 instead —
# this is the single reuse hook that keeps Stage 2's plan defined in ONE place.
next_cmd="pyauto-brain release rehearse --ingest <dir> --commit-shas <dir>/commit_shas.json"
# The "mode" stamped on the phase-2 verdict JSON. Overridden to "validate" when
# the full orchestrator delegates its final ingest+verdict step here.
mode_label="rehearse"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref) ref="$2"; shift 2 ;;
    --ref=*) ref="${1#*=}"; shift ;;
    --minor) minor="$2"; shift 2 ;;
    --minor=*) minor="${1#*=}"; shift ;;
    --ingest) ingest_dir="$2"; shift 2 ;;
    --ingest=*) ingest_dir="${1#*=}"; shift ;;
    --commit-shas) commit_shas_file="$2"; shift 2 ;;
    --commit-shas=*) commit_shas_file="${1#*=}"; shift ;;
    --profile) profile="$2"; shift 2 ;;
    --profile=*) profile="${1#*=}"; shift ;;
    --next-plan-cmd) next_cmd="$2"; shift 2 ;;
    --next-plan-cmd=*) next_cmd="${1#*=}"; shift ;;
    --mode-label) mode_label="$2"; shift 2 ;;
    --mode-label=*) mode_label="${1#*=}"; shift ;;
    --force) force=1; shift ;;
    --json) json_only=1; shift ;;
    -h|--help)
      awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "${BASH_SOURCE[0]}"
      exit 0 ;;
    *) echo "release rehearse: unknown arg '$1'" >&2; exit 5 ;;
  esac
done

# ---------------------------------------------------------------------------
# Phase 1: emit the MCP dispatch/poll/download plan (no --ingest given).
# ---------------------------------------------------------------------------
if [[ -z "$ingest_dir" ]]; then
  inputs='{"rehearsal": true}'
  [[ -n "$minor" ]] && inputs='{"rehearsal": true, "minor_version": "'"$minor"'"}'

  if [[ "$json_only" -eq 1 ]]; then
    REF="$ref" INPUTS="$inputs" REPO="$BUILD_REPO" WF="$RELEASE_WORKFLOW" \
    ART="$REHEARSAL_ARTIFACT" LIBS="${LIBRARIES[*]}" LIBS_OWNER="$LIBRARIES_OWNER" \
    NEXT_CMD="$next_cmd" python3 -c '
import json, os
libs = os.environ["LIBS"].split()
owner = os.environ["LIBS_OWNER"]
print(json.dumps({
  "agent": "release", "mode": "rehearse", "phase": "dispatch-plan",
  "steps": [
    {"step": "dispatch", "mcp_tool": "mcp__github__actions_run_trigger",
     "repo": os.environ["REPO"], "workflow": os.environ["WF"],
     "ref": os.environ["REF"], "inputs": json.loads(os.environ["INPUTS"])},
    {"step": "poll", "mcp_tool": "mcp__github__actions_get",
     "until": "status == completed", "note": "artifact exists IFF all 5 wheels built+installed"},
    {"step": "download", "artifact": os.environ["ART"],
     "note": "download into an artifacts dir (rehearsal.json + testpypi_version.txt)"},
    {"step": "commit-shas-from-record", "source": "rehearsal.json",
     "note": "write rehearsal.json commit_shas (the commits the rehearsal BUILT, "
             "keyed by BARE repo name) to commit_shas.json in the dir, and keep "
             "its run_id: a live release.yml needs rehearsal_run_id "
             "(PyAutoHands#337). Never re-read main HEADs - main may have moved. "
             "The ingest phase does this itself when rehearsal.json is present."},
    {"step": "next", "cmd": os.environ["NEXT_CMD"]},
  ],
}, indent=2))
'
    exit 0
  fi

  cat <<EOF
== release agent: release-validation rehearsal (dispatch plan) ==

Bash cannot call GitHub; execute these steps with Brain's MCP GitHub tools
(cloud/mobile has no gh). Heart never dispatches — this is the Release Agent's job.

1. DISPATCH the M1 TestPyPI rehearsal:
     mcp__github__actions_run_trigger
       repo:     $BUILD_REPO
       workflow: $RELEASE_WORKFLOW
       ref:      $ref
       inputs:   $inputs

2. POLL the run to completion (mcp__github__actions_get / actions_list).
   The '$REHEARSAL_ARTIFACT' artifact is produced IFF all six wheels built,
   uploaded, and installed from TestPyPI — its presence IS the success signal.

3. DOWNLOAD the '$REHEARSAL_ARTIFACT' artifact into an artifacts directory
   (it contains rehearsal.json + testpypi_version.txt).

4. RECORD the rehearsed commits: copy rehearsal.json's "commit_shas" object
   ({bare_repo_name: sha}, e.g. "PyAutoNerves") to <dir>/commit_shas.json, and
   keep its "run_id" — the live release.yml needs it as rehearsal_run_id
   (PyAutoHands#337: a release builds the rehearsed commits). Never re-read the
   library main HEADs: main may have moved since the rehearsal. (The ingest
   phase writes commit_shas.json itself when rehearsal.json is in <dir>.)

5. NEXT (continue the pipeline):
     $next_cmd

After the final ingest, the vitals faculty (read-only) reports GREEN/YELLOW/RED
from the freshly-ingested validation_report — it does NOT dispatch anything.
EOF
  exit 0
fi

# ---------------------------------------------------------------------------
# Phase 2: ingest the downloaded artifacts, then consult the vitals faculty.
# ---------------------------------------------------------------------------
if [[ ! -d "$ingest_dir" && ! -f "$ingest_dir" ]]; then
  echo "release rehearse: artifacts path '$ingest_dir' not found" >&2
  exit 1
fi

heart="$(resolve_heart)" || exit $?

# The rehearsal's own record is the commit_shas authority (PyAutoHands#337):
# when rehearsal.json is in the artifacts, commit_shas.json is written from it,
# and a --commit-shas file that disagrees with it refuses.
if [[ -d "$ingest_dir" ]]; then
  source "$HERE/_nightly_lib.sh"
  if record_run="$(rehearsal_record "$ingest_dir" "$ingest_dir/.commit_shas.record.json" 2>/dev/null)"; then
    if [[ -n "$commit_shas_file" && "$commit_shas_file" != "$ingest_dir/commit_shas.json" ]] \
       && ! python3 -c 'import json,sys; sys.exit(json.load(open(sys.argv[1])) != json.load(open(sys.argv[2])))' \
            "$commit_shas_file" "$ingest_dir/.commit_shas.record.json"; then
      echo "release rehearse: --commit-shas $commit_shas_file disagrees with rehearsal.json (run $record_run) — the record is the authority" >&2
      exit 1
    fi
    mv "$ingest_dir/.commit_shas.record.json" "$ingest_dir/commit_shas.json"
    commit_shas_file="$ingest_dir/commit_shas.json"
    [[ "$json_only" -eq 1 ]] || echo "== release agent: commit_shas from rehearsal.json (run $record_run) =="
  fi
fi

ingest_args=(validate --ingest "$ingest_dir")
[[ -n "$commit_shas_file" ]] && ingest_args+=(--commit-shas "$commit_shas_file")
[[ -n "$profile" ]] && ingest_args+=(--profile "$profile")

[[ "$json_only" -eq 1 ]] || echo "== release agent: handing artifacts to pyauto-heart validate --ingest =="
if ! "$heart" "${ingest_args[@]}"; then
  echo "release rehearse: pyauto-heart validate --ingest failed" >&2
  exit 1
fi

# Consult the sibling vitals faculty (read-only) for the verdict. --refresh runs a
# fresh Heart tick so state.json re-aggregates the just-written
# validation_report.json before readiness recomputes the gate.
[[ "$json_only" -eq 1 ]] || echo "== release agent: consulting vitals faculty for the release-validation verdict =="
verdict="$(consult_vitals_verdict --refresh)"

eff="$verdict"; [[ "$eff" == "unknown" ]] && eff="yellow"
decision=""; decision_code=0; blockers=(); warnings=(); next=()
[[ "$verdict" == "unknown" ]] && warnings+=("Readiness verdict unknown; treated as YELLOW.")

case "$eff" in
  green)
    decision="release-ready"; decision_code=0
    next+=("Source built, TestPyPI-installed, and validated at release fidelity. A human/Release-Agent may promote to PyPI via Hands/Build.")
    ;;
  yellow)
    if [[ "$force" -eq 1 ]]; then
      decision="proceed-with-caution"; decision_code=0
      warnings+=("Readiness YELLOW; proceeding under --force.")
    else
      decision="hold"; decision_code=2
      blockers+=("Readiness is YELLOW — likely no fresh release-fidelity run yet, stale rehearsal, or source moved. See 'pyauto-brain vitals'. Re-run with --force to accept the caution.")
    fi
    ;;
  red)
    decision="blocked"; decision_code=3
    blockers+=("Readiness is RED — a validation stage failed or a hard blocker is present. Fix before releasing.")
    ;;
  *)
    decision="unknown"; decision_code=4
    blockers+=("Could not obtain a readiness verdict ('$verdict').")
    ;;
esac

emit_decision() {
  HEALTH="$verdict" DECISION="$decision" DIR="$ingest_dir" MODE="$mode_label" \
  WARNINGS="$(printf '%s\n' "${warnings[@]:-}")" \
  BLOCKERS="$(printf '%s\n' "${blockers[@]:-}")" \
  NEXT="$(printf '%s\n' "${next[@]:-}")" \
  python3 -c '
import json, os
def lines(k): return [x for x in os.environ.get(k, "").splitlines() if x.strip()]
print(json.dumps({
  "agent": "release", "mode": os.environ["MODE"], "phase": "verdict",
  "artifacts": os.environ["DIR"],
  "health_status": os.environ["HEALTH"],
  "decision": os.environ["DECISION"],
  "warnings": lines("WARNINGS"),
  "blockers": lines("BLOCKERS"),
  "next_steps": lines("NEXT"),
}, indent=2))
'
}

if [[ "$json_only" -eq 1 ]]; then
  emit_decision
else
  echo "-- ReleaseValidationDecision --"
  emit_decision
  echo
  "$heart" readiness || true
fi

exit "$decision_code"
