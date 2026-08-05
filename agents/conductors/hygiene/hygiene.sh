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
#   docs  -> /audit_docs (Heart)           packaging -> clean_slate.sh (Brain)
#   docstrings -> /refactor (exact findings; Hygiene remains read-only)
#   refs  -> /refactor (dead internal references in workspace prose)
#   optdeps -> /refactor (smoke-listed scripts missing an optional-dep skip guard)
#   extras  -> /bug (optional deps a library declares that the smoke CI leg never installs)
# The three Heart skills are read-only observation skills — measurement lives in
# Heart; hygiene routes and prioritises. perf's import timing runs in a
# SUBPROCESS, so the conductor itself never imports the science/JAX stack.
#
# Usage:
#   hygiene.sh                 # pre-scan across modes -> ranked worklist (default)
#   hygiene.sh perf            # import-cost timing (subprocess) -> /refactor + Heart legs
#   hygiene.sh perf --profile <script>  # cProfile a script, rank NON-likelihood hotspots -> /refactor
#   hygiene.sh tidy            # git debris pre-scan -> condemn into condemned.md (async, no per-item gate)
#   hygiene.sh sweep           # void condemned.md entries past sweep-after -> pyauto-gut void (repo_cleanup gates)
#   hygiene.sh noise           # CLI-noise route -> /cli_noise_clean
#   hygiene.sh deps            # dependency-cap pre-scan -> /dep_audit
#   hygiene.sh docs            # API-docs pre-scan -> /audit_docs
#   hygiene.sh crlf            # executable scripts w/ CRLF break on HPC (+ cosmetic .py) -> /refactor
#   hygiene.sh docstrings      # adjacent top-level script documentation -> /refactor
#   hygiene.sh refs            # dead internal references in workspace prose -> /refactor
#   hygiene.sh optdeps         # smoke-listed scripts w/ a gated API but no skip guard -> /refactor
#   hygiene.sh extras          # optional deps declared by a library but missing from the smoke CI install -> /bug
#   hygiene.sh config          # library config keys missing downstream + orphan config files -> /refactor
#   hygiene.sh artifacts       # tracked leaked outputs/data -> /repo_cleanup
#   hygiene.sh packaging       # ignored top-level *.egg-info/build dirs -> clean_slate.sh
#   hygiene.sh <mode> --json   # machine-readable HygieneDecision
#
# tidy + sweep are the PyAutoGut drive seam (the organ HOLDS and VOIDS; this
# conductor DECIDES what to condemn and WHEN to sweep, mirroring Heart <-> vitals).
# tidy files 95%-sure debris into the condemned.md manifest asynchronously (no
# synchronous per-item repo_cleanup interrogation); sweep runs the repo_cleanup
# safety gates in batch against entries whose transit window has expired.
#
# All modes are live. The fast default scan DEFERS perf's import timing (it
# spawns real imports); run `hygiene perf` for it. Repos are read under
# PYAUTO_ROOT (defaulted by _common.sh) and WHICH repos comes from the body map,
# never from a list here; import timing uses HYGIENE_PYTHON (default python3 —
# point it at the PyAuto venv to time the science libs). A scan that sees no
# checkouts reports `unscanned`, never `clean`.

set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$HERE/../../_common.sh"

# PYAUTO_ROOT is exported/defaulted by _common.sh. Scan the canonical checkouts
# there, never the worktree symlinks.
ROOT="$PYAUTO_ROOT"

