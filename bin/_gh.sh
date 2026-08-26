#!/usr/bin/env bash
# bin/_gh.sh — one honest answer to "is there a gh here?".
#
# These scripts were written on a developer box, where `gh` is installed and
# authenticated. A Claude Code remote session has no `gh` at all — its GitHub
# access is the GitHub MCP tool surface, which a shell script cannot call. So a
# script that shells out to `gh` in such a session does not misbehave subtly; it
# simply cannot run.
#
# What it used to do was worse than failing: `gh` not found means the command
# substitution is empty, and a caller that reads that as "no open PRs" or "no
# runs" proceeds on an answer it never got. `pyauto-brain board` reported "no
# runs" for seven workflows on a machine that had never been able to ask.
#
# So: say so, once, in the caller's own voice, and point at the page that
# explains the alternative.
#
# Source it via `dirname` rather than `readlink`: some of these scripts are
# exercised with a deliberately lean PATH (see
# tests/test_branch_sweep.py::_gh_free_path, which links in only the tools the
# script actually calls), and a helper that needs an absent command to locate
# itself fails before it can explain anything.
#
#   . "$(dirname "${BASH_SOURCE[0]}")/_gh.sh"
#   require_gh || exit $?      # hard requirement: stop here
#   have_gh || skip_this_leg   # optional: degrade, but say the reason

if [ -z "${_PYAUTO_GH_SOURCED:-}" ]; then
_PYAUTO_GH_SOURCED=1

# True when `gh` is present AND authenticated. Both matter: an unauthenticated
# gh fails per-call, which reads like a network flake rather than a setup gap.
have_gh() {
    command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1
}

# Print why this cannot run here, and where the alternative is documented.
gh_unavailable_reason() {
    if ! command -v gh >/dev/null 2>&1; then
        printf 'the GitHub CLI (gh) is not installed in this environment'
    else
        printf 'the GitHub CLI (gh) is installed but not authenticated'
    fi
}

# Hard requirement. Returns 127 (command-not-found) so a caller's `|| exit $?`
# carries a meaningful status rather than a generic 1.
require_gh() {
    have_gh && return 0
    local who="${1:-$(basename "${0:-this script}")}"
    {
        echo "$who: $(gh_unavailable_reason)."
        echo "  A Claude Code remote session reaches GitHub through the GitHub MCP"
        echo "  tools instead, which a shell script cannot call — so run this leg"
        echo "  from an environment with gh, or perform it through MCP."
        echo "  Mapping: PyAutoBrain/skills/GITHUB_ACCESS.md"
    } >&2
    return 127
}

fi
