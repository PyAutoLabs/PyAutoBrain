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