# The scanned repo sets are DERIVED from the organism's body map (the Mind's
# repos.yaml — the single source of repo identity), never written out here. A
# hardcoded list drifts as the organism grows and the drift is INVISIBLE: a repo
# that is never scanned produces no findings, so the conductor reports a clean
# bill of health it has not earned. repos_sync.py's hygiene-coverage check fails
# if these stop matching the map, or if a repo name is written back into an
# array literal.
#
#   LIB_REPOS  the science libraries        ORG_REPOS  the organism's own repos
#   WS_REPOS   the user-facing workspaces
#
# BODY_MAP_OK separates "no repos DECLARED" (map unreachable) from "no repos
# PRESENT" (scan root empty) — both must report `unscanned`, never `clean`.
_body_map() { python3 "$HERE/_hygiene_repos.py" --category "$1" 2>/dev/null; }
mapfile -t LIB_REPOS < <(_body_map library)
mapfile -t ORG_REPOS < <(_body_map organ)
mapfile -t WS_REPOS  < <(_body_map workspace)
BODY_MAP_OK=1
[[ ${#LIB_REPOS[@]} -eq 0 && ${#ORG_REPOS[@]} -eq 0 ]] && BODY_MAP_OK=0

# CODE_REPOS — every repo the organism maintains as code (libraries + organs).
# SCAN_REPOS — those plus the user-facing workspaces, for the modes that read
# example scripts and prose as well as source.
CODE_REPOS=("${LIB_REPOS[@]}" "${ORG_REPOS[@]}")
SCAN_REPOS=("${CODE_REPOS[@]}" "${WS_REPOS[@]}")

# `deps` and `docs` each want a narrower set than "code repo", and both take it
# from what the checkout actually CONTAINS rather than from a category — because
# category alone gets it wrong. The config layer is an ORGAN in the body map yet
# ships a real distribution, so keying `deps` off `category: library` would
# silently drop it: the very bug this change repairs, re-created one line down.
# `docs` was pinned to three named repos and so never noticed a fourth acquiring
# Sphinx docs. Presence is the honest test in both cases.
repo_is_checked_out() { [[ -d "$ROOT/$1/.git" || -f "$ROOT/$1/.git" ]]; }
repo_ships_distribution() { [[ -f "$ROOT/$1/pyproject.toml" ]]; }
repo_ships_api_docs() { [[ -d "$ROOT/$1/docs/api" ]]; }

# MANAGED_PRESENT — how many declared repos are actually checked out under
# $ROOT. Zero means the repo-array modes saw NOTHING, and their counts would be
# 0 for that reason alone. Reporting that as `clean` is the same failure as
# reporting half the organism as clean, so they report `unscanned` + the reason.
#
# ARRAY_MODES is exactly the set this applies to: the modes that iterate the
# derived arrays. The helper-backed modes (docstrings/refs/optdeps/extras/config)
# DISCOVER their targets by walking $ROOT for workspace-shaped directories, so
# they can legitimately find material the body map never names — suppressing
# them here would hide real findings.
ARRAY_MODES=" tidy crlf artifacts deps docs packaging "
mode_reads_repo_arrays() { [[ "$ARRAY_MODES" == *" $1 "* ]]; }

MANAGED_PRESENT=0
for _repo in "${SCAN_REPOS[@]}"; do
  repo_is_checked_out "$_repo" && MANAGED_PRESENT=$((MANAGED_PRESENT + 1))
done
UNSCANNED_REASON=""
if [[ "$BODY_MAP_OK" -eq 0 ]]; then
  UNSCANNED_REASON="body map unreachable — the Mind checkout was not found (set PYAUTO_MIND)"
elif [[ "$MANAGED_PRESENT" -eq 0 ]]; then
  UNSCANNED_REASON="no managed checkouts under the scan root $ROOT (set PYAUTO_ROOT)"
fi

# PyAutoGut drive seam (tidy/sweep). The conductor DECIDES and emits a plan; the
# organ entrypoint performs the archive/void. GUT_CMD is referenced in the
# emitted plan, not executed here — the session/organ runs it. MIND holds the
# condemned.md catalog; transit-days is the default holding window a condemned
# item stays recoverable before it is eligible to be swept.
GUT_CMD="${PYAUTO_GUT:-pyauto-gut}"
MIND="$(resolve_mind 2>/dev/null || true)"
CONDEMN_MANIFEST="${MIND:+$MIND/condemned.md}"
CONDEMN_TRANSIT_DAYS="${HYGIENE_CONDEMN_TRANSIT_DAYS:-30}"

# perf: import timing is measured in a subprocess with this interpreter (never
# imported into the conductor). Point HYGIENE_PYTHON at the PyAuto venv to time
# the science libs; HYGIENE_PERF_LIBS overrides the import names (tests use
# fast stdlib modules); HYGIENE_PERF_THRESHOLD (s) is the slow cutoff.
PERF_PY="${HYGIENE_PYTHON:-python3}"
PERF_THRESHOLD="${HYGIENE_PERF_THRESHOLD:-3.0}"
read -r -a PERF_LIBS <<< "${HYGIENE_PERF_LIBS:-autoconf autofit autoarray autogalaxy autolens}"

MODE_ORDER=(perf tidy crlf docstrings refs optdeps extras artifacts packaging noise deps docs config)
declare -A MODE_DELEGATE=(
  [perf]="/refactor"
  [tidy]="condemn → condemned.md (async; 'hygiene sweep' voids)"
  [crlf]="/refactor"
  [docstrings]="/refactor"
  [refs]="/refactor"
  [optdeps]="/refactor"
  [extras]="/bug"
  [artifacts]="/repo_cleanup"
  [packaging]="PyAutoBrain/bin/clean_slate.sh --packaging"
  [noise]="/cli_noise_clean"
  [deps]="/dep_audit"
  [docs]="/audit_docs"
  [config]="/refactor"
)
# A mode's pre-scan is one of a few kinds, which is what makes its count
# comparable (or not): 'debris' finds directly-removable items, 'finding'
# confirms a source-quality defect, and 'timing' finds slow imports — all three
# are real, rankable counts; 'surface' only sizes the
# audit (the real problems emerge when the delegated skill runs — the count is
# NOT a problem count); 'advisory' has no cheap local signal. Only 'debris',
# 'finding', and 'timing' counts drive the ranking.
declare -A MODE_KIND=(
  [perf]="timing" [tidy]="debris" [crlf]="debris" [artifacts]="debris" [packaging]="debris"
  [docstrings]="finding" [refs]="finding" [optdeps]="finding" [extras]="finding"
  [deps]="surface" [docs]="surface" [config]="surface" [noise]="advisory"
)

# --- Pre-scan helpers (read-only; each echoes "count|one-line summary"). -------

# tidy: git debris across managed checkouts — stale branches, stashes, [gone]
# tracking refs, dirty trees. The prioritisable count is the total debris.
prescan_tidy() {
  local branches=0 stashes=0 gone=0 dirty=0 scanned=0 repo dir
  for repo in "${CODE_REPOS[@]}"; do
    dir="$ROOT/$repo"
    repo_is_checked_out "$repo" || continue
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
  echo "${total}|${scanned}/${#CODE_REPOS[@]} code repos: ${branches} stale branches, ${stashes} stashes, ${gone} [gone] refs, ${dirty} dirty checkouts"
}

# deps: count capped dependency specifiers (<, <=, ==) in every managed repo
# that ships a distribution. A cheap "how many caps could be stale" signal;
# /dep_audit does the PyPI compare.
prescan_deps() {
  local caps=0 files=0 scanned=0 repo pj
  for repo in "${CODE_REPOS[@]}"; do
    repo_is_checked_out "$repo" || continue
    scanned=$((scanned + 1))
    repo_ships_distribution "$repo" || continue
    pj="$ROOT/$repo/pyproject.toml"
    files=$((files + 1))
    local c
    c=$(grep -oE '[<>=!~]=?[[:space:]]*[0-9]' "$pj" 2>/dev/null | grep -cE '<|==' || true)
    caps=$((caps + c))
  done
  echo "${caps}|${caps} capped/pinned specifiers across ${files} pyproject.toml (${scanned}/${#CODE_REPOS[@]} code repos present)"
}

# docs: count docs/api/*.rst files and currentmodule directives in every managed
# repo that ships an api docs tree. /audit_docs does the actual import validation.
prescan_docs() {
  local rst=0 cm=0 doc_repos=0 scanned=0 repo d
  for repo in "${CODE_REPOS[@]}"; do
    repo_is_checked_out "$repo" || continue
    scanned=$((scanned + 1))
    repo_ships_api_docs "$repo" || continue
    doc_repos=$((doc_repos + 1))
    d="$ROOT/$repo/docs/api"
    local n c
    n=$(find "$d" -maxdepth 1 -name '*.rst' 2>/dev/null | wc -l | tr -d ' ')
    c=$(grep -rhE '^\s*\.\.\s+currentmodule::' "$d" 2>/dev/null | wc -l | tr -d ' ')
    rst=$((rst + n)); cm=$((cm + c))
  done
  echo "${cm}|${rst} api .rst files, ${cm} currentmodule directives across ${doc_repos} repos with docs/api (${scanned}/${#CODE_REPOS[@]} code repos present)"
}

# crlf: CRLF line endings, split by severity. The count that MATTERS is
# executable scripts (`.sh` + shebang-executable `.py`, mode 755): a CRLF shebang
# (`#!/bin/bash\r`) breaks execution on Linux/HPC ("bad interpreter"). Library
# `.py` CRLF is COSMETIC (Python reads CRLF fine) — reported separately, not
# ranked, since mass-normalising it is a big diff for zero functional gain
# (the real fix there is `.gitattributes * text=auto`, going forward).
prescan_crlf() {
  local scripts=0 cosmetic=0 scanned=0 sdetail="" repo dir sh_n exe_list exe_n py_n
  for repo in "${SCAN_REPOS[@]}"; do
    dir="$ROOT/$repo"
    repo_is_checked_out "$repo" || continue
    scanned=$((scanned + 1))
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
  echo "${scripts}|${scripts} executable scripts w/ CRLF (BREAK on HPC — normalise + add .gitattributes eol=lf): ${sdetail}; ${cosmetic} .py w/ CRLF (cosmetic — leave, or '* text=auto' going forward) across ${scanned}/${#SCAN_REPOS[@]} scanned repos"
}

# docstrings: confirmed adjacent module-level triple-quoted documentation
# expressions in user-facing *_workspace and HowTo* scripts. The stdlib AST
# helper provides the exact findings; this compact form feeds the default
# ranked worklist without mutating any scanned repository.
prescan_docstrings() {
  python3 "$HERE/_hygiene_docstrings.py" --root "$ROOT" --summary
}

# optdeps: smoke-listed workspace scripts that construct an optional-dependency
# gated API (e.g. TransformerNUFFT -> nufftax) without the house skip guard.
# Those scripts hard-fail the CI matrices that omit the optional extras, where a
# guarded script exits 0 and is reported as a skip. Scripts outside
# smoke_tests.txt are never flagged — a real error is correct for a user.
prescan_optdeps() {
  python3 "$HERE/_hygiene_optdeps.py" --root "$ROOT" --summary
}

# extras: the complement of optdeps — an optional dependency a library DECLARES
# (in its [optional] extra, which mode=release installs) that the
# workspace-validation mode=smoke leg never installs. The extras chain reaches
# each library's own [jax], never a sibling's [optional], so those have to be
# hand-added and silently drift. The symptom is a script red in smoke and green
# in release; the fix is always the install set, never the script.
prescan_extras() {
  python3 "$HERE/_hygiene_extras.py" --root "$ROOT" --summary
}

# refs: file/folder references in user-facing *_workspace and HowTo* prose
# (script docstrings/comments + the top-level README) whose target no longer
# exists. A restructure moves the target and the prose keeps the old name — the
# scripts still run, so no health sweep can see it. The stdlib helper resolves
# each reference against the checked-out repos (scripts/ and notebooks/ are one
# namespace) and holds precision with documented suppressions; this compact form
# feeds the default ranked worklist.
prescan_refs() {
  python3 "$HERE/_hygiene_refs.py" --root "$ROOT" --summary
}

# artifacts: tracked files that look like leaked generated outputs — anything
# under a run-output dir (outputs?/, but NOT the output_test fixture dir) plus
# stray data-ext files outside dataset/test fixtures. Should be gitignored.
prescan_artifacts() {
  local total=0 scanned=0 detail="" repo dir n
  for repo in "${SCAN_REPOS[@]}"; do
    dir="$ROOT/$repo"
    repo_is_checked_out "$repo" || continue
    scanned=$((scanned + 1))
    local leaked
    leaked=$( { git -C "$dir" ls-files 2>/dev/null | grep -E '(^|/)outputs?/' \
                 | grep -vE '(^|/)\.gitignore$';
               git -C "$dir" ls-files -- '*.fits' '*.hdf5' '*.npy' '*.npz' '*.pkl' '*.pt' 2>/dev/null \
                 | grep -vE '(^|/)(dataset|test_[A-Za-z0-9_]*|files|output_test)/'; } | sort -u | wc -l | tr -d ' ')
    total=$((total + leaked))
    [[ "$leaked" -gt 0 ]] && detail+="${repo}:${leaked} "
  done
  echo "${total}|${total} tracked files look like leaked outputs/data across ${scanned}/${#SCAN_REPOS[@]} scanned repos: ${detail}(fix: gitignore + git rm --cached)"
}

# packaging: ignored, fully-untracked Python packaging products at repository
# roots. The narrow depth + ignore + tracked-file guards deliberately exclude
# nested domain directories named build and any directory that owns source.
# Deliberately NOT filtered to repos that ship a pyproject.toml: the existing
# guards already establish that a hit is a packaging product, and requiring the
# manifest would only narrow detection.
prescan_packaging() {
  local total=0 scanned=0 detail="" dir repo candidate rel repo_count
  for repo in "${CODE_REPOS[@]}"; do
    dir="$ROOT/$repo"
    repo_is_checked_out "$repo" || continue
    scanned=$((scanned + 1))
    repo_count=0
    while IFS= read -r -d '' candidate; do
      rel="${candidate#"$dir"/}"
      git -C "$dir" check-ignore -q -- "$rel" 2>/dev/null || continue
      [[ -z "$(git -C "$dir" ls-files -- "$rel" 2>/dev/null)" ]] || continue
      total=$((total + 1)); repo_count=$((repo_count + 1))
    done < <(find "$dir" -mindepth 1 -maxdepth 1 -type d \
      \( -name '*.egg-info' -o -name build \) -print0 2>/dev/null)
    [[ "$repo_count" -gt 0 ]] && detail+="${repo}:${repo_count} "
  done
  echo "${total}|${total} ignored top-level packaging directories (*.egg-info/build) across ${scanned}/${#CODE_REPOS[@]} code repos present: ${detail}(clean: DRY_RUN=1 PyAutoBrain/bin/clean_slate.sh --packaging, then run without DRY_RUN)"
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
    crlf) prescan_crlf ;; docstrings) prescan_docstrings ;; refs) prescan_refs ;;
    optdeps) prescan_optdeps ;; extras) prescan_extras ;;
    artifacts) prescan_artifacts ;;
    packaging) prescan_packaging ;; config) prescan_config ;;
  esac
}

