#!/usr/bin/env bash
#
# overnight_status.sh — latest scheduled-workflow run conclusions across the
# PyAuto organism. Pure `gh` API — needs no local checkout, so it runs on the
# CLI, on mobile Claude Code chat, and in Codex alike.
#
# Output: one line per job — icon  owner/repo/workflow  conclusion (age).

set -u
command -v gh >/dev/null 2>&1 || { echo "gh not found — cannot fetch run status" >&2; exit 1; }

# owner/repo:workflow-file  (owner defaults to PyAutoLabs when omitted). The
# passive morning webhooks (morning_health / morning_status) are excluded —
# /morning is their interactive complement, not a re-run of them.
JOBS=(
  "PyAutoBrain:nightly-release.yml"
  "PyAutoHeart:heart-health.yml"
  "PyAutoHeart:workspace-validation.yml"
  "PyAutoBuild:python_matrix.yml"
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

fails=0
for job in "${JOBS[@]}"; do
    repo="${job%%:*}"; wf="${job##*:}"
    [[ "$repo" == */* ]] || repo="PyAutoLabs/$repo"
    read -r concl created < <(gh api "repos/$repo/actions/workflows/$wf/runs?per_page=1" \
        -q '.workflow_runs[0] | "\(.conclusion // .status) \(.created_at)"' 2>/dev/null)
    if [ -z "${concl:-}" ] || [ "$concl" = "null null" ]; then
        printf '  –  %-42s no runs\n' "$repo/$wf"
        continue
    fi
    if [ "$concl" = "success" ]; then icon="✓"; else icon="✗"; fails=$((fails+1)); fi
    printf '  %s  %-42s %s (%s)\n' "$icon" "$repo/$wf" "$concl" "$(age "$created")"
done

echo
if [ "$fails" -eq 0 ]; then
    echo "Overnight: all scheduled jobs green."
else
    echo "Overnight: $fails job(s) not green — see above (e.g. a blocked nightly-release)."
fi
