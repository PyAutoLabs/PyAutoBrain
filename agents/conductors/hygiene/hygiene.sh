#!/usr/bin/env bash
# agents/conductors/hygiene/hygiene.sh — the Hygiene Agent (a PyAutoBrain
# reasoning conductor). The maintenance function — the organism's sense of its
# own upkeep: the code-quality debt that neither proves it works (that is Heart)
# nor measures the speed of modelling (that is profiling).
#
# Owns code-quality upkeep across the organism and emits a HygieneDecision the
# human/session executes, delegating the actual fixes to the dev-flow conductors
# (refactor/bug/feature) via ship_*. It reasons; it never edits source itself,
# never mutates a repo, and (like profiling) it stays stdlib/bash so it never
# drags the JAX stack into the Brain.
#
# Each mode does a cheap, read-only local PRE-SCAN and DELEGATES the full audit +
# any execution to the owning skill:
#   tidy  -> /repo_cleanup (Brain)         perf  -> /refactor (+ Heart timing legs)
#   noise -> /cli_noise_clean (Heart)      deps  -> /dep_audit (Heart)
#   docs  -> /audit_docs (Heart)
# The three Heart skills are read-only observation skills — measurement lives in
# Heart; hygiene routes and prioritises. perf's import timing runs in a
# SUBPROCESS, so the conductor itself never imports the science/JAX stack.
#
# Usage:
#   hygiene.sh                 # pre-scan across modes -> ranked worklist (default)
#   hygiene.sh perf            # import-cost timing (subprocess) -> /refactor + Heart legs
#   hygiene.sh tidy            # git debris pre-scan -> /repo_cleanup
#   hygiene.sh noise           # CLI-noise route -> /cli_noise_clean
#   hygiene.sh deps            # dependency-cap pre-scan -> /dep_audit
#   hygiene.sh docs            # API-docs pre-scan -> /audit_docs
#   hygiene.sh <mode> --json   # machine-readable HygieneDecision
#
# All five modes are live. The fast default scan DEFERS perf's import timing (it
# spawns real imports); run `hygiene perf` for it. Repos are read under
# PYAUTO_ROOT (default ~/Code/PyAutoLabs); import timing uses HYGIENE_PYTHON
# (default python3 — point it at the PyAuto venv to time the science libs).

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

# PYAUTO_ROOT is exported/defaulted by _common.sh (~/Code/PyAutoLabs). Scan the
# canonical checkouts there, never the worktree symlinks.
ROOT="${PYAUTO_ROOT:-$HOME/Code/PyAutoLabs}"
LIB_REPOS=(PyAutoConf PyAutoFit PyAutoArray PyAutoGalaxy PyAutoLens)
ORG_REPOS=(PyAutoBrain PyAutoBuild PyAutoHeart PyAutoMind)
DOC_REPOS=(PyAutoFit PyAutoGalaxy PyAutoLens)

# perf: import timing is measured in a subprocess with this interpreter (never
# imported into the conductor). Point HYGIENE_PYTHON at the PyAuto venv to time
# the science libs; HYGIENE_PERF_LIBS overrides the import names (tests use
# fast stdlib modules); HYGIENE_PERF_THRESHOLD (s) is the slow cutoff.
PERF_PY="${HYGIENE_PYTHON:-python3}"
PERF_THRESHOLD="${HYGIENE_PERF_THRESHOLD:-3.0}"
read -r -a PERF_LIBS <<< "${HYGIENE_PERF_LIBS:-autoconf autofit autoarray autogalaxy autolens}"

MODE_ORDER=(perf tidy noise deps docs)
declare -A MODE_DELEGATE=(
  [perf]="/refactor"
  [tidy]="/repo_cleanup"
  [noise]="/cli_noise_clean"
  [deps]="/dep_audit"
  [docs]="/audit_docs"
)
# A mode's pre-scan is one of a few kinds, which is what makes its count
# comparable (or not): 'debris' finds directly-removable items and 'timing'
# finds slow imports — both real, rankable counts; 'surface' only sizes the
# audit (the real problems emerge when the delegated skill runs — the count is
# NOT a problem count); 'advisory' has no cheap local signal. Only 'debris' and
# 'timing' counts drive the ranking.
declare -A MODE_KIND=(
  [perf]="timing" [tidy]="debris" [deps]="surface" [docs]="surface" [noise]="advisory"
)

# --- Pre-scan helpers (read-only; each echoes "count|one-line summary"). -------