# --- Arg parse. ----------------------------------------------------------------

mode="default"; json=0; profile_script=""; expect_script=0
for arg in "$@"; do
  if [[ "$expect_script" -eq 1 ]]; then profile_script="$arg"; expect_script=0; continue; fi
  case "$arg" in
    perf|tidy|sweep|noise|deps|docs|crlf|docstrings|refs|optdeps|extras|config|artifacts|packaging) mode="$arg" ;;
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

# --- PyAutoGut drive seam: tidy (condemn) + sweep (void). ----------------------
# The conductor stays a planner: it enumerates candidates / reads the manifest
# and EMITS the plan (condemned.md entries + the exact pyauto-gut commands). The
# organ performs the archive/void; the session applies the filing. Nothing here
# mutates a repo — consistent with every other hygiene mode.

# enumerate_condemn_candidates — read-only: stale local branches (with merged
# status vs the default branch) and stashes across the managed checkouts. Echoes
# TSV rows: "<repo>\t<type>\t<locator>\t<merged>".
enumerate_condemn_candidates() {
  local repo dir def br
  for repo in "${CODE_REPOS[@]}"; do
    dir="$ROOT/$repo"
    repo_is_checked_out "$repo" || continue
    def=$(git -C "$dir" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@')
    [[ -n "$def" ]] || def=main
    while IFS= read -r br; do
      [[ -z "$br" ]] && continue
      case "$br" in main|master|HEAD|"$def") continue ;; esac
      local merged=no
      if git -C "$dir" merge-base --is-ancestor "$br" "origin/$def" 2>/dev/null \
         || git -C "$dir" merge-base --is-ancestor "$br" "$def" 2>/dev/null; then
        merged=yes
      fi
      printf '%s\tbranch\t%s\t%s\n' "$repo" "$br" "$merged"
    done < <(git -C "$dir" for-each-ref --format='%(refname:short)' refs/heads 2>/dev/null)
    local i=0 line
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      printf '%s\tstash\tstash@{%s}\tno\n' "$repo" "$i"; i=$((i + 1))
    done < <(git -C "$dir" stash list 2>/dev/null)
  done
}

