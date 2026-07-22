#!/usr/bin/env bash
# agents/release/validate.sh — the full Stages 0-3 release-validation orchestrator (M4).
#
# This is the Brain Release Agent's END-TO-END release-validation driver. Where
# rehearse.sh drives Stage 2 alone (the TestPyPI build + ingest), this sequences
# the whole pipeline the release_validation.md spec lays out:
#
#   Stage 0 (preflight)  local read of Heart's cached repo_state / version_skew
#                        signals for the 5 libraries — all clean, on main, not
#                        behind; workspace pins not AHEAD/MISMATCH/BAD. Pure
#                        local read; NO dispatch. Abort RED if any signal is bad
#                        ("no point building a dirty tree").
#   Stage 1 (unit)       reuse the same Stage-0 ci_status.conclusion signal (each
#                        library's last known CI result); a red conclusion is a
#                        preflight blocker. (A fresh dispatch-if-stale run is the
#                        spec's optional path — deferred for M4's first cut.)
#   Stage 2 (rehearse)   dispatch Build's release.yml rehearsal, poll, download
#                        the testpypi-rehearsal-version artifact, capture each
#                        library's main HEAD -> commit_shas.json. Reused AS-IS
#                        from rehearse.sh (called into, not re-implemented).
#   Stage 3 (integrate)  dispatch PyAutoHeart's workspace-validation.yml in
#                        mode=release with the Stage-2 testpypi_version +
#                        commit_shas, poll, download the release-stage-report.
#   final ingest+verdict hand Stage 2's rehearsal.json/commit_shas.json AND
#                        Stage 3's stage_report.json together to
#                        `pyauto-heart validate --ingest`, then consult the
#                        vitals faculty — reused AS-IS from rehearse.sh's phase 2.
#
# BOUNDARY (unchanged from M2, non-negotiable). Heart never dispatches, never
# talks to GitHub, never mutates a repo — ingest-and-judge only. The vitals faculty
# is strict read-and-reason. ALL dispatch/poll/download across all four stages is
# the Release Agent's job, done via Brain's MCP GitHub tools (cloud/mobile has no
# gh; bash cannot call MCP). So — exactly as rehearse.sh already does for Stage 2 —
# this script owns the LOCAL half (preflight + plan emission + ingest + verdict)
# and EMITS each dispatch stage's MCP plan for the agent to execute, picking up
# where the agent left off once each stage's artifacts land.
#
# Because of that MCP boundary the orchestrator is a 3-phase driver — one phase
# per point where it must hand off to (and resume from) the agent's MCP work:
#
#   # Phase A — preflight (Stage 0/1) + emit the Stage 2 dispatch plan:
#   validate.sh [--ref main] [--minor N] [--json]
#       Stage 0/1 bad  -> RED decision, exit 3, NOTHING dispatched.
#       Stage 0/1 ok   -> emit the Stage 2 plan; the agent runs it, then calls:
#
#   # Phase B — once Stage 2 artifacts exist, emit the Stage 3 dispatch plan:
#   validate.sh --stage3-plan <dir> [--ref main] [--json]
#       reads testpypi_version + commit_shas from <dir>, emits the
#       workspace-validation.yml mode=release plan; the agent runs it, then calls:
#
#   # Phase C — once Stage 3 artifacts exist, ingest everything + get the verdict:
#   validate.sh --ingest <dir> [--commit-shas FILE] [--profile P] [--force] [--json]
#       delegates to rehearse.sh --ingest (reused verbatim) so the ingest +
#       vitals-faculty consult + decision + exit codes are IDENTICAL to Stage 2's.
#
# Exit codes: preflight RED -> 3; a phase that cannot proceed (missing artifacts)
# -> 1; phase-C ingest -> 0 green · 2 yellow (use --force) · 3 red · 4 unknown ·
# 1 could-not-ingest — i.e. the same convention rehearse.sh's phase 2 uses, held
# consistent across the now-longer pipeline. Plan-emission phases exit 0.
#
# commit_shas authority. Stage 2's commit_shas.json (the library main HEADs the
# Release Agent read straight from GitHub) is the SINGLE source of truth. Stage 3
# merely echoes it back: the same JSON is passed as workspace-validation.yml's
# `commit_shas` input, which emit_release_report writes out and embeds into
# stage_report.json. So the phase-C `--commit-shas` flag and the stage report's
# embedded copy derive from the SAME file and cannot legitimately disagree.
# Passing --commit-shas is therefore a SAFETY NET (it guarantees readiness has
# the SHAs even if a stage report is malformed / omits them), not redundant. In
# heart/validate.py's fold a stage artifact's embedded commit_shas is applied
# after the --commit-shas seed (last-writer-wins), so on the impossible
# disagreement the embedded copy wins — but since both originate from Stage 2,
# Stage 2's commit_shas.json remains authoritative by construction.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

