#!/usr/bin/env bash
# agents/conductors/release/nightly.sh — the scheduled-nightly release driver.
#
# Implements the nightly sequence of PyAutoHands/docs/nightly_release_design.md
# (§3, steps 0-7): the ONLY path authorised to ship a live PyPI release without
# a per-release human, under the AUTONOMY.md standing grant of 2026-07-09
# (activity-gated, Heart-GREEN-gated, kill-switchable, loud on every outcome).
#
# This driver is deterministic shell — no LLM in the release gate. It COMPOSES
# the existing conductors rather than re-implementing them:
#
#   step 0  kill switch      vars.NIGHTLY_RELEASES (scheduled runs only)
#   step 1  same-day guard   a YYYY.M.D.* release tag already on PyAutoLens
#   step 2  activity gate    activity_gate.py over the release-relevant repos
#   step 3  known-red        open `release-blocker`-labelled issues
#   step 4  validate         validate.sh Phases A→C — the emitted dispatch
#                            plans are EXECUTED here with `gh` (in CI, unlike
#                            the MCP-only cloud sessions the plans were written
#                            for, gh is available to bash)
#   step 5  gate             vitals faculty → `pyauto-heart readiness
#                            --profile release-ci` — GREEN only; STALE/YELLOW/
#                            RED stop and page; there is NO force input
#   step 6  live release     dispatch Build's release.yml (rehearsal=false,
#                            minor_version=1) — or a log line under dry-run
#   step 7  report           one Slack message per terminal outcome
#
# Activity-window anchor: the PyAutoBrain repo Actions variable
# NIGHTLY_LAST_WINDOW_END. It advances ONLY when the window's activity was
# shipped (released) or the window was empty (skipped) — dry-runs and stops
# leave it, so unshipped merges are never swallowed (design §4).
#
# Environment (the workflow provides these; local runs may set them):
#   GH_TOKEN                  PAT for dispatch/poll/label/commit reads (required
#                             beyond --no-dispatch if gh is not already authed)
#   PYAUTO_RELEASE_WEBHOOK_URL  Slack webhook (missing → loud stderr warning)
#   NIGHTLY_RELEASES          kill switch; scheduled runs exit unless "true"
#   DRY_RUN                   "true" (default) → step 6 logs instead of shipping
#   GITHUB_EVENT_NAME         "schedule" engages the kill switch; anything else
#                             (manual dispatch, local) proceeds
#
# Usage:
#   nightly.sh [--dry-run] [--no-dispatch]
#     --dry-run       force DRY_RUN=true regardless of environment
#     --no-dispatch   stop after step 3, strictly read-only: no dispatch, no
#                     Slack post (printed instead), no anchor write
#
#   NIGHTLY_WINDOW_START (env) — override the activity-window start (ISO 8601)
#   for local verification; the persisted/24h anchor is used when unset.
#
# Exit: 0 on a reported outcome (shipped / skipped / dry-run) — 2 blocked at a
# gate (paged) — 3 not GREEN / preflight red (paged) — 1 driver error (paged).

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

BRAIN_REPO="PyAutoLabs/PyAutoHands"   # where release-blocker labels are curated first
ANCHOR_REPO="PyAutoLabs/PyAutoBrain"
ANCHOR_VAR="NIGHTLY_LAST_WINDOW_END"
# Release tags land on every library; one suffices. Which one is release
# POLICY — read from config/policy.yaml (the declared config surface).
TAG_REPO="$(python3 -c "import yaml, pathlib; print(yaml.safe_load((pathlib.Path('$HERE').parents[2] / 'config' / 'policy.yaml').read_text())['release']['tag_repo'])")"
BUILD_REPO="PyAutoLabs/PyAutoHands"
RELEASE_WORKFLOW="release.yml"
# Repos whose open `release-blocker` issues stop the night (the release-relevant
# set from activity_gate.py plus the release/health organs).
BLOCKER_EXTRA_REPOS=(PyAutoHands PyAutoHeart)

DRY_RUN="${DRY_RUN:-true}"
no_dispatch=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --no-dispatch) no_dispatch=1; shift ;;
    -h|--help)
      awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "${BASH_SOURCE[0]}"
      exit 0 ;;
    *) echo "release nightly: unknown arg '$1'" >&2; exit 1 ;;
  esac
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/pyauto-nightly.XXXXXX")"
ART_DIR="$WORK/artifacts"
mkdir -p "$ART_DIR"
RUN_URL="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-PyAutoLabs/PyAutoBrain}/actions/runs/${GITHUB_RUN_ID:-local}"
WINDOW_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