# run_tidy — emit the async condemnation plan (no synchronous per-item gate).
run_tidy() {
  local rows; rows="$(enumerate_condemn_candidates)"
  local sweep_after; sweep_after="$(date -d "+${CONDEMN_TRANSIT_DAYS} days" +%F 2>/dev/null || echo "<today+${CONDEMN_TRANSIT_DAYS}d>")"
  if [[ "$json" -eq 1 ]]; then
    printf '{"decision":"HygieneDecision","mode":"tidy","action":"condemn","manifest":%s,"transit_days":%s,"sweep_after":"%s","candidates":[' \
      "$([[ -n "$CONDEMN_MANIFEST" ]] && printf '"%s"' "$CONDEMN_MANIFEST" || echo null)" \
      "$CONDEMN_TRANSIT_DAYS" "$sweep_after"
    local sep="" repo typ loc merged
    while IFS=$'\t' read -r repo typ loc merged; do
      [[ -z "$repo" ]] && continue
      printf '%s{"repo":"%s","type":"%s","locator":"%s","merged":"%s"}' "$sep" "$repo" "$typ" "$loc" "$merged"; sep=","
    done <<< "$rows"
    printf ']}\n'; return 0
  fi
  echo "== HygieneDecision (tidy → condemn) =="
  echo "PyAutoGut drive seam: file 95%-sure git debris into condemned.md ASYNC — no"
  echo "synchronous per-item gate. Nothing is deleted now; 'hygiene sweep' voids each"
  echo "entry once its transit window expires (recover a false positive until then)."
  echo
  if [[ -z "$rows" ]]; then
    echo "No condemn candidates (no stale branches/stashes in the checkouts under $ROOT)."
    [[ -z "$MIND" ]] && echo "(PyAutoMind checkout not found — set PYAUTO_MIND to locate condemned.md.)"
    return 0
  fi
  echo "Candidates → one condemned.md entry each (sweep-after ${sweep_after}):"
  local repo typ loc merged slug
  while IFS=$'\t' read -r repo typ loc merged; do
    [[ -z "$repo" ]] && continue
    if [[ "$typ" == "branch" && "$merged" == "yes" ]]; then
      echo "  - ${repo}:${loc} — merged branch → skips the pen: recommend straight delete."
    else
      slug="${repo,,}-${loc//[^A-Za-z0-9]/-}"
      echo "  - ${repo}:${loc} — ${typ}, unmerged → archive then condemn:"
      echo "      (cd $ROOT/$repo && $GUT_CMD archive ${loc} ${slug})"
      echo "      condemned.md: type=${typ} locator=${loc} merged=${merged} sweep-after=${sweep_after} archive-ref=refs/heads/archive/condemned/${slug}"
    fi
  done <<< "$rows"
  echo
  echo "File the batch async (no per-item interrogation); recover any false positive"
  echo "with '$GUT_CMD recover <slug>' until it is swept."
  [[ -n "$CONDEMN_MANIFEST" ]] && echo "Manifest: $CONDEMN_MANIFEST"
}