# tidy: git debris across managed checkouts — stale branches, stashes, [gone]
# tracking refs, dirty trees. The prioritisable count is the total debris.
prescan_tidy() {
  local branches=0 stashes=0 gone=0 dirty=0 scanned=0 repo dir
  for repo in "${LIB_REPOS[@]}" "${ORG_REPOS[@]}"; do
    dir="$ROOT/$repo"
    [[ -d "$dir/.git" || -f "$dir/.git" ]] || continue
    scanned=$((scanned + 1))
    local b s g
    b=$(git -C "$dir" for-each-ref --format='%(refname:short)' refs/heads 2>/dev/null \
          | grep -vxE 'main|master|HEAD' | wc -l | tr -d ' ')
    s=$(git -C "$dir" stash list 2>/dev/null | wc -l | tr -d ' ')
    g=$(git -C "$dir" branch -vv 2>/dev/null | grep -c '\[gone\]' || true)
    branches=$((branches + b)); stashes=$((stashes + s)); gone=$((gone + g))
    [[ -n "$(git -C "$dir" status --porcelain 2>/dev/null)" ]] && dirty=$((dirty + 1))
  done
  local total=$((branches + stashes + gone + dirty))
  echo "${total}|${scanned} repos: ${branches} stale branches, ${stashes} stashes, ${gone} [gone] refs, ${dirty} dirty checkouts"
}

# deps: count capped dependency specifiers (<, <=, ==) in library pyproject.toml.
# A cheap "how many caps could be stale" signal; /dep_audit does the PyPI compare.
prescan_deps() {
  local caps=0 files=0 repo pj
  for repo in "${LIB_REPOS[@]}"; do
    pj="$ROOT/$repo/pyproject.toml"
    [[ -f "$pj" ]] || continue
    files=$((files + 1))
    local c
    c=$(grep -oE '[<>=!~]=?[[:space:]]*[0-9]' "$pj" 2>/dev/null | grep -cE '<|==' || true)
    caps=$((caps + c))
  done
  echo "${caps}|${caps} capped/pinned specifiers across ${files} library pyproject.toml"
}

# docs: count docs/api/*.rst files and currentmodule directives in the doc repos.
# /audit_docs does the actual import validation.
prescan_docs() {
  local rst=0 cm=0 repo d
  for repo in "${DOC_REPOS[@]}"; do
    d="$ROOT/$repo/docs/api"
    [[ -d "$d" ]] || continue
    local n c
    n=$(find "$d" -maxdepth 1 -name '*.rst' 2>/dev/null | wc -l | tr -d ' ')
    c=$(grep -rhE '^\s*\.\.\s+currentmodule::' "$d" 2>/dev/null | wc -l | tr -d ' ')
    rst=$((rst + n)); cm=$((cm + c))
  done
  echo "${cm}|${rst} api .rst files, ${cm} currentmodule directives across ${#DOC_REPOS[@]} repos"
}

# noise: no cheap local signal (needs running pytest + workspace scripts).
prescan_noise() {
  echo "-1|no cheap local signal — runs pytest + workspace scripts (PYAUTO_TEST_MODE=2)"
}

# perf: import-cost timing — time `import <pkg>` per library in a SUBPROCESS
# (best-effort; the conductor never imports the science stack itself). The count
# is the number of libraries whose import exceeds the slow threshold. Heavy
# dev-loop timing (slow tests / integration scripts) is already observed by
# PyAutoHeart's script_timing / test_run legs — perf points there and routes.
prescan_perf() {
  local slow=0 measured=0 detail="" pkg rc start end t
  for pkg in "${PERF_LIBS[@]}"; do
    [[ -n "$pkg" ]] || continue
    start=$(date +%s.%N)
    timeout 60 "$PERF_PY" -c "import ${pkg}" >/dev/null 2>&1; rc=$?
    end=$(date +%s.%N)
    if [[ $rc -ne 0 ]]; then detail+="${pkg}:n/a "; continue; fi
    measured=$((measured + 1))
    t=$(awk "BEGIN{printf \"%.2f\", ${end}-${start}}")
    detail+="${pkg}:${t}s "
    awk "BEGIN{exit !(${t} > ${PERF_THRESHOLD})}" && slow=$((slow + 1))
  done
  if [[ $measured -eq 0 ]]; then
    echo "-1|no library importable here (set HYGIENE_PYTHON to the PyAuto venv) — slow tests/scripts live in Heart (script_timing/test_run)"
  else
    echo "${slow}|${measured} libs timed, >${PERF_THRESHOLD}s = slow: ${detail}(slow tests/scripts: see Heart script_timing/test_run)"
  fi
}

prescan() {
  case "$1" in
    perf) prescan_perf ;; tidy) prescan_tidy ;; deps) prescan_deps ;;
    docs) prescan_docs ;; noise) prescan_noise ;;
  esac
}

# --- Arg parse. ----------------------------------------------------------------

mode="default"; json=0
for arg in "$@"; do
  case "$arg" in
    perf|tidy|noise|deps|docs) mode="$arg" ;;
    default) mode="default" ;;
    --json) json=1 ;;
    -h|--help|help) mode="help" ;;
    *) echo "hygiene: unknown argument '$arg' (modes: ${MODE_ORDER[*]}, --json)" >&2; exit 2 ;;
  esac