# Stage 3 target: Heart's workspace-validation.yml (the M3 mode=release path).
# Dispatched on Heart's own main (where the merged workflow lives) — the LIBRARY
# source is pinned by the TestPyPI wheels + commit_shas input, not by this ref.
HEART_REPO="PyAutoLabs/PyAutoHeart"
INTEGRATE_WORKFLOW="workspace-validation.yml"
INTEGRATE_ARTIFACT="release-stage-report"
# The 5 libraries whose Stage-0 cleanliness/CI signals gate the whole run. Bare
# names match heart state's repos.<name> keys and readiness' commit_shas keys.
LIBRARIES=(PyAutoNerves PyAutoFit PyAutoArray PyAutoGalaxy PyAutoLens)

ref="main"
minor=""
stage3_dir=""
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
    --stage3-plan) stage3_dir="$2"; shift 2 ;;
    --stage3-plan=*) stage3_dir="${1#*=}"; shift ;;
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
    *) echo "release validate: unknown arg '$1'" >&2; exit 5 ;;
  esac
done

# ---------------------------------------------------------------------------
# Phase C: final ingest + verdict (Stage 2 + Stage 3 artifacts together).
# Reuse rehearse.sh --ingest VERBATIM so the ingest + vitals-faculty consult +
# decision + exit codes are identical to the Stage-2-only path — the "mode" in
# the emitted verdict JSON is stamped "validate" to attribute it to this flow.
# ---------------------------------------------------------------------------
if [[ -n "$ingest_dir" ]]; then
  args=(--ingest "$ingest_dir" --mode-label validate)
  [[ -n "$commit_shas_file" ]] && args+=(--commit-shas "$commit_shas_file")
  [[ -n "$profile" ]] && args+=(--profile "$profile")
  [[ "$force" -eq 1 ]] && args+=(--force)
  [[ "$json_only" -eq 1 ]] && args+=(--json)
  exec bash "$HERE/rehearse.sh" "${args[@]}"
fi

# ---------------------------------------------------------------------------
# Phase B: emit the Stage 3 (integrate) dispatch plan. Requires the Stage 2
# artifacts (testpypi_version + commit_shas.json) already downloaded into <dir>.
# ---------------------------------------------------------------------------
if [[ -n "$stage3_dir" ]]; then
  if [[ ! -d "$stage3_dir" ]]; then
    echo "release validate: Stage 2 artifacts dir '$stage3_dir' not found" >&2
    exit 1
  fi

  # Resolve the rehearsed TestPyPI version and the compact commit_shas JSON
  # string the workflow expects. Both come from the Stage 2 artifacts in <dir>.
  read_out="$(DIR="$stage3_dir" python3 -c '
import json, os, sys
from pathlib import Path

d = Path(os.environ["DIR"])

def find_version():
    for name in ("rehearsal.json", "testpypi_version.txt"):
        for p in sorted(d.rglob(name)):
            try:
                if p.suffix == ".txt":
                    t = p.read_text().strip().splitlines()
                    if t:
                        return t[0].strip()
                else:
                    data = json.loads(p.read_text())
                    v = data.get("version")
                    if v:
                        return str(v)
            except (OSError, json.JSONDecodeError):
                continue
    # No loose "any JSON with a version key" fallback: once Stage 3 has run its
    # stage_report.json ALSO carries a "version", so guessing could pick the
    # wrong artifact. Only the Stage-2 rehearsal artifacts are authoritative;
    # missing them is a hard failure (handled by the caller), not a guess.
    return ""

def find_shas():
    for p in sorted(d.rglob("commit_shas.json")):
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data.get("commit_shas") if "commit_shas" in data else data
    return {}

version = find_version()
shas = find_shas()
if not isinstance(shas, dict):
    shas = {}