log() { printf '== nightly: %s\n' "$*"; }

# notify <emoji> <text> — one Slack message per terminal outcome (design §6).
# A missing webhook is a loud warning, never a crash: the run's own log +
# wake_up-digest watchdog still cover it.
notify() {
  local emoji="$1" text="$2"
  printf '%s %s\n' "$emoji" "$text"
  if [[ "$no_dispatch" -eq 1 ]]; then
    echo "nightly: --no-dispatch — outcome printed only, not posted"
    return 0
  fi
  if [[ -z "${PYAUTO_RELEASE_WEBHOOK_URL:-}" ]]; then
    echo "nightly: PYAUTO_RELEASE_WEBHOOK_URL not set — outcome NOT posted to Slack" >&2
    return 0
  fi
  jq -n --arg t "$emoji $text" '{text: $t}' | curl -sS -X POST \
    -H "Content-Type: application/json" --fail-with-body --data @- \
    "$PYAUTO_RELEASE_WEBHOOK_URL" >/dev/null \
    || echo "nightly: Slack POST failed — outcome NOT delivered" >&2
}

# advance_anchor — persist WINDOW_END as the next night's window start. Only
# called for shipped / empty-skip outcomes (see header). Failure is a warning:
# the fallback window (24h) self-heals.
advance_anchor() {
  if [[ "$no_dispatch" -eq 1 ]]; then
    echo "nightly: --no-dispatch — anchor left at its persisted value"
    return 0
  fi
  gh api -X PATCH "repos/$ANCHOR_REPO/actions/variables/$ANCHOR_VAR" \
      -f name="$ANCHOR_VAR" -f value="$WINDOW_END" >/dev/null 2>&1 \
    || gh api -X POST "repos/$ANCHOR_REPO/actions/variables" \
        -f name="$ANCHOR_VAR" -f value="$WINDOW_END" >/dev/null 2>&1 \
    || echo "nightly: could not persist $ANCHOR_VAR (window falls back to 24h)" >&2
}

page() { # page <text> — the 🚨 severity; never advances the anchor.
  notify "🚨" "*nightly release stopped* — $1
<$RUN_URL|nightly run>. No release was made."
}

# ---------------------------------------------------------------------------
# Step 0 — kill switch (scheduled runs only; manual/local runs proceed).
# Pausing is a human act, so the pause itself was the notification: exit silently.
# ---------------------------------------------------------------------------
if [[ "${GITHUB_EVENT_NAME:-}" == "schedule" && "${NIGHTLY_RELEASES:-}" != "true" ]]; then
  log "kill switch: NIGHTLY_RELEASES != 'true' — paused, exiting silently"
  exit 0
fi

# ---------------------------------------------------------------------------
# Step 0b — token sanity: every later step reads GitHub through gh. A dead or
# missing GH_TOKEN must page BEFORE any judgment — on 2026-07-10 a tokenless
# run read as a quiet night and silently skipped a real release (#67).
# ---------------------------------------------------------------------------
if ! gh api rate_limit >/dev/null 2>&1; then
  page "driver cannot authenticate to GitHub (GH_TOKEN missing or expired?) — no gate was evaluated"
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 1 — same-day guard: never double-release a date (design §8).
# ---------------------------------------------------------------------------
today="$(date -u +'%Y.%-m.%-d')"
today_re="^${today//./\\.}\\.[0-9]+$"
if gh api "repos/$TAG_REPO/tags?per_page=50" --jq '.[].name' 2>/dev/null \
    | grep -Eq "$today_re"; then
  log "a $today.* release tag already exists on $TAG_REPO"
  notify "💤" "*nightly release skipped* — already released today ($today). <$RUN_URL|nightly run>"
  exit 0
fi

# ---------------------------------------------------------------------------
# Step 2 — activity gate (design §4). Window: since the persisted anchor,
# falling back to 24h; judgment in activity_gate.py.
# ---------------------------------------------------------------------------
anchor="${NIGHTLY_WINDOW_START:-}"
[[ -z "$anchor" ]] && anchor="$(gh api "repos/$ANCHOR_REPO/actions/variables/$ANCHOR_VAR" --jq .value 2>/dev/null || true)"
# Validate the anchor before it reaches a `since=` parameter: a failed read
# can land an API error body on stdout (#67, hole 2 — the 404 JSON became the
# window start and poisoned every fetch). Anything malformed → 24h fallback.
if ! PYTHONPATH="$HERE" python3 -c '
import sys
from activity_gate import valid_anchor
sys.exit(0 if valid_anchor(sys.argv[1]) else 1)' "$anchor" 2>/dev/null; then
  [[ -n "$anchor" ]] && log "anchor read is not a timestamp ('${anchor:0:60}') — falling back to 24h"
  anchor="$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)"
