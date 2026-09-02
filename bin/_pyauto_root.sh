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
# Usage (from anywhere in this repo):
#     . "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../bin/_pyauto_root.sh"
# then read $PYAUTO_ROOT. An explicit PYAUTO_ROOT in the environment always
# wins, so a caller can still point the tooling at another workspace.

# Guard against re-sourcing: several agents source both _common.sh and a bin
# helper that each pull this in.
if [ -z "${_PYAUTO_ROOT_SOURCED:-}" ]; then
_PYAUTO_ROOT_SOURCED=1

# The parent of this PyAutoBrain checkout. Resolved through readlink so an
# agent invoked via a symlinked bin/ still lands on the real tree.
_pyauto_brain_home() {
    cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd
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

_pyauto_resolve_root() {
    # 1. An explicit override is the operator's word; never second-guess it.
    if [ -n "${PYAUTO_ROOT:-}" ]; then
        printf '%s' "$PYAUTO_ROOT"
        return 0
    fi
    # 2. Beside this checkout — the layout that is true in every environment
    #    the organism actually runs in, remote sessions included. 3. Failing
    #    that, the parent anyway: the best guess available, and a real path the
    #    caller can name in a diagnostic.
    printf '%s' "$(dirname "$(_pyauto_brain_home)")"
}

PYAUTO_ROOT="$(_pyauto_resolve_root)"
export PYAUTO_ROOT

# Task worktrees live beside the workspace root, not inside it, so they derive
# from whatever the root resolved to rather than re-deriving from $HOME.
PYAUTO_WT_ROOT="${PYAUTO_WT_ROOT:-${PYAUTO_ROOT}-wt}"
export PYAUTO_WT_ROOT

fi
