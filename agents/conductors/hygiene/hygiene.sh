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
#   hygiene.sh perf --profile <script>  # cProfile a script, rank NON-likelihood hotspots -> /refactor
#   hygiene.sh tidy            # git debris pre-scan -> /repo_cleanup
#   hygiene.sh noise           # CLI-noise route -> /cli_noise_clean
#   hygiene.sh deps            # dependency-cap pre-scan -> /dep_audit
#   hygiene.sh docs            # API-docs pre-scan -> /audit_docs
#   hygiene.sh crlf            # executable scripts w/ CRLF break on HPC (+ cosmetic .py) -> /refactor
#   hygiene.sh config          # library config keys missing downstream -> /refactor
#   hygiene.sh artifacts       # tracked leaked outputs/data -> /repo_cleanup
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

MODE_ORDER=(perf tidy crlf artifacts noise deps docs config)
declare -A MODE_DELEGATE=(
  [perf]="/refactor"
  [tidy]="/repo_cleanup"
  [crlf]="/refactor"
  [artifacts]="/repo_cleanup"
  [noise]="/cli_noise_clean"
  [deps]="/dep_audit"
  [docs]="/audit_docs"
  [config]="/refactor"
)
# A mode's pre-scan is one of a few kinds, which is what makes its count
# comparable (or not): 'debris' finds directly-removable items and 'timing'
# finds slow imports — both real, rankable counts; 'surface' only sizes the
# audit (the real problems emerge when the delegated skill runs — the count is
# NOT a problem count); 'advisory' has no cheap local signal. Only 'debris' and
# 'timing' counts drive the ranking.
declare -A MODE_KIND=(
  [perf]="timing" [tidy]="debris" [crlf]="debris" [artifacts]="debris"
  [deps]="surface" [docs]="surface" [config]="surface" [noise]="advisory"
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

# crlf: CRLF line endings, split by severity. The count that MATTERS is
# executable scripts (`.sh` + shebang-executable `.py`, mode 755): a CRLF shebang
# (`#!/bin/bash\r`) breaks execution on Linux/HPC ("bad interpreter"). Library
# `.py` CRLF is COSMETIC (Python reads CRLF fine) — reported separately, not
# ranked, since mass-normalising it is a big diff for zero functional gain
# (the real fix there is `.gitattributes * text=auto`, going forward).
prescan_crlf() {
  local scripts=0 cosmetic=0 sdetail="" repo dir sh_n exe_list exe_n py_n
  for repo in "${LIB_REPOS[@]}" "${ORG_REPOS[@]}" autolens_workspace autogalaxy_workspace autofit_workspace; do
    dir="$ROOT/$repo"
    [[ -d "$dir/.git" || -f "$dir/.git" ]] || continue
    # .sh with CRLF (all shell scripts break)
    sh_n=$(git -C "$dir" grep -Il $'\r$' -- '*.sh' 2>/dev/null | wc -l | tr -d ' ')
    # executable .py (mode 755 — run directly, so a CRLF shebang breaks)
    exe_n=0
    exe_list=$(git -C "$dir" ls-files --stage -- '*.py' 2>/dev/null | awk '$1 ~ /755$/ {print $4}')
    [[ -n "$exe_list" ]] && exe_n=$(git -C "$dir" grep -Il $'\r$' -- $exe_list 2>/dev/null | wc -l | tr -d ' ')
    local repo_scripts=$((sh_n + exe_n))
    scripts=$((scripts + repo_scripts))
    [[ "$repo_scripts" -gt 0 ]] && sdetail+="${repo}:${repo_scripts} "
    # cosmetic: library .py with CRLF (informational)
    py_n=$(git -C "$dir" grep -Il $'\r$' -- '*.py' 2>/dev/null | wc -l | tr -d ' ')
    cosmetic=$((cosmetic + py_n))
  done
  echo "${scripts}|${scripts} executable scripts w/ CRLF (BREAK on HPC — normalise + add .gitattributes eol=lf): ${sdetail}; ${cosmetic} library .py w/ CRLF (cosmetic — leave, or '* text=auto' going forward)"
}

# artifacts: tracked files that look like leaked generated outputs — anything
# under a run-output dir (outputs?/, but NOT the output_test fixture dir) plus
# stray data-ext files outside dataset/test fixtures. Should be gitignored.
prescan_artifacts() {
  local total=0 detail="" repo dir n
  for repo in "${LIB_REPOS[@]}" "${ORG_REPOS[@]}" autolens_workspace autogalaxy_workspace autofit_workspace; do
    dir="$ROOT/$repo"
    [[ -d "$dir/.git" || -f "$dir/.git" ]] || continue
    local leaked
    leaked=$( { git -C "$dir" ls-files 2>/dev/null | grep -E '(^|/)outputs?/';
               git -C "$dir" ls-files -- '*.fits' '*.hdf5' '*.npy' '*.npz' '*.pkl' '*.pt' 2>/dev/null \
                 | grep -vE '(^|/)(dataset|test_|files|output_test)/'; } | sort -u | wc -l | tr -d ' ')
    total=$((total + leaked))
    [[ "$leaked" -gt 0 ]] && detail+="${repo}:${leaked} "
  done
  echo "${total}|${total} tracked files look like leaked outputs/data: ${detail}(fix: gitignore + git rm --cached)"
}

# config: keys present in a library config yaml but missing from the matching
# workspace config (the "mirror new library config keys downstream" chore).
# Uses a stdlib+PyYAML helper for a recursive key diff; degrades if PyYAML absent.
prescan_config() {
  local out
  out=$(python3 "$HERE/_hygiene_config.py" --root "$ROOT" 2>/dev/null)
  [[ -n "$out" ]] && echo "$out" || echo "0|config diff unavailable (PyYAML missing?)"
}

# noise: no cheap local signal (needs running pytest + workspace scripts).
prescan_noise() {
  echo "-1|no cheap local signal — runs pytest + workspace scripts (PYAUTO_TEST_MODE=2)"
}

# perf: prefer PyAutoHeart's tracked dev-loop timing legs (baseline + regression
# over time — the standing signals) when present; otherwise fall back to a
# one-shot import-cost timing, timing `import <pkg>` per library in a SUBPROCESS
# (the conductor never imports the science stack itself). The legs are the
# hygiene-perf family shipped alongside the conductor: import_time (import cost),
# unit_test_timing (slow unit tests), workspace_testmode_timing (TEST_MODE
# scripts) — each read only when its sidecar exists.
PERF_HEART_LEGS=(import_time unit_test_timing workspace_testmode_timing)
prescan_perf() {
  # --- Heart timing legs (preferred): the tracked over-time view. ------------
  local hs="${HEART_STATE_DIR:-$HOME/.pyauto-heart}" leg jf present=0 total=0 parts="" counts r y
  for leg in "${PERF_HEART_LEGS[@]}"; do
    jf="$hs/${leg}.json"
    [[ -f "$jf" ]] || continue
    counts=$(python3 - "$jf" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(int(d.get("red_count", 0)), int(d.get("yellow_count", 0)))
except Exception:
    pass
PY
)
    [[ -n "$counts" ]] || continue
    read -r r y <<< "$counts"
    present=$((present + 1)); total=$((total + r + y))
    parts+="${leg}:${r}r/${y}y "
  done
  if [[ "$present" -gt 0 ]]; then
    echo "${total}|Heart timing legs (${present}): ${parts}(regressions = red+yellow); refresh via the leg drivers (python -m heart.checks.<leg>)"
    return
  fi
  # --- Fallback: one-shot subprocess timing (no Heart reading available). -----
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
    crlf) prescan_crlf ;; artifacts) prescan_artifacts ;; config) prescan_config ;;
  esac
}