fi
log "activity window: $anchor → $WINDOW_END"

repos="$(PYTHONPATH="$HERE" python3 -c 'from activity_gate import RELEASE_RELEVANT_REPOS as R; print("\n".join(R))')"
commits_json="$WORK/commits.json"
{
  printf '{'
  first=1
  while IFS= read -r repo; do
    [[ -z "$repo" ]] && continue
    # A failed fetch is `null`, never `[]`: an unreadable repo must not be
    # mistaken for a quiet one (#67, hole 1). activity_gate.py counts these.
    if ! body="$(gh api "repos/PyAutoLabs/$repo/commits?sha=main&since=$anchor&per_page=100" 2>/dev/null)"; then
      body='null'
    fi
    [[ "$first" -eq 0 ]] && printf ','
    first=0
    printf '%s' "\"$repo\":"
    printf '%s' "$body"
  done <<< "$repos"
  printf '}'
} > "$commits_json"

gate="$(PYTHONPATH="$HERE" python3 "$HERE/activity_gate.py" < "$commits_json")" || {
  page "activity gate could not be evaluated (driver error)"
  exit 1
}
active="$(printf '%s' "$gate" | python3 -c 'import json,sys; print("1" if json.load(sys.stdin)["active"] else "0")')"
summary="$(printf '%s' "$gate" | python3 -c 'import json,sys; print(json.load(sys.stdin)["summary"])')"
fetch_errors="$(printf '%s' "$gate" | python3 -c 'import json,sys; print(json.load(sys.stdin)["fetch_errors"])')"
all_failed="$(printf '%s' "$gate" | python3 -c 'import json,sys; print("1" if json.load(sys.stdin)["all_failed"] else "0")')"
log "$summary"

# An unobservable GitHub pages, never sleeps (#67): if every fetch failed the
# night was not judged at all. Partial failures proceed on what was readable —
# activity in a readable repo still legitimately qualifies the night.
if [[ "$all_failed" == "1" ]]; then
  page "activity fetch failed for every release-relevant repo — the night was NOT judged. $summary"
  exit 1
fi

if [[ "$active" != "1" ]]; then
  notify "💤" "*nightly release skipped* — no activity since $anchor. $summary. <$RUN_URL|nightly run>"
  # Advance only a truly-judged, truly-quiet night: unreadable repos may hold
  # the missed activity, and a dry-run must not mutate state (design header:
  # "dry-runs and stops leave it" — the 2026-07-10 08:03 dry-run violated
  # this and swallowed the missed window).
  if [[ "$fetch_errors" != "0" ]]; then
    log "fetch errors present — anchor NOT advanced"
  elif [[ "$DRY_RUN" == "true" ]]; then
    log "dry-run — anchor NOT advanced"
  else
    advance_anchor
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
# Step 3 — known-red: any open `release-blocker` issue stops the night before
# any dispatch (design §5). A human labels an issue; that click pages every
# scheduled night until it closes.
# ---------------------------------------------------------------------------
blockers=""
while IFS= read -r repo; do
  [[ -z "$repo" ]] && continue
  found="$(gh api "repos/PyAutoLabs/$repo/issues?labels=release-blocker&state=open&per_page=10" \
             --jq '.[] | "\(.html_url) (\(.title))"' 2>/dev/null || true)"
  [[ -n "$found" ]] && blockers+="$found"$'\n'
done <<< "$repos"$'\n'"$(printf '%s\n' "${BLOCKER_EXTRA_REPOS[@]}")"

if [[ -n "${blockers//[[:space:]]/}" ]]; then
  log "release-blocker issue(s) open:"
  printf '%s' "$blockers"
  page "release-blocked by open issue(s):
$blockers"
  exit 2
fi

if [[ "$no_dispatch" -eq 1 ]]; then
  log "--no-dispatch: gates passed (activity present, no blockers); stopping before any dispatch"
  exit 0
fi