# run_sweep — read condemned.md, emit the batch void plan for past-due entries.
run_sweep() {
  if [[ -z "$CONDEMN_MANIFEST" ]]; then
    echo "hygiene sweep: PyAutoMind checkout not found — set PYAUTO_MIND to locate condemned.md" >&2
    return 4
  fi
  if [[ "$json" -eq 1 ]]; then
    python3 "$HERE/_hygiene_condemned.py" --manifest "$CONDEMN_MANIFEST" --json; return $?
  fi
  echo "== HygieneDecision (sweep → void) =="
  echo "Batch-void condemned.md entries whose transit window has expired. The organ"
  echo "performs the deletion; the existing repo_cleanup safety gates apply (no second"
  echo "gate). Reabsorb anything still wanted BEFORE sweeping."
  echo
  python3 "$HERE/_hygiene_condemned.py" --manifest "$CONDEMN_MANIFEST"
  echo
  local due_names
  due_names="$(python3 "$HERE/_hygiene_condemned.py" --manifest "$CONDEMN_MANIFEST" --json \
    | python3 -c 'import json,sys;print("\n".join(e["name"] for e in json.load(sys.stdin)["due"]))' 2>/dev/null)"
  if [[ -n "$due_names" ]]; then
    echo "Void plan (past sweep-after) — run each behind the repo_cleanup gate:"
    while IFS= read -r n; do [[ -n "$n" ]] && echo "  $GUT_CMD void ${n// /-}"; done <<< "$due_names"
  else
    echo "Nothing due — no entry has reached its sweep-after date. Pending entries stay recoverable."
  fi
}