# --- Arg parse. ----------------------------------------------------------------

mode="default"; json=0; profile_script=""; expect_script=0
for arg in "$@"; do
  if [[ "$expect_script" -eq 1 ]]; then profile_script="$arg"; expect_script=0; continue; fi
  case "$arg" in
    perf|tidy|noise|deps|docs|crlf|config|artifacts) mode="$arg" ;;
    default) mode="default" ;;
    --json) json=1 ;;
    --profile) mode="perf"; expect_script=1 ;;
    --profile=*) mode="perf"; profile_script="${arg#*=}" ;;
    -h|--help|help) mode="help" ;;
    *) echo "hygiene: unknown argument '$arg' (modes: ${MODE_ORDER[*]}, --json, perf --profile <script>)" >&2; exit 2 ;;
  esac
done
if [[ "$expect_script" -eq 1 ]]; then
  echo "hygiene: --profile needs a script path" >&2; exit 2
fi

if [[ "$mode" == "help" ]]; then
  awk '/^# Usage:/{u=1;next} u{ if($0 ~ /^#   /){sub(/^#   /,"  "); print} else exit }' "$HERE/hygiene.sh"
  exit 0
fi

# perf --profile <script>: an on-demand cProfile run of a NORMAL-mode script,
# ranking the slowest NON-likelihood functions as /refactor candidates. The
# script runs under cProfile in a SUBPROCESS (HYGIENE_PYTHON — the science env),
# so the conductor never imports the science stack; the stdlib helper then ranks
# and applies the likelihood-exclusion filter. Heavy + per-target → on demand
# only, never the default scan or a Heart tick.
run_profile() {
  local script="$1"
  if [[ ! -f "$script" ]]; then
    echo "hygiene perf --profile: no such script '$script'" >&2; return 2
  fi
  local py="${HYGIENE_PYTHON:-python3}" out dir base rc
  out="$(mktemp)"; dir="$(cd "$(dirname "$script")" && pwd)"; base="$(basename "$script")"
  ( cd "$dir" && timeout "${HYGIENE_PROFILE_TIMEOUT:-600}" "$py" -m cProfile -o "$out" "$base" >/dev/null 2>&1 )
  rc=$?
  if [[ $rc -ne 0 || ! -s "$out" ]]; then
    rm -f "$out"
    echo "hygiene perf --profile: could not profile '$script' (rc=$rc; set HYGIENE_PYTHON to the science venv, e.g. ~/venv/PyAuto/bin/python)" >&2
    return 1
  fi
  if [[ "$json" -eq 1 ]]; then
    python3 "$HERE/_hygiene_profile.py" "$out" --json
  else
    echo "== HygieneDecision (perf --profile: $script) =="
    echo "Slowest NON-likelihood functions by self time (likelihood entry points + JAX compile excluded):"
    python3 "$HERE/_hygiene_profile.py" "$out"
    echo
    echo "→ route candidates to /refactor; a clear win may be a JAX-adaptation candidate (judgement, never automatic)."
    echo "  A hotspot inside the likelihood compute path belongs to /profiling, not hygiene."
  fi
  rm -f "$out"
}