done

if [[ "$mode" == "help" ]]; then
  awk '/^# Usage:/{u=1;next} u{ if($0 ~ /^#   /){sub(/^#   /,"  "); print} else exit }' "$HERE/hygiene.sh"
  exit 0
fi

# perf's import timing spawns real imports, so the fast default scan defers it;
# an explicit `hygiene perf` runs it. This predicate decides which.
perf_deferred() { [[ "$1" == "perf" && "$mode" == "default" ]]; }

# --- JSON footing: a HygieneDecision the Brain session can consume. ------------
emit_json_row() { # mode
  local m="$1"
  if perf_deferred "$m"; then
    printf '{"mode":"perf","status":"deferred","hint":"run: pyauto-brain hygiene perf (import timings; skipped in the fast default scan)","delegate":"/refactor"}'
    return
  fi
  local res count summary kind status
  res="$(prescan "$m")"; count="${res%%|*}"; summary="${res#*|}"; kind="${MODE_KIND[$m]}"
  if   [[ "$kind" == "advisory" || "$count" == "-1" ]]; then status="advisory"
  elif [[ "$kind" == "surface" ]]; then status="surface"
  elif [[ "$count" == "0" ]]; then status="clean"
  else status="$kind"; fi   # debris | timing
  printf '{"mode":"%s","kind":"%s","status":"%s","count":%s,"summary":"%s","delegate":"%s"}' \
    "$m" "$kind" "$status" "$([[ "$count" == "-1" ]] && echo null || echo "$count")" \
    "${summary//\"/\\\"}" "${MODE_DELEGATE[$m]}"
}

if [[ "$json" -eq 1 ]]; then
  if [[ "$mode" == "default" ]]; then
    printf '{"decision":"HygieneDecision","mode":"default","rows":['
    sep=""
    for m in "${MODE_ORDER[@]}"; do printf '%s' "$sep"; emit_json_row "$m"; sep=","; done
    printf ']}\n'
  else
    printf '{"decision":"HygieneDecision","mode":"%s","row":' "$mode"; emit_json_row "$mode"; printf '}\n'
  fi
  exit 0
fi

# --- Human footing. ------------------------------------------------------------
echo "== HygieneDecision =="
echo "The hygiene conductor pre-scans code-quality debt (read-only) and delegates the"
echo "audit + fix to the owning skill — it never mutates a repo itself."
echo

render_delegate_line() { # mode
  local m="$1"
  if [[ "${MODE_KIND[$m]}" == "timing" ]]; then
    printf '  %-6s %-9s → route slow items to %s; slow tests/scripts → Heart script_timing/test_run\n' "" "" "${MODE_DELEGATE[$m]}"
  else
    printf '  %-6s %-9s → run %s for the full audit\n' "" "" "${MODE_DELEGATE[$m]}"
  fi
}

render_row() { # mode
  local m="$1"
  if perf_deferred "$m"; then
    printf '  %-6s %-9s %s\n' "perf" "run it" "import timings (subprocess) — run 'hygiene perf'; deferred in the fast default scan"
    render_delegate_line "$m"
    return
  fi
  local res count summary kind tag
  res="$(prescan "$m")"; count="${res%%|*}"; summary="${res#*|}"; kind="${MODE_KIND[$m]}"
  if   [[ "$kind" == "advisory" || "$count" == "-1" ]]; then tag="advisory"
  elif [[ "$kind" == "surface" ]]; then tag="surface"
  elif [[ "$count" == "0" ]]; then tag="clean"
  elif [[ "$kind" == "timing" ]]; then tag="${count} slow"
  else tag="${count} debris"; fi
  printf '  %-6s %-9s %s\n' "$m" "$tag" "$summary"
  render_delegate_line "$m"
}

if [[ "$mode" == "default" ]]; then
  # Only the 'debris'/'timing' pre-scans yield a directly-actionable count, and
  # perf's timing is deferred here (too slow for the fast scan) — so the default
  # recommendation ranks on tidy debris and points at the periodic audits.
  tidy_n="$(prescan tidy)"; tidy_n="${tidy_n%%|*}"
  for m in "${MODE_ORDER[@]}"; do render_row "$m"; done
  echo
  if [[ "$tidy_n" -gt 0 ]]; then
    echo "Recommended next: hygiene tidy (${tidy_n} removable debris items), then run /repo_cleanup."
    echo "  Then 'hygiene perf' for import timings; deps/docs/noise are periodic audits (surface only)."
  else
    echo "Recommended next: no removable debris — run 'hygiene perf' for import timings, and deps/docs/noise audits periodically."
  fi
  echo "Design: PyAutoMind research/pyautobrain/hygiene_agent_decision.md."
else
  render_row "$mode"
fi
exit 0