# Compact single-line JSON string — the workspace-validation.yml commit_shas
# input is a JSON *string* (default "{}").
shas_json = json.dumps(shas, separators=(",", ":"), sort_keys=True)
# Emit two NUL-free lines: version, then the shas JSON string.
print(version)
print(shas_json)
' 2>/dev/null)"

  testpypi_version="$(printf '%s\n' "$read_out" | sed -n '1p')"
  commit_shas_json="$(printf '%s\n' "$read_out" | sed -n '2p')"

  if [[ -z "$testpypi_version" ]]; then
    echo "release validate: no testpypi_version found in '$stage3_dir' (expected rehearsal.json or testpypi_version.txt from Stage 2)" >&2
    exit 1
  fi

  # Stage 3 REQUIRES Stage 2's commit_shas (the authoritative library HEADs the
  # Release Agent read from GitHub). Missing/empty is a hard failure: dispatching
  # with an empty {} would run the integration against unconfirmed source and
  # then emit a phase-C `--commit-shas <dir>/commit_shas.json` step pointing at a
  # file that may not exist. Better to stop here than dispatch a blind run.
  if [[ -z "$commit_shas_json" || "$commit_shas_json" == "{}" ]]; then
    echo "release validate: no Stage-2 commit_shas found in '$stage3_dir' (expected a non-empty commit_shas.json — the authoritative library main HEADs). Cannot dispatch Stage 3 without them." >&2
    exit 1
  fi

  # The inputs object for the workspace-validation.yml mode=release dispatch.
  inputs="$(MODE=release VER="$testpypi_version" SHAS="$commit_shas_json" python3 -c '
import json, os
print(json.dumps({
  "mode": os.environ["MODE"],
  "testpypi_version": os.environ["VER"],
  "commit_shas": os.environ["SHAS"],
}))
')"
  next_cmd="pyauto-brain release validate --ingest $stage3_dir --commit-shas $stage3_dir/commit_shas.json"

  if [[ "$json_only" -eq 1 ]]; then
    REPO="$HEART_REPO" WF="$INTEGRATE_WORKFLOW" REF="$ref" INPUTS="$inputs" \
    ART="$INTEGRATE_ARTIFACT" DIR="$stage3_dir" NEXT_CMD="$next_cmd" python3 -c '
import json, os
print(json.dumps({
  "agent": "release", "mode": "validate", "phase": "stage3-dispatch-plan",
  "steps": [
    {"step": "dispatch", "mcp_tool": "mcp__github__actions_run_trigger",
     "repo": os.environ["REPO"], "workflow": os.environ["WF"],
     "ref": os.environ["REF"], "inputs": json.loads(os.environ["INPUTS"])},
    {"step": "poll", "mcp_tool": "mcp__github__actions_get",
     "until": "status == completed",
     "note": "wheel-based integration at release fidelity + verify_install A-E"},
    {"step": "download", "artifact": os.environ["ART"],
     "note": "download stage_report.json INTO " + os.environ["DIR"] +
             " (the SAME dir holding rehearsal.json + commit_shas.json) so the "
             "final ingest sees all three artifacts together"},
    {"step": "next", "cmd": os.environ["NEXT_CMD"]},
  ],
}, indent=2))
'
    exit 0
  fi

  cat <<EOF
== release agent: Stage 3 (integrate on wheels at release fidelity) — dispatch plan ==

Stage 2 artifacts read from: $stage3_dir
  testpypi_version: $testpypi_version
  commit_shas:      $commit_shas_json

Bash cannot call GitHub; execute these steps with Brain's MCP GitHub tools.
Heart never dispatches — this is the Release Agent's job.

1. DISPATCH the wheel-based release-fidelity integration run:
     mcp__github__actions_run_trigger
       repo:     $HEART_REPO
       workflow: $INTEGRATE_WORKFLOW
       ref:      $ref
       inputs:   $inputs

   (mode=release: pip-installs the Stage-2 TestPyPI wheels with NO source on
    PYTHONPATH, runs every workspace + workspace_test script under the 'release'
    env profile from inside each workspace checkout, and runs verify_install A-E
    against the same wheels.)

2. POLL the run to completion (mcp__github__actions_get / actions_list).