# ---------------------------------------------------------------------------
# Step 4 — validate: run validate.sh's Phases A→C, executing each emitted
# dispatch plan with gh (this is the CI incarnation of the plans' MCP steps;
# parameters are parsed FROM the plans so nothing is duplicated here).
# ---------------------------------------------------------------------------

# plan_field <plan-json> <python-expr over `plan`> — tiny extractor.
plan_field() {
  PLAN="$1" python3 -c "
import json, os
plan = json.loads(os.environ['PLAN'])
print($2)
"
}

# dispatch_and_await <repo> <workflow> <inputs-json> [<artifact> <dest-dir>]
# Dispatches, resolves the run id, watches to completion (fails loudly), and
# optionally downloads an artifact. Echoes the run URL on success.
dispatch_and_await() {
  local repo="$1" wf="$2" inputs="$3" artifact="${4:-}" dest="${5:-}"
  local before run_id rc
  before="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local fargs=()
  while IFS=$'\t' read -r k v; do
    [[ -z "$k" ]] && continue
    fargs+=(-f "$k=$v")
  done < <(printf '%s' "$inputs" | python3 -c '
import json, sys
for k, v in (json.load(sys.stdin) or {}).items():
    print(f"{k}\t{str(v).lower() if isinstance(v, bool) else v}")
')
  gh workflow run "$wf" -R "$repo" --ref main "${fargs[@]}" || return 1
  run_id=""
  for _ in $(seq 1 18); do
    sleep 10
    run_id="$(gh run list -R "$repo" --workflow "$wf" --created ">=$before" \
                -L 1 --json databaseId --jq '.[0].databaseId // empty' 2>/dev/null)"
    [[ -n "$run_id" ]] && break
  done
  if [[ -z "$run_id" ]]; then
    echo "nightly: dispatched $repo/$wf but could not find the run" >&2
    return 1
  fi
  echo "https://github.com/$repo/actions/runs/$run_id" >&2
  gh run watch "$run_id" -R "$repo" --interval 60 --exit-status >/dev/null
  rc=$?
  LAST_RUN_URL="https://github.com/$repo/actions/runs/$run_id"
  [[ $rc -ne 0 ]] && return 2
  if [[ -n "$artifact" ]]; then
    gh run download "$run_id" -R "$repo" -n "$artifact" -D "$dest" || return 3
  fi
  return 0
}

log "step 4 — validate (Stages 0-3 via validate.sh)"
phase_a="$(bash "$HERE/validate.sh" --json)"
rc=$?
if [[ $rc -eq 3 ]]; then
  page "validation preflight RED:
$(plan_field "$phase_a" "chr(10).join(plan.get('blockers', []))")"
  exit 3
elif [[ $rc -ne 0 || -z "$phase_a" ]]; then
  page "validation Phase A failed (exit $rc)"
  exit 1
fi

s2_repo="$(plan_field "$phase_a" "plan['stage2_plan']['steps'][0]['repo']")"
s2_wf="$(plan_field "$phase_a" "plan['stage2_plan']['steps'][0]['workflow']")"
s2_inputs="$(plan_field "$phase_a" "json.dumps(plan['stage2_plan']['steps'][0]['inputs'])")"
s2_artifact="$(plan_field "$phase_a" "[s for s in plan['stage2_plan']['steps'] if s['step']=='download'][0]['artifact']")"
head_repos="$(plan_field "$phase_a" "chr(10).join([s for s in plan['stage2_plan']['steps'] if s['step']=='capture-heads'][0]['repos'])")"

log "step 4a — Stage 2 rehearsal: dispatch $s2_repo/$s2_wf"
if ! dispatch_and_await "$s2_repo" "$s2_wf" "$s2_inputs" "$s2_artifact" "$ART_DIR"; then
  page "Stage 2 (TestPyPI rehearsal) failed — <${LAST_RUN_URL:-$RUN_URL}|run>"
  exit 2
fi

# capture-heads: {bare repo name: main HEAD sha} — Stage 2's commit_shas.json
# is the single source of truth downstream (validate.sh header).
python3 - "$ART_DIR/commit_shas.json" <<PY
import json, subprocess, sys
repos = """$head_repos""".split()
shas = {}
for full in repos:
    sha = subprocess.run(["gh", "api", f"repos/{full}/commits/main", "--jq", ".sha"],
                         capture_output=True, text=True, check=True).stdout.strip()
    shas[full.split("/")[-1]] = sha
with open(sys.argv[1], "w") as f:
    json.dump(shas, f, indent=2, sort_keys=True)
print("commit_shas:", json.dumps(shas))
PY
[[ -s "$ART_DIR/commit_shas.json" ]] || { page "could not capture library main HEADs"; exit 1; }

log "step 4b — Stage 3 integrate: emitting + executing the dispatch plan"
phase_b="$(bash "$HERE/validate.sh" --stage3-plan "$ART_DIR" --json)" || {
  page "validation Phase B failed (Stage 2 artifacts incomplete in $ART_DIR)"
  exit 1
}
s3_repo="$(plan_field "$phase_b" "plan['steps'][0]['repo']")"
s3_wf="$(plan_field "$phase_b" "plan['steps'][0]['workflow']")"
s3_inputs="$(plan_field "$phase_b" "json.dumps(plan['steps'][0]['inputs'])")"
s3_artifact="$(plan_field "$phase_b" "[s for s in plan['steps'] if s['step']=='download'][0]['artifact']")"

if ! dispatch_and_await "$s3_repo" "$s3_wf" "$s3_inputs" "$s3_artifact" "$ART_DIR"; then
  page "Stage 3 (release-fidelity integration) failed — <${LAST_RUN_URL:-$RUN_URL}|run>"
  exit 2
fi

# ---------------------------------------------------------------------------
# Step 4c + 5 — assemble the CI snapshot Heart's release-ci profile evaluates
# (design §5): cloud-safe checks + the just-produced validation artifacts,
# then the gate through the vitals faculty. GREEN only; no force input exists.
# ---------------------------------------------------------------------------
log "step 4c — ingest + assemble the CI readiness snapshot"
heart="$(resolve_heart)" || { page "pyauto-heart not resolvable"; exit 1; }
HEART_DIR="$(cd "$(dirname "$(readlink -f "$(command -v "$heart" || echo "$heart")")")/.." && pwd)"
export HEART_STATE_DIR="${HEART_STATE_DIR:-$WORK/heart-state}"
mkdir -p "$HEART_STATE_DIR"

bash "$HEART_DIR/heart/checks/ci_status.sh" || echo "nightly: ci_status check failed (verdict will show unknowns)" >&2
bash "$HEART_DIR/heart/checks/open_prs.sh" || echo "nightly: open_prs check failed" >&2
"$heart" validate --ingest "$ART_DIR" --commit-shas "$ART_DIR/commit_shas.json" || {
  page "could not ingest the validation artifacts into Heart"
  exit 1
}
PYTHONPATH="$HEART_DIR" python3 -c "from heart import state; state.aggregate()" || {
  page "could not aggregate the Heart snapshot"
  exit 1
}

log "step 5 — readiness gate (release-ci profile; GREEN only)"
verdict="$(consult_vitals_verdict --profile release-ci)"
"$heart" readiness --profile release-ci || true
if [[ "$verdict" != "green" ]]; then
  reasons="$("$heart" readiness --json --profile release-ci 2>/dev/null \
    | python3 -c 'import json,sys; print("; ".join(json.load(sys.stdin).get("reasons", [])[:6]))' 2>/dev/null || true)"
  page "Heart is ${verdict^^}, not GREEN: ${reasons:-see the run log}"
  exit 3
fi
log "Heart GREEN — release authorised by the standing grant"

# ---------------------------------------------------------------------------
# Step 6 — the live release (or the dry-run log line).
# ---------------------------------------------------------------------------
version="$today.1"
if [[ "$DRY_RUN" == "true" ]]; then
  notify "🧪" "*nightly dry-run complete* — all gates GREEN; would have dispatched the live release ($version). $summary. <$RUN_URL|nightly run>"
  # Deliberately NOT advancing the anchor: nothing shipped, so tonight's
  # activity stays in the next real night's window (see header).
  exit 0
fi

log "step 6 — dispatching the LIVE release ($version)"
if ! dispatch_and_await "$BUILD_REPO" "$RELEASE_WORKFLOW" \
      '{"rehearsal": "false", "minor_version": "1"}'; then
  # release.yml's announce_release also pages on a live failure; this adds the
  # nightly attribution so the two reports correlate.
  page "live release run failed — <${LAST_RUN_URL:-$RUN_URL}|release run>"
  exit 2
fi

notify "📦" "*nightly release shipped* — $version. $summary (window $anchor → $WINDOW_END). <${LAST_RUN_URL:-$RUN_URL}|release run>"
advance_anchor
exit 0
