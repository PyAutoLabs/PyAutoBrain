#!/usr/bin/env bash
#
# overnight_status.sh — latest scheduled-workflow run conclusions across the
# PyAuto organism. Pure `gh` API — needs no local checkout, so it runs on the
# CLI, on mobile Claude Code chat, and in Codex alike.
#
# Output: one line per job — icon  owner/repo/workflow  conclusion (age).
#
# A green run does not always mean "nothing to see". The nightly release driver
# deliberately renders a night it BLOCKED at a gate as a successful run (red is
# reserved for a broken driver — see PyAutoBrain/.github/workflows/
# nightly-release.yml, OUTCOME CONTRACT), so a blocked night would otherwise be
# indistinguishable here from a night that shipped. Any workflow that names a
# step with $BLOCKED_STEP_PREFIX gets its own ⏸ line: not green, not a failure,
# but something a human should read.

set -u
command -v gh >/dev/null 2>&1 || { echo "gh not found — cannot fetch run status" >&2; exit 1; }

# owner/repo:workflow-file  (owner defaults to PyAutoLabs when omitted). The
# passive morning webhooks (morning_health / morning_status) are excluded —
# /wake_up is their interactive complement, not a re-run of them.
JOBS=(
  "PyAutoBrain:nightly-release.yml"
  "PyAutoHeart:heart-health.yml"
  "PyAutoHeart:workspace-smoke.yml"
  "PyAutoHands:python_matrix.yml"
  "PyAutoMind:arxiv_papers.yml"
  "PyAutoMind:spawn_drift.yml"
  "autolens_assistant:wiki-currency.yml"
)

age() {  # ISO8601 -> "Nh" (<48h) or "Nd" ago
  local ts now diff
  now=$(date -u +%s) || { echo "?"; return; }
  ts=$(date -u -d "$1" +%s 2>/dev/null) || { echo "?"; return; }
  diff=$(( (now - ts) / 3600 ))
  if [ "$diff" -lt 48 ]; then echo "${diff}h"; else echo "$(( diff / 24 ))d"; fi
}

# A successful run carrying a step with this name prefix stopped on purpose and
# made no change. Keep in sync with the step name in nightly-release.yml.
BLOCKED_STEP_PREFIX="Blocked at a gate"

fails=0
blocked=0
for job in "${JOBS[@]}"; do
    repo="${job%%:*}"; wf="${job##*:}"
    [[ "$repo" == */* ]] || repo="PyAutoLabs/$repo"
    read -r concl created run_id < <(gh api "repos/$repo/actions/workflows/$wf/runs?per_page=1" \
        -q '.workflow_runs[0] | "\(.conclusion // .status) \(.created_at) \(.id)"' 2>/dev/null)
    # No runs yet: workflow_runs[0] is null, so jq emits "null null" and
    # read leaves concl="null" (created gets the second "null").
    if [ -z "${concl:-}" ] || [ "$concl" = "null" ]; then
        printf '  –  %-42s no runs\n' "$repo/$wf"
        continue
    fi
    # A green run may still have stopped on purpose; ask the run's steps before
    # calling it clean. Only on success — a red run is already reported as red.
    if [ "$concl" = "success" ] && [ -n "${run_id:-}" ] && [ "$run_id" != "null" ]; then
        hits=$(gh api "repos/$repo/actions/runs/$run_id/jobs" \
            -q "[.jobs[].steps[]? | select(.conclusion == \"success\")
                 | select(.name | startswith(\"$BLOCKED_STEP_PREFIX\"))] | length" 2>/dev/null)
        if [ "${hits:-0}" != "0" ] && [ -n "${hits:-}" ]; then
            blocked=$((blocked+1))
            printf '  ⏸  %-42s blocked — no release made (%s)\n' "$repo/$wf" "$(age "$created")"
            continue
        fi
    fi
    if [ "$concl" = "success" ]; then icon="✓"; else icon="✗"; fails=$((fails+1)); fi
    printf '  %s  %-42s %s (%s)\n' "$icon" "$repo/$wf" "$concl" "$(age "$created")"
done

echo
if [ "$fails" -eq 0 ] && [ "$blocked" -eq 0 ]; then
    echo "Overnight: all scheduled jobs green."
fi
# Separate `if`s, not `[ … ] && echo`: a false test as the script's last command
# would make it exit non-zero and read as a tool failure to /wake_up.
if [ "$fails" -gt 0 ]; then
    echo "Overnight: $fails job(s) not green — see above."
fi
if [ "$blocked" -gt 0 ]; then
    echo "Overnight: $blocked job(s) blocked at a gate — ran correctly, made no change; the reason is in the run summary / Slack."
fi
