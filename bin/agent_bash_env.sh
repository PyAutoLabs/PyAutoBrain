# agent_bash_env.sh — sourced via BASH_ENV by every non-interactive bash the
# agent harness spawns (wired in the workspace .claude/settings.json `env`).
#
# docs/agent_failure_modes.md mitigation 1: `cmd | head; $?` read the pager's
# exit status three times in one campaign day — make the INSTRUMENT loud
# instead of the agent careful. pipefail applies ONLY to `bash -c` invocations
# (the agent's top-level tool commands); script files keep their authored
# semantics — organism scripts were written against default pipeline
# behaviour and must not change under this file.
#
# Discriminator: BASH_EXECUTION_STRING is set only for `bash -c`. ($0 cannot
# be used here — inside BASH_ENV it reads "bash" even for script invocations;
# measured before shipping, which is this file's own moral.)
if [ -n "${BASH_EXECUTION_STRING:-}" ]; then
    set -o pipefail
fi
