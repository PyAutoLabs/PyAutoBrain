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
#     -> consult the Health Agent for the verdict           (Health judges)
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
# Exit codes (ingest phase): 0 green · 2 yellow (use --force) · 3 red · 4 unknown
#   · 1 could not ingest. Plan phase always exits 0.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../_common.sh"

# The Build repo + workflow the rehearsal is dispatched against (M1).
BUILD_REPO="PyAutoLabs/PyAutoBuild"
RELEASE_WORKFLOW="release.yml"
REHEARSAL_ARTIFACT="testpypi-rehearsal-version"
# The 5 libraries whose main HEADs the rehearsal is built from; readiness
# confirms the ingested report's commit_shas against these. Bare names here
# are intentional: `commit_shas.json` keys (and heart/readiness.py's
# _GATE_SHA_LIBS) are bare repo names, e.g. "PyAutoConf", not "owner/repo".
# LIBRARIES_OWNER qualifies them ONLY for the get_commit MCP calls below
# (same convention as BUILD_REPO) — all five libraries live under this one
# GitHub org in this ecosystem, but qualifying explicitly removes any
# ambiguity for the agent executing the emitted plan.
LIBRARIES=(PyAutoConf PyAutoFit PyAutoArray PyAutoGalaxy PyAutoLens)
LIBRARIES_OWNER="PyAutoLabs"

ref="main"
minor=""
ingest_dir=""
commit_shas_file=""
profile=""
force=0
json_only=0

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
    ART="$REHEARSAL_ARTIFACT" LIBS="${LIBRARIES[*]}" LIBS_OWNER="$LIBRARIES_OWNER" python3 -c '
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
    {"step": "capture-heads", "mcp_tool": "mcp__github__get_commit",
     "repos": [f"{owner}/{lib}" for lib in libs],
     "note": "write {repo: sha} of each library main HEAD to commit_shas.json in the dir, "
             "keyed by the BARE repo name (e.g. PyAutoConf, not owner/repo) - "
             "matches heart/readiness.py commit_shas convention"},
    {"step": "ingest", "cmd": "pyauto-brain release rehearse --ingest <dir> --commit-shas <dir>/commit_shas.json"},
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
   The '$REHEARSAL_ARTIFACT' artifact is produced IFF all five wheels built,
   uploaded, and installed from TestPyPI — its presence IS the success signal.

3. DOWNLOAD the '$REHEARSAL_ARTIFACT' artifact into an artifacts directory
   (it contains rehearsal.json + testpypi_version.txt).

4. CAPTURE the current main HEAD sha of each library and write them as
   {bare_repo_name: sha} to <dir>/commit_shas.json (keys are bare names, e.g.
   "PyAutoConf" — matches heart/readiness.py's commit_shas convention, NOT
   "owner/repo") — so Heart can confirm the report is for THIS source
   (readiness matches them against the live main HEADs):
     mcp__github__get_commit  for: ${LIBRARIES[*]/#/$LIBRARIES_OWNER/}

5. INGEST + get the verdict (this script, phase 2):
     pyauto-brain release rehearse --ingest <dir> --commit-shas <dir>/commit_shas.json

After ingest, the Health Agent (read-only) reports GREEN/YELLOW/RED from the
freshly-ingested validation_report — it does NOT dispatch anything.
EOF
  exit 0
fi

# ---------------------------------------------------------------------------
# Phase 2: ingest the downloaded artifacts, then consult the Health Agent.
# ---------------------------------------------------------------------------
if [[ ! -d "$ingest_dir" && ! -f "$ingest_dir" ]]; then
  echo "release rehearse: artifacts path '$ingest_dir' not found" >&2
  exit 1
fi

heart="$(resolve_heart)" || exit $?

ingest_args=(validate --ingest "$ingest_dir")
[[ -n "$commit_shas_file" ]] && ingest_args+=(--commit-shas "$commit_shas_file")
[[ -n "$profile" ]] && ingest_args+=(--profile "$profile")

[[ "$json_only" -eq 1 ]] || echo "== release agent: handing artifacts to pyauto-heart validate --ingest =="
if ! "$heart" "${ingest_args[@]}"; then
  echo "release rehearse: pyauto-heart validate --ingest failed" >&2
  exit 1
fi

# Consult the sibling Health Agent (read-only) for the verdict. --refresh runs a
# fresh Heart tick so state.json re-aggregates the just-written
# validation_report.json before readiness recomputes the gate.
[[ "$json_only" -eq 1 ]] || echo "== release agent: consulting Health Agent for the release-validation verdict =="
verdict="$(consult_health_agent_verdict --refresh)"

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
      blockers+=("Readiness is YELLOW — likely no fresh release-fidelity run yet, stale rehearsal, or source moved. See 'pyauto-brain health'. Re-run with --force to accept the caution.")
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
  HEALTH="$verdict" DECISION="$decision" DIR="$ingest_dir" \
  WARNINGS="$(printf '%s\n' "${warnings[@]:-}")" \
  BLOCKERS="$(printf '%s\n' "${blockers[@]:-}")" \
  NEXT="$(printf '%s\n' "${next[@]:-}")" \
  python3 -c '
import json, os
def lines(k): return [x for x in os.environ.get(k, "").splitlines() if x.strip()]
print(json.dumps({
  "agent": "release", "mode": "rehearse", "phase": "verdict",
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
