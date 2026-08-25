#!/usr/bin/env bash
# SessionStart hook — Python 3.12 is the default interpreter in Claude Code
# web/mobile sessions.
#
# The remote container ships `/usr/local/bin/python3 -> python3.11` and a
# uv-managed `pytest` built on 3.11 with no PyYAML, so a mobile session ran on
# an interpreter BELOW the floor the organism set for itself in the Python
# 3.12 floor campaign, and `pytest tests/` died at import on `yaml` before a
# single test ran.
#
# This hook builds one small 3.12 virtualenv per container and puts it first on
# PATH, so `python`, `python3`, `pip` and `pytest` all mean 3.12 with exactly
# the dependency set CI installs (pytest + PyYAML) — a mobile session and the
# `pytest (3.12)` CI leg then run the same interpreter and the same packages.
# 3.13 stays reachable as `/usr/bin/python3.13` for the two-version checks.
#
# Remote-only (a local checkout keeps whatever the developer's shell provides),
# idempotent (the venv is reused once the container image is cached), and
# non-blocking: if no 3.12 can be found the hook logs why and leaves PATH alone
# rather than failing the session start.
set -euo pipefail

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

VENV="${PYAUTO_SESSION_VENV:-$HOME/.pyauto/session-py312}"
DEPS=(pytest PyYAML)

# stderr, not stdout: a SessionStart hook's stdout is fed to the agent as
# session context.
log() { printf '[session-start] %s\n' "$*" >&2; }

is_py312() {
    [ -x "$1" ] && "$1" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))' >/dev/null 2>&1
}

find_base_python() {
    local candidate
    for candidate in /usr/bin/python3.12 /usr/local/bin/python3.12 \
                     "$(command -v python3.12 2>/dev/null || true)"; do
        if [ -n "$candidate" ] && is_py312 "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    # No system 3.12 (a future base image could drop it) — uv can fetch one.
    if command -v uv >/dev/null 2>&1; then
        log "no system python3.12; asking uv to install one"
        uv python install 3.12 >&2 || return 1
        candidate="$(uv python find 3.12 2>/dev/null || true)"
        if [ -n "$candidate" ] && is_py312 "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    fi
    return 1
}

venv_ready() {
    is_py312 "$VENV/bin/python" \
        && [ -x "$VENV/bin/pip" ] \
        && "$VENV/bin/python" -c 'import pytest, yaml' >/dev/null 2>&1
}

if venv_ready; then
    log "reusing $VENV ($("$VENV/bin/python" -V 2>&1))"
else
    if ! base_python="$(find_base_python)"; then
        log "ERROR: no Python 3.12 available in this container; PATH left unchanged"
        exit 0
    fi
    log "building $VENV on $base_python"
    rm -rf "$VENV"
    mkdir -p "$(dirname "$VENV")"
    if command -v uv >/dev/null 2>&1; then
        # --seed puts pip inside the venv too, so `pip install` targets 3.12
        # rather than falling through to the container's 3.11 /usr/bin/pip.
        uv venv --seed --python "$base_python" "$VENV" >&2
        uv pip install --python "$VENV/bin/python" --quiet "${DEPS[@]}" >&2
    else
        "$base_python" -m venv "$VENV" >&2
        "$VENV/bin/python" -m pip install --quiet --upgrade pip >&2
        "$VENV/bin/python" -m pip install --quiet "${DEPS[@]}" >&2
    fi
    if ! venv_ready; then
        log "ERROR: could not build a working 3.12 venv at $VENV; PATH left unchanged"
        exit 0
    fi
fi

# Both PyAutoMind and PyAutoBrain register this hook and a session usually has
# both checked out, so the second run must not prepend the venv twice.
if [ -n "${CLAUDE_ENV_FILE:-}" ] && ! grep -qs 'PYAUTO_SESSION_PY312=' "$CLAUDE_ENV_FILE"; then
    {
        echo "export PYAUTO_SESSION_PY312=\"$VENV\""
        echo "export VIRTUAL_ENV=\"$VENV\""
        echo "export PATH=\"$VENV/bin:\$PATH\""
    } >> "$CLAUDE_ENV_FILE"
fi

log "default python is now $("$VENV/bin/python" -V 2>&1) ($VENV/bin)"