if [[ "$mode" == "tidy"  ]]; then run_tidy;  exit $?; fi
if [[ "$mode" == "sweep" ]]; then run_sweep; exit $?; fi

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
  # A repo-array mode that saw no repositories reports `unscanned`, NOT `clean`.
  # Its count would be 0 for want of anything to count, and a consumer cannot
  # tell the two apart from a zero alone.
  if [[ -n "$UNSCANNED_REASON" ]] && mode_reads_repo_arrays "$m"; then
    printf '{"mode":"%s","kind":"%s","status":"unscanned","count":null,"repos_present":0,"reason":"%s","delegate":"%s"}' \
      "$m" "${MODE_KIND[$m]}" "${UNSCANNED_REASON//\"/\\\"}" "${MODE_DELEGATE[$m]}"
    return
  fi
  if [[ "$m" == "docstrings" ]]; then
    python3 "$HERE/_hygiene_docstrings.py" --root "$ROOT" --json-row
    return
  fi
  if [[ "$m" == "refs" ]]; then
    python3 "$HERE/_hygiene_refs.py" --root "$ROOT" --json-row
    return
  fi
  if [[ "$m" == "optdeps" ]]; then
    python3 "$HERE/_hygiene_optdeps.py" --root "$ROOT" --json-row
    return
  fi
  if [[ "$m" == "extras" ]]; then
    python3 "$HERE/_hygiene_extras.py" --root "$ROOT" --json-row
    return
  fi
  local res count summary kind status
  res="$(prescan "$m")"; count="${res%%|*}"; summary="${res#*|}"; kind="${MODE_KIND[$m]}"
  if   [[ "$kind" == "advisory" || "$count" == "-1" ]]; then status="advisory"
  elif [[ "$kind" == "surface" ]]; then status="surface"
  elif [[ "$count" == "0" ]]; then status="clean"
  else status="$kind"; fi   # debris | timing
  printf '{"mode":"%s","kind":"%s","status":"%s","count":%s,"repos_present":%s,"summary":"%s","delegate":"%s"}' \
    "$m" "$kind" "$status" "$([[ "$count" == "-1" ]] && echo null || echo "$count")" \
    "$MANAGED_PRESENT" "${summary//\"/\\\"}" "${MODE_DELEGATE[$m]}"
}

