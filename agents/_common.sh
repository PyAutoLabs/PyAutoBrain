#!/usr/bin/env bash
# agents/_common.sh — shared helpers for PyAutoAgent agents.
#
# Resolves the sibling PyAuto CLIs (pyauto-pulse, autobuild) the same way the
# autobuild shim resolves pyauto-pulse: prefer PATH, fall back to the sibling
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
  echo "pyauto-agent: '$name' not found on PATH or at $fallback" >&2
  echo "  Clone the sibling repo under $PYAUTO_ROOT and add its bin/ to PATH." >&2
  return 127
}

resolve_pulse() {
  _resolve_bin pyauto-pulse "$PYAUTO_ROOT/PyAutoPulse/bin/pyauto-pulse"
}

resolve_autobuild() {
  _resolve_bin autobuild "$PYAUTO_ROOT/PyAutoBuild/bin/autobuild"
}

# readiness_verdict — run `pyauto-pulse readiness --json` and echo the verdict
# string (green/yellow/red). Returns non-zero if Pulse can't be resolved/run.
readiness_verdict() {
  local pulse
  pulse="$(resolve_pulse)" || return $?
  "$pulse" readiness --json | python3 -c 'import json,sys; print(json.load(sys.stdin).get("verdict","unknown"))'
}