3. DOWNLOAD the '$INTEGRATE_ARTIFACT' artifact (stage_report.json) INTO
   $stage3_dir — the SAME directory already holding rehearsal.json +
   commit_shas.json, so the final ingest folds all three together.

4. NEXT — ingest Stage 2 + Stage 3 together and get the verdict:
     $next_cmd
EOF
  exit 0
fi

# ---------------------------------------------------------------------------
# Phase A: Stage 0 (preflight) + Stage 1 (unit, cached CI) — a pure local read
# of Heart's cached signals. On a clean result, emit the Stage 2 dispatch plan
# (reusing rehearse.sh's plan emission, redirected to continue into phase B).
# ---------------------------------------------------------------------------
heart="$(resolve_heart)" || exit $?

# Refresh Heart's state so preflight reads fresh signals; tolerate a failed tick
# (fall back to the last cached state, as the release agent already does).
"$heart" tick >/dev/null 2>&1 || echo "  (warning: heart tick failed; using last cached state)" >&2

# Read the aggregated snapshot and evaluate the Stage 0/1 gates in one pass. The
# evaluation MIRRORS heart/readiness.py's library + version_skew gates (same
# signals), but is applied here as a *preflight* before any dispatch. Definitely
# bad signals (off-main / dirty / behind / failing CI / AHEAD / MISMATCH / BAD)
# abort RED; unknowns are surfaced as warnings but do NOT block (an unknown is
# never silently treated as green, nor escalated to a hard abort — same
# philosophy readiness follows).
preflight_json="$("$heart" status --json 2>/dev/null | LIBS="${LIBRARIES[*]}" python3 -c '
import json, sys, os

try:
    snap = json.load(sys.stdin)
except Exception:
    snap = None

libs = os.environ["LIBS"].split()
blockers = []
unknowns = []

if not isinstance(snap, dict) or not snap:
    # No usable snapshot at all — cannot confirm cleanliness; treat as unknown,
    # not a hard abort (readiness treats a missing snapshot the same way).
    unknowns.append("no Heart state snapshot (run `pyauto-heart tick`)")
    snap = {}

repos = snap.get("repos", {}) or {}

for lib in libs:
    body = repos.get(lib)
    if not isinstance(body, dict) or not body:
        unknowns.append(f"{lib}: status unknown (not observed by Heart)")
        continue
    # Stage 1 (unit): last known CI conclusion. success = ok; a real failure
    # conclusion blocks; empty/None (in-progress/never-run) is an unknown.
    ci = body.get("ci_status", {}) or {}
    concl = ci.get("conclusion")
    if concl in (None, ""):
        unknowns.append(f"{lib}: CI conclusion unknown")
    elif concl != "success":
        blockers.append(f"{lib}: CI {concl}")
    # Stage 0 (preflight): clean, on main, not behind.
    rs = body.get("repo_state", {}) or {}
    branch = rs.get("branch")
    if branch and branch != "main":
        blockers.append(f"{lib}: on branch {branch} (not main)")
    # A present-but-unparseable count (schema drift / non-int) must NOT be
    # coerced to 0 and silently pass as clean — that would violate the
    # "unknowns are never silently treated as green" invariant. An ABSENT key is
    # fine (repo_state omits it when clean); only a value we cannot parse is an
    # unknown, surfaced as a warning (still non-blocking, per the unknown policy).
    raw_dirty = rs.get("dirty_real", rs.get("dirty_files"))
    if raw_dirty is None:
        dirty = 0
    else:
        try:
            dirty = int(raw_dirty)
        except (TypeError, ValueError):
            dirty = 0
            unknowns.append(f"{lib}: dirty count unparseable ({raw_dirty!r}) — not assuming clean")
    if dirty > 0:
        blockers.append(f"{lib}: {dirty} uncommitted source change(s)")
    raw_behind = rs.get("behind")
    if raw_behind is None:
        behind = 0
    else:
        try:
            behind = int(raw_behind)
        except (TypeError, ValueError):
            behind = 0
            unknowns.append(f"{lib}: behind count unparseable ({raw_behind!r}) — not assuming up-to-date")
    if behind > 0:
        blockers.append(f"{lib}: {behind} commit(s) behind origin")