if [[ -n "$profile_script" ]]; then
  run_profile "$profile_script"; exit $?
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
    printf '  %-9s %-9s → route slow items to %s; slow tests/scripts → Heart script_timing/test_run\n' "" "" "${MODE_DELEGATE[$m]}"
  else
    printf '  %-9s %-9s → run %s for the full audit\n' "" "" "${MODE_DELEGATE[$m]}"
  fi
}

render_row() { # mode
  local m="$1"
  if perf_deferred "$m"; then
    printf '  %-9s %-9s %s\n' "perf" "run it" "import timings (subprocess) — run 'hygiene perf'; deferred in the fast default scan"
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
  printf '  %-9s %-9s %s\n' "$m" "$tag" "$summary"
  render_delegate_line "$m"
}

if [[ "$mode" == "default" ]]; then
  # Only 'debris' pre-scans yield a directly-actionable count (perf's timing is
  # deferred here — too slow for the fast scan). Rank across all debris modes and
  # recommend the one with the most removable items.
  best=""; best_n=0
  for m in tidy crlf artifacts; do
    local_n="$(prescan "$m")"; local_n="${local_n%%|*}"
    if [[ "$local_n" -gt "$best_n" ]]; then best_n="$local_n"; best="$m"; fi
  done
  for m in "${MODE_ORDER[@]}"; do render_row "$m"; done
  echo
  if [[ -n "$best" ]]; then
    echo "Recommended next: hygiene ${best} (${best_n} items), then run ${MODE_DELEGATE[$best]}."
    echo "  Then 'hygiene perf' for import timings; config/deps/docs/noise are periodic audits (surface only)."
  else
    echo "Recommended next: no removable debris — run 'hygiene perf' for import timings, and config/deps/docs/noise audits periodically."
  fi
  echo "Design: PyAutoMind research/pyautobrain/hygiene_agent_decision.md."
else
  render_row "$mode"
fi
exit 0
