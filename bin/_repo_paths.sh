#!/usr/bin/env bash
# Python owns repository identity and placement; shell consumers use this door.
_pyauto_repo_module="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../agents/_repo_paths.py"
pyauto_repo_path() {
    python3 "$_pyauto_repo_module" path "$1" --root "${2:-${PYAUTO_ROOT:-.}}"
}
pyauto_repo_list() {
    python3 "$_pyauto_repo_module" list --root "${1:-${PYAUTO_ROOT:-.}}"
}