if [[ "$json" -eq 1 ]]; then
  if [[ "$mode" == "default" ]]; then
    printf '{"decision":"HygieneDecision","mode":"default","scan_root":"%s","repos_declared":%s,"repos_present":%s,%s"rows":[' \
      "${ROOT//\"/\\\"}" "${#SCAN_REPOS[@]}" "$MANAGED_PRESENT" \
      "$([[ -n "$UNSCANNED_REASON" ]] && printf '"unscanned_reason":"%s",' "${UNSCANNED_REASON//\"/\\\"}")"
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
if [[ -n "$UNSCANNED_REASON" ]]; then
  echo "!! SCANNED 0 REPOS — every 'unscanned' row below means nothing was LOOKED AT,"
  echo "   not that the organism is clean:"
  echo "   $UNSCANNED_REASON"
  echo
fi

render_delegate_line() { # mode
  local m="$1"
  if [[ "$m" == "tidy" ]]; then
    printf '  %-9s %-9s → hygiene tidy condemns these into condemned.md (async); hygiene sweep voids past-due\n' "" ""
    return
  fi
  if [[ "$m" == "docstrings" || "$m" == "refs" || "$m" == "optdeps" ]]; then
    printf '  %-9s %-9s → route exact findings to /refactor; Hygiene never edits source\n' "" ""
    return
  fi
  if [[ "$m" == "extras" ]]; then
    printf '  %-9s %-9s → route the missing installs to /bug; fix the CI install set, never the script\n' "" ""
    return
  fi
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
  if [[ -n "$UNSCANNED_REASON" ]] && mode_reads_repo_arrays "$m"; then
    printf '  %-9s %-9s %s\n' "$m" "unscanned" "no repository was read — $UNSCANNED_REASON"
    return
  fi
  local res count summary kind tag
  res="$(prescan "$m")"; count="${res%%|*}"; summary="${res#*|}"; kind="${MODE_KIND[$m]}"
  if [[ "$m" == "docstrings" && "$summary" != *"; 0 parse errors" ]]; then tag="partial"
  elif [[ "$kind" == "advisory" || "$count" == "-1" ]]; then tag="advisory"
  elif [[ "$kind" == "surface" ]]; then tag="surface"
  elif [[ "$count" == "0" ]]; then tag="clean"
  elif [[ "$kind" == "timing" ]]; then tag="${count} slow"
  elif [[ "$kind" == "finding" ]]; then tag="${count} findings"
  else tag="${count} debris"; fi
  printf '  %-9s %-9s %s\n' "$m" "$tag" "$summary"
  render_delegate_line "$m"
}

if [[ "$mode" == "docstrings" ]]; then
  echo "Confirmed adjacent top-level documentation blocks (read-only scan):"
  python3 "$HERE/_hygiene_docstrings.py" --root "$ROOT"
  echo
  echo "→ route the mechanical merges to /refactor; Hygiene never edits source."
elif [[ "$mode" == "refs" ]]; then
  echo "Dead internal references in workspace prose (read-only scan):"
  python3 "$HERE/_hygiene_refs.py" --root "$ROOT"
  echo
  echo "→ route the re-points to /refactor; Hygiene never edits source. Each finding is"
  echo "  the reference AS WRITTEN — judge the intended target before repointing (a moved"
  echo "  file, a file that became a directory, or a reference meant for a sibling repo)."
elif [[ "$mode" == "optdeps" ]]; then
  echo "Smoke-listed scripts missing an optional-dependency skip guard (read-only scan):"
  python3 "$HERE/_hygiene_optdeps.py" --root "$ROOT"
elif [[ "$mode" == "extras" ]]; then
  echo "Optional dependencies the workspace-validation smoke leg never installs (read-only scan):"
  python3 "$HERE/_hygiene_extras.py" --root "$ROOT"
elif [[ "$mode" == "config" ]]; then
  echo "Library config keys absent downstream + orphan config files (read-only scan):"
  python3 "$HERE/_hygiene_config.py" --root "$ROOT" --detail \
    || echo "config diff unavailable (PyYAML missing?)"
  echo
  echo "→ route the mirrors/removals to /refactor; Hygiene never edits source. This is a"
  echo "  SURFACE signal — judge each item before acting: a workspace may omit a library"
  echo "  key deliberately, and an orphan file may be read by something the library set"
  echo "  does not encode (add its owner to ORPHAN_OWNERS rather than deleting it)."
elif [[ "$mode" == "default" ]]; then
  # 'debris' and 'finding' pre-scans yield directly-actionable counts (perf's
  # timing is deferred here — too slow for the fast scan). Rank across them and
  # recommend the mode with the largest confirmed workload.
  best=""; best_n=0
  for m in tidy crlf docstrings refs optdeps extras artifacts packaging; do
    local_n="$(prescan "$m")"; local_n="${local_n%%|*}"
    if [[ "$local_n" -gt "$best_n" ]]; then best_n="$local_n"; best="$m"; fi
  done
  for m in "${MODE_ORDER[@]}"; do render_row "$m"; done
  echo
  if [[ -n "$best" ]]; then
    # Real findings still lead, even when the repo-array modes scanned nothing —
    # the helper-backed modes discover their own targets, so their findings are
    # genuine. The caveat says the RANKING is partial, not that the work is.
    echo "Recommended next: hygiene ${best} (${best_n} items), then run ${MODE_DELEGATE[$best]}."
    echo "  Then 'hygiene perf' for import timings; config/deps/docs/noise are periodic audits (surface only)."
    if [[ -n "$UNSCANNED_REASON" ]]; then
      echo "  CAVEAT: the repo-array modes scanned 0 of ${#SCAN_REPOS[@]} declared repos, so this"
      echo "  ranking is partial — ${UNSCANNED_REASON}."
    fi
  elif [[ -n "$UNSCANNED_REASON" ]]; then
    echo "Recommended next: fix the scan first — this is NOT a clean bill of health."
    echo "  The repo-array modes scanned 0 of ${#SCAN_REPOS[@]} declared repos under $ROOT:"
    echo "  ${UNSCANNED_REASON}."
  else
    echo "Recommended next: no direct findings or removable debris — run 'hygiene perf' for import timings, and config/deps/docs/noise audits periodically."
  fi
  echo "Design: PyAutoMind research/pyautobrain/hygiene_agent_decision.md."
else
  render_row "$mode"
fi
exit 0
