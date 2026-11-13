# agents/conductors/release/_nightly_lib.sh — token refresh + run polling for
# the nightly driver. Sourced by nightly.sh after _common.sh; the tests source
# it on its own.
#
# A GitHub App installation token lives 60 minutes and the nightly job runs for
# hours. refresh_gh_token re-mints GH_TOKEN once it is 45 minutes old, and
# await_run polls a run (refreshing as it goes) instead of one long blocking
# `gh run watch` that dies with "HTTP 401: Bad credentials" when the token
# expires underneath it.
#
# Without APP_CLIENT_ID + APP_PRIVATE_KEY (a local run on a personal gh login)
# refresh_gh_token does nothing.

_NIGHTLY_LIB_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# The workflow mints the first token seconds before the driver starts.
_GH_TOKEN_MINTED_AT="$(date +%s)"
_GH_TOKEN_MAX_AGE=2700   # 45 min: refresh well inside the 60-min life

# refresh_gh_token [--force] — re-mint GH_TOKEN when it is old (or always with
# --force). Returns 1, with the reason on stderr, if a mint fails.
refresh_gh_token() {
  [[ -z "${APP_CLIENT_ID:-}" || -z "${APP_PRIVATE_KEY:-}" ]] && return 0
  local now token
  now="$(date +%s)"
  if [[ "${1:-}" != "--force" ]] && (( now - _GH_TOKEN_MINTED_AT <= _GH_TOKEN_MAX_AGE )); then
    return 0
  fi
  if [[ -n "${NIGHTLY_MINT_CMD:-}" ]]; then
    token="$($NIGHTLY_MINT_CMD)" || token=""
  else
    token="$(python3 "$_NIGHTLY_LIB_DIR/../../../bin/gh_app_token.py")" || token=""
  fi
  if [[ -z "$token" ]]; then
    echo "nightly: could not mint a fresh GitHub App token (see above)" >&2
    return 1
  fi
  export GH_TOKEN="$token"
  _GH_TOKEN_MINTED_AT="$now"
  printf '== nightly: GitHub token refreshed\n'
}

# await_run <repo> <run_id> — poll until the run completes.
# Returns 0 success, 2 completed with any other conclusion, 4 could not
# observe the run (5 failed reads in a row, even after re-minting the token).
await_run() {
  local repo="$1" run_id="$2" interval="${NIGHTLY_POLL_SECONDS:-60}"
  local fails=0 out status conclusion last="" err
  err="$(mktemp "${TMPDIR:-/tmp}/nightly-await.XXXXXX")"
  while :; do
    refresh_gh_token || true
    if out="$(gh run view "$run_id" -R "$repo" --json status,conclusion 2>"$err")" \
       && out="$(printf '%s' "$out" | python3 -c 'import json, sys
r = json.load(sys.stdin)
print(r["status"], r.get("conclusion") or "")' 2>>"$err")"; then
      fails=0
      read -r status conclusion <<< "$out"
      if [[ "$status" != "$last" ]]; then
        printf '== nightly: run %s %s\n' "$run_id" "$status"
        last="$status"
      fi
      if [[ "$status" == "completed" ]]; then
        rm -f "$err"
        [[ "$conclusion" == "success" ]] && return 0
        printf '== nightly: run %s concluded %s\n' "$run_id" "${conclusion:-unknown}"
        return 2
      fi
    else
      fails=$((fails + 1))
      echo "nightly: could not read run $run_id ($fails/5): $(head -c 200 "$err")" >&2
      (( fails >= 5 )) && { rm -f "$err"; return 4; }
      refresh_gh_token --force || true
    fi
    sleep "$interval"
  done
}

# dispatch_and_await <repo> <workflow> <inputs-json> [<artifact> <dest-dir>]
# Dispatches, resolves the run id, polls it to completion (await_run, which
# keeps the token fresh), and optionally downloads an artifact. Returns 0 ok,
# 1 dispatch failed, 2 run red, 3 artifact missing, 4 lost the watch (the run
# was never judged — callers treat it as a driver error).
dispatch_and_await() {
  local repo="$1" wf="$2" inputs="$3" artifact="${4:-}" dest="${5:-}"
  local before run_id rc
  # The step 6 dispatch comes hours in: never dispatch on a stale token.
  refresh_gh_token
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
  LAST_RUN_URL="https://github.com/$repo/actions/runs/$run_id"
  LAST_RUN_ID="$run_id"
  await_run "$repo" "$run_id"
  rc=$?
  [[ $rc -eq 4 ]] && return 4
  if [[ $rc -ne 0 ]]; then
    # The report artifacts upload `if: always()`, so a FAILED run still carries
    # the evidence of which scripts failed — fetch it so the page can name
    # them. Best-effort: paging must never be blocked by a missing artifact.
    if [[ -n "$artifact" ]]; then
      refresh_gh_token
      gh run download "$run_id" -R "$repo" -n "$artifact" -D "$dest" 2>/dev/null \
        || echo "nightly: failed run's artifact '$artifact' not downloadable" >&2
    fi
    return 2
  fi
  if [[ -n "$artifact" ]]; then
    refresh_gh_token
    gh run download "$run_id" -R "$repo" -n "$artifact" -D "$dest" || return 3
  fi
  return 0
}

# rehearsal_record <artifacts-dir> <commit-shas-out> — the rehearsal's own
# record (PyAutoHands#337 "Caller contract"): writes rehearsal.json's
# `commit_shas` to <commit-shas-out> as {bare repo: sha} and prints its run id.
# Returns 1, with the reason on stderr, when there is no usable record — no
# rehearsal.json, a pre-#337 one without `commit_shas`, or no digit run id.
rehearsal_record() {
  python3 - "$1" "$2" <<'PY'
import json, re, sys
from pathlib import Path
d, out = Path(sys.argv[1]), Path(sys.argv[2])
cands = ([d / "rehearsal.json"] if (d / "rehearsal.json").is_file() else []) \
    + sorted(p for p in d.rglob("rehearsal.json") if p != d / "rehearsal.json")
for p in cands:
    try:
        rec = json.loads(p.read_text())
    except (OSError, ValueError):
        continue
    shas, run = rec.get("commit_shas"), str(rec.get("run_id") or "")
    if isinstance(shas, dict) and shas and re.fullmatch(r"\d+", run):
        out.write_text(json.dumps(shas, indent=2, sort_keys=True) + "\n")
        print(run)
        sys.exit(0)
print(f"nightly: no rehearsal record (rehearsal.json with run_id and commit_shas) under {d}",
      file=sys.stderr)
sys.exit(1)
PY
}

# live_release_inputs <minor> <rehearsal-run-id> <commit-shas-file> — the
# live release.yml inputs: `rehearsal_run_id` (required by #337) and the
# compact `commit_shas` JSON string the run cross-checks against the record.
live_release_inputs() {
  python3 - "$1" "$2" "$3" <<'PY'
import json, re, sys
minor, run, path = sys.argv[1:4]
if not re.fullmatch(r"\d+", run):
    sys.exit(f"nightly: rehearsal run id {run!r} is not a run id")
shas = json.loads(open(path).read())
print(json.dumps({"rehearsal": "false", "minor_version": minor,
                  "rehearsal_run_id": run,
                  "commit_shas": json.dumps(shas, separators=(",", ":"), sort_keys=True)}))
PY
}
