#!/usr/bin/env bash
# agents/_common.sh — shared helpers for PyAutoBrain's specialist agents.
#
# Resolves the sibling PyAuto organ CLIs (pyauto-heart, autobuild) the same way
# the autobuild shim resolves them: prefer PATH, fall back to the sibling
# checkout under ~/Code/PyAutoLabs/. Nothing here is pip-installed.

PYAUTO_ROOT="${PYAUTO_ROOT:-$HOME/Code/PyAutoLabs}"

# _resolve_bin <command-name> <fallback-path> — echo a runnable invocation or
# print an install hint to stderr and return 127.
_resolve_bin() {
  local name="$1" fallback="$2"
  if command -v "$name" >/dev/null 2>&1; then
    printf '%s' "$name"
    return 0
  fi
  if [[ -x "$fallback" ]]; then
    printf '%s' "$fallback"
    return 0
  fi
  echo "pyauto-brain: '$name' not found on PATH or at $fallback" >&2
  echo "  Clone the sibling repo under $PYAUTO_ROOT and add its bin/ to PATH." >&2
  return 127
}

# resolve_heart — locate the PyAutoHeart CLI (the health authority of the
# organism). The former name was `pyauto-pulse`; PyAutoHeart keeps that as a
# back-compat shim, but the canonical command is `pyauto-heart`.
resolve_heart() {
  _resolve_bin pyauto-heart "$PYAUTO_ROOT/PyAutoHeart/bin/pyauto-heart"
}

resolve_autobuild() {
  _resolve_bin autobuild "$PYAUTO_ROOT/PyAutoBuild/bin/autobuild"
}

# _resolve_dir <env-var-name> <repo-name> — echo the path to a sibling PyAuto
# *repository checkout* (not a binary), or print a hint to stderr and return 1.
# Organs like PyAutoMind and PyAutoMemory are markdown knowledge bases with no
# CLI: the Brain reasons over their files directly. Resolution order: an explicit
# env override (e.g. PYAUTO_MIND), then $PYAUTO_ROOT/<repo>, then a couple of
# common dev layouts ($HOME/<repo>, $HOME/Code/<repo>).
_resolve_dir() {
  local var="$1" repo="$2" override="${!1:-}" c
  if [[ -n "$override" && -d "$override" ]]; then printf '%s' "$override"; return 0; fi
  # The parent of this PyAutoBrain checkout is the most reliable sibling root
  # (organs are typically cloned side by side), so check it first.
  local brain_parent
  brain_parent="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
  for c in "$brain_parent/$repo" "$PYAUTO_ROOT/$repo" "$HOME/$repo" \
           "$HOME/Code/$repo" "$HOME/Code/PyAutoLabs/$repo"; do
    if [[ -d "$c" ]]; then printf '%s' "$c"; return 0; fi
  done
  echo "pyauto-brain: '$repo' checkout not found (set $var, or clone it beside PyAutoBrain / under $PYAUTO_ROOT)" >&2
  return 1
}

# resolve_mind — locate the PyAutoMind checkout (the organism's intent store).
resolve_mind() { _resolve_dir PYAUTO_MIND PyAutoMind; }

# resolve_memory — locate the PyAutoMemory checkout (the organism's long-term
# scientific/architectural knowledge). Optional: the Feature Agent degrades
# gracefully when memory is absent rather than inventing context.
resolve_memory() { _resolve_dir PYAUTO_MEMORY PyAutoMemory; }

# readiness_verdict — run `pyauto-heart readiness --json` and echo the verdict
# string (green/yellow/red). Returns non-zero if Heart can't be resolved/run.
readiness_verdict() {
  local heart
  heart="$(resolve_heart)" || return $?
  "$heart" readiness --json | python3 -c 'import json,sys; print(json.load(sys.stdin).get("verdict","unknown"))'
}

# _agents_dir — directory holding the sibling agents (this file lives in it).
_agents_dir() {
  cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd
}

# consult_health_agent_verdict [--refresh] — ask the *sibling Health Agent* for
# the readiness verdict, rather than querying PyAutoHeart directly. This is the
# Brain-agent-consults-Brain-agent pattern: a specialist agent reasons *with*
# another specialist agent, and only the Health Agent talks to the Heart organ.
# It keeps the Build Agent decoupled from Heart's surface and lets future agents
# (Feature, Release, ...) consult one another the same way.
#
#   --refresh   ask the Health Agent to refresh Heart's state first (a fresh
#               gate); release-grade work uses this, ordinary build work does not.
#
# Echoes one of: green | yellow | red | unknown. Never fails the caller — an
# unresolvable/again-unknown verdict is reported as "unknown" (treated as YELLOW
# by callers), never silently as green.
consult_health_agent_verdict() {
  local refresh=0
  [[ "${1:-}" == "--refresh" ]] && refresh=1
  local health
  health="$(_agents_dir)/health/health.sh"
  if [[ ! -f "$health" ]]; then
    echo "unknown"
    return 0
  fi
  if [[ "$refresh" -eq 1 ]]; then
    bash "$health" tick >/dev/null 2>&1 || true
  fi
  # Capture into a variable rather than piping straight out: the caller may have
  # `set -o pipefail`, under which a non-zero exit from the (possibly
  # Heart-less) Health Agent would otherwise double-fire a fallback. The python
  # below always prints exactly one token, even on empty/garbage input.
  local out
  out="$(bash "$health" readiness --json 2>/dev/null | python3 -c '
import json, sys
try:
    v = json.load(sys.stdin).get("verdict", "unknown")
    print(v or "unknown")
except Exception:
    print("unknown")
' 2>/dev/null)"
  printf '%s\n' "${out:-unknown}"
}