# Workspace version-skew: AHEAD / MISMATCH / BAD are hard blockers (never build
# a workspace pinned ahead of / inconsistent with its library).
skew = snap.get("version_skew")
if isinstance(skew, dict):
    for w in skew.get("workspaces") or []:
        if not isinstance(w, dict):
            continue
        status = str(w.get("status", "")).upper()
        ws = w.get("workspace")
        if status == "AHEAD":
            pinned = w.get("pinned")
            installed = w.get("installed")
            blockers.append(f"{ws}: pinned {pinned} AHEAD of installed {installed}")
        elif status == "MISMATCH":
            blockers.append(f"{ws}: general.yaml != version.txt")
        elif status == "BAD":
            blockers.append(f"{ws}: unparseable version pin")

ok = not blockers
print(json.dumps({"ok": ok, "blockers": blockers, "unknowns": unknowns}))
')"

[[ -z "$preflight_json" ]] && preflight_json='{"ok": false, "blockers": ["preflight evaluation failed"], "unknowns": []}'

preflight_ok="$(printf '%s' "$preflight_json" | python3 -c 'import json,sys; print("1" if json.load(sys.stdin).get("ok") else "0")' 2>/dev/null)"
[[ -z "$preflight_ok" ]] && preflight_ok=0

if [[ "$preflight_ok" -ne 1 ]]; then
  # Stage 0/1 RED — abort before dispatching anything.
  if [[ "$json_only" -eq 1 ]]; then
    printf '%s' "$preflight_json" | python3 -c '
import json, sys
pf = json.load(sys.stdin)
print(json.dumps({
  "agent": "release", "mode": "validate", "phase": "preflight",
  "decision": "blocked",
  "health_status": "red",
  "blockers": pf.get("blockers", []),
  "warnings": pf.get("unknowns", []),
  "next_steps": ["Fix the preflight blockers (dirty/off-main/behind/CI/skew) before rehearsing — no point building a dirty tree."],
}, indent=2))
'
  else
    echo "== release agent: Stage 0/1 PREFLIGHT — reading Heart's cached signals =="
    echo "-- ReleaseValidationDecision (preflight) --"
    printf '%s' "$preflight_json" | python3 -c '
import json, sys
pf = json.load(sys.stdin)
print("preflight: BLOCKED (red)")
for b in pf.get("blockers", []):
    print("  ✗ " + b)
for u in pf.get("unknowns", []):
    print("  ! " + u)
print("No dispatch — fix the blockers above (no point building a dirty tree).")
'
  fi
  exit 3
fi

# Stage 0/1 clean → proceed to Stage 2. Surface any unknowns as warnings, then
# delegate the Stage 2 dispatch plan to rehearse.sh, redirected to continue into
# phase B (--stage3-plan) rather than the Stage-2-only ingest.
if [[ "$json_only" -eq 1 ]]; then
  # Combined JSON: preflight result + the Stage 2 plan rehearse.sh emits.
  stage2_plan="$(bash "$HERE/rehearse.sh" --ref "$ref" ${minor:+--minor "$minor"} \
                   --next-plan-cmd "pyauto-brain release validate --stage3-plan <dir>" --json)"
  PF="$preflight_json" S2="$stage2_plan" python3 -c '
import json, os
pf = json.loads(os.environ["PF"])
try:
    s2 = json.loads(os.environ["S2"])
except Exception:
    s2 = {"error": "could not parse Stage 2 plan"}
print(json.dumps({
  "agent": "release", "mode": "validate", "phase": "preflight+stage2-plan",
  "preflight": {"ok": True, "warnings": pf.get("unknowns", [])},
  "stage2_plan": s2,
}, indent=2))
'
  exit 0
fi

echo "== release agent: Stage 0/1 PREFLIGHT — reading Heart's cached signals =="
echo "preflight: PASS (all 5 libraries clean/on main/not behind; no version-skew blockers)"
printf '%s' "$preflight_json" | python3 -c '
import json, sys
for u in json.load(sys.stdin).get("unknowns", []):
    print("  ! " + u + " (unknown — not blocking)")
' 2>/dev/null || true
echo
echo "== release agent: Stage 0/1 clean → emitting the Stage 2 dispatch plan =="
echo
exec bash "$HERE/rehearse.sh" --ref "$ref" ${minor:+--minor "$minor"} \
     --next-plan-cmd "pyauto-brain release validate --stage3-plan <dir>"
