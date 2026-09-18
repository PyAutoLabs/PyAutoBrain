#!/usr/bin/env bash
# bin/_pyauto_root.sh — the single answer to "where is the workspace root?".
#
# The workspace root is the directory holding the organ checkouts side by side
# (PyAutoBrain/, PyAutoMind/, PyAutoHeart/, ...). Three layouts have to work:
#
#   a developer box           organs cloned side by side under one directory
#   a remote session          each in-scope repo cloned directly under the
#                             session's working directory (web/mobile)
#   anywhere else             a worktree, a CI checkout, a spawned template
#
# Consumers used to default to a hardcoded developer-box path. On that box it
# was right; in a remote session $HOME is /root while the checkouts are under
# /home/user, so every consumer resolved into a directory that does not exist.
# Nothing crashed, because the consumers are written to degrade — they just
# reported empty. `pyauto-brain board` printed a plausible board with hollow
# sections at exit 0, and the community leg said "body map not found" for a
# file that was present all along, one directory up from the script reading it.
#
# So: derive the root from where THIS checkout actually is, and name no
# absolute path at all — a literal here would only be right for the machine it
# was written on. `bin/pyauto-brain` and `board/_board.py` already resolved it
# this way (BRAIN_HOME.parent); this file makes that the one convention instead
# of the majority one.
#
# The order, identical to agents/_pyauto_root.py's:
#
#   1. an explicit PYAUTO_ROOT — the operator's word, taken verbatim, but
#      reported as verified or not so a wrong value from a hook is visible;
#   2. the nearest ancestor holding a .pyauto-root marker file — the only rule
#      that survives the workspace growing subdirectories, because "does this
#      directory hold an organ?" is answered yes by a family directory such as
#      organs/ the moment the organs move into one;
#   3. the parent of this checkout when it holds a sibling organ — still true
#      for a single-repo remote checkout, which has no root above it to mark;
#   4. the parent regardless, reported as unverified.
#
# Usage (from anywhere in this repo):
#     . "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../bin/_pyauto_root.sh"
# then read $PYAUTO_ROOT, and $PYAUTO_ROOT_REASON when reporting a degraded
# result. An explicit PYAUTO_ROOT in the environment always wins, so a caller
# can still point the tooling at another workspace.

# Guard against re-sourcing: several agents source both _common.sh and a bin
# helper that each pull this in.
if [ -z "${_PYAUTO_ROOT_SOURCED:-}" ]; then
_PYAUTO_ROOT_SOURCED=1

# The parent of this PyAutoBrain checkout. Resolved through readlink so an
# agent invoked via a symlinked bin/ still lands on the real tree.
_pyauto_brain_home() {
    cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd
}

# A workspace root says so itself by holding this file. It is deliberately
# unversioned — the root is not a git repo — so it marks a checkout layout on
# one machine, not a fact about the organism.
PYAUTO_ROOT_MARKER=".pyauto-root"
export PYAUTO_ROOT_MARKER

# The nearest ANCESTOR of $1 holding the marker, printed; non-zero when there
# is none. A checkout is never its own workspace root, so the walk starts one
# level up — the layout-independent walk the workspace already uses elsewhere
# to find a project root.
_pyauto_marked_root() {
    _pyauto_d=$(dirname "$1")
    while [ "$_pyauto_d" != "/" ]; do
        if [ -f "$_pyauto_d/$PYAUTO_ROOT_MARKER" ]; then
            printf '%s' "$_pyauto_d"
            return 0
        fi
        _pyauto_d=$(dirname "$_pyauto_d")
    done
    if [ -f "/$PYAUTO_ROOT_MARKER" ]; then
        printf '%s' "/"
        return 0
    fi
    return 1
}

# A directory counts as a workspace root if it holds at least one sibling organ
# besides this one. The Mind is the strongest signal (it carries repos.yaml,
# the body map every consumer wants), but a Brain-only remote session is still
# a legitimate root, so accept any organ sibling.
_pyauto_is_root() {
    [ -d "$1/PyAutoMind" ] || [ -d "$1/PyAutoHeart" ] || [ -d "$1/PyAutoHands" ] \
        || [ -d "$1/PyAutoMemory" ] || [ -d "$1/PyAutoGut" ] || [ -d "$1/PyAutoNerves" ] \
        || [ -d "$1/PyAutoCortex" ]
}

# Assigns PYAUTO_ROOT and PYAUTO_ROOT_REASON rather than printing: one
# decision produces two answers, and a command substitution would drop the
# reason. Called directly, so it runs in this shell, not a subshell.
_pyauto_resolve_root() {
    # 1. An explicit override is the operator's word; never second-guess it.
    #    The marker only decides how the reason reads.
    if [ -n "${PYAUTO_ROOT:-}" ]; then
        if [ -f "$PYAUTO_ROOT/$PYAUTO_ROOT_MARKER" ]; then
            PYAUTO_ROOT_REASON="PYAUTO_ROOT"
        else
            PYAUTO_ROOT_REASON="PYAUTO_ROOT (unverified - no $PYAUTO_ROOT_MARKER marker)"
        fi
        return 0
    fi
    _pyauto_home="$(_pyauto_brain_home)"
    # 2. A marked ancestor — the root naming itself, which stays right however
    #    deep under it this checkout sits.
    if _pyauto_marked="$(_pyauto_marked_root "$_pyauto_home")"; then
        PYAUTO_ROOT="$_pyauto_marked"
        PYAUTO_ROOT_REASON="$PYAUTO_ROOT_MARKER marker"
        return 0
    fi
    # 3. Beside this checkout — no marker anywhere above us, so what sits
    #    beside us is all there is: a single-repo remote session, a CI matrix,
    #    a spawned template. 4. Failing that, the parent anyway: the best guess
    #    available, and a real path the caller can name in a diagnostic.
    PYAUTO_ROOT="$(dirname "$_pyauto_home")"
    if _pyauto_is_root "$PYAUTO_ROOT"; then
        PYAUTO_ROOT_REASON="beside this checkout"
    else
        PYAUTO_ROOT_REASON="unverified (no sibling organ beside this checkout)"
    fi
}

_pyauto_resolve_root
export PYAUTO_ROOT
export PYAUTO_ROOT_REASON

# Task worktrees live beside the workspace root, not inside it, so they derive
# from whatever the root resolved to rather than re-deriving from $HOME.
PYAUTO_WT_ROOT="${PYAUTO_WT_ROOT:-${PYAUTO_ROOT}-wt}"
export PYAUTO_WT_ROOT

fi
