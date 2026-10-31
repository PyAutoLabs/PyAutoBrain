#!/usr/bin/env python3
"""PreToolUse(Bash) gate: no raw scheduler mutations outside a project's `hpc/sync`.

Motivation (hpc-campaign phase 5c, ruling F12): an agent that types
``ssh ral "scancel 413011"`` or ``sbatch --array=0-99 job.sh`` changes a shared
cluster queue with no record of who asked, why, or what came of it — and one
CPU array on the wrong partition has already idled all eight RAL A100s
(2026-09-30). A project's own ``hpc/sync`` is the one place the queue is
changed, and it writes the record:

  - ``hpc/sync act <submit|resubmit|hold|release|throttle|update-pending|cancel>
    <campaign> …`` is the only way a campaign's jobs start or change, a pilot
    included (the legacy ``hpc/sync cancel <job>`` is ``act cancel``);
  - ``hpc/sync submit|push-submit`` sbatch one hand-written script, outside
    any campaign;
  - every ``act`` checks it can write, then appends, one JSON line ``{utc,
    user, campaign, action, args, exit}`` to
    ``<project_root>/campaign/<name>/actions.log`` on the cluster.

The allowlist and the audit-log contract are stated in ``AUTONOMY.md``
("Scheduler actions"); this guard is that rule converted into a refusal.

Rule: a Bash command that runs ``sbatch``, ``scancel``, a mutating
``scontrol`` (anything but ``show``/``ping``/``version``/``help``) or a raw
``python -m autofit.campaign submit`` (not ``--dry-run``) is denied —
directly, over ``ssh``, inside ``bash -c``/``eval``, behind env assignments or
wrappers (``env``, ``sudo``, ``nohup``, ``timeout``, ``xargs`` …), chained with
``;``/``&&``/``||``/``|``, in a ``$(…)``/backtick substitution, or in a
heredoc fed to ``ssh``/a shell. Read-only scheduler commands (``squeue``,
``sacct``, ``sinfo``, ``scontrol show job …``) are free — the Cortex reads
``gres/gpu`` from ``scontrol show job``. An ``hpc/sync`` invocation is never
denied: the scheduler words it runs live inside the script, not in the command.

Only a command word is judged — a quoted commit message or ``grep sbatch`` that
merely *mentions* one is not a call. The guard is textual: it cannot see a
scheduler call made from inside a script or a Python ``subprocess`` — the
allowlist doctrine covers those. Malformed payloads and unparseable shell are
allowed (fail-open — a guard that misfires trains bypass-by-default,
``docs/agent_failure_modes.md`` §4). Human-directed exception:
``PYAUTO_SKIP_SCHEDULER_GUARD=1`` in the environment or the command text.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

MUTATING = frozenset({"sbatch", "scancel"})
#: `scontrol` subcommands that only read. Everything else (hold, release,
#: update, requeue, suspend, top, reconfigure …) changes the cluster.
SCONTROL_READ_ONLY = frozenset({"show", "ping", "version", "help", "listpids", "-h", "--help", "-V", "--version"})

#: Words that run the next word as the command: skipped to reach it.
_PREFIXES = frozenset(
    {"nohup", "time", "command", "exec", "builtin", "!", "{", "}",
     "if", "then", "else", "elif", "do", "while", "until"}
)
#: Wrappers whose options precede the command: `(short options that take a
#: value, positionals before the command)` — `timeout 60 sbatch`, `xargs -n 1 scancel`.
_OPTION_WRAPPERS = {
    "env": ("uCS", 0),
    "sudo": ("ugCDhpRrTU", 0),
    "nice": ("n", 0),
    "stdbuf": ("ioe", 0),
    "timeout": ("sk", 1),
    "xargs": ("aEdIiLlnPs", 0),
    "watch": ("dn", 0),
}
_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
#: ssh options that take a value (OpenSSH).
_SSH_VALUE_OPTS = "BbcDEeFIiJLlmOoPpQRSWw"
#: scontrol options that take a value (`-M <clusters>`).
_SCONTROL_VALUE_OPTS = frozenset({"-M", "--clusters"})
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_SEPARATORS = ";&|\n()`"
#: Cheap pre-filter: nothing to judge unless a scheduler word appears at all.
_TRIGGER = re.compile(r"\b(sbatch|scancel|scontrol|autofit\.campaign)\b")
_PYTHON = re.compile(r"^python[0-9.]*$")

DENY_REASON = (
    "Raw `{word}` changes the shared cluster queue with no record. A "
    "campaign's jobs start and change only through the project's "
    "`hpc/sync act <submit|resubmit|hold|release|throttle|update-pending|cancel> "
    "<campaign> ...`, which logs each action to "
    "<project_root>/campaign/<name>/actions.log (AUTONOMY.md, \"Scheduler "
    "actions\"); one hand-written script outside any campaign goes through "
    "`hpc/sync submit|push-submit`. Reading is free: squeue, sacct, sinfo, "
    "`scontrol show`, `hpc/sync status|plan|pilot`. "
    "Human-directed exception: prefix PYAUTO_SKIP_SCHEDULER_GUARD=1."
)


def _allow() -> None:
    sys.exit(0)


def _deny(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def _strip_heredocs(command: str) -> tuple[str, list[str]]:
    """``(command without heredoc bodies, bodies a shell will run)``.

    A heredoc body is text, not shell — unless it is fed to ``ssh`` or a shell,
    in which case every line of it is a command. Writing a job script that
    contains ``sbatch`` (``cat <<EOF > chain.sh``) is not a scheduler call;
    ``ssh ral <<EOF … scancel … EOF`` is.
    """
    kept: list[str] = []
    executed: list[str] = []
    lines = command.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        m = _HEREDOC.search(line)
        if not m:
            continue
        # Fed to a shell anywhere on the line: `ssh ral bash -s <<EOF`, and
        # `cat <<EOF | ssh ral` alike.
        runs_body = any(os.path.basename(w) in _SHELLS | {"ssh"} for w in line.split())
        body: list[str] = []
        while i < len(lines) and lines[i].strip() != m.group(2):
            body.append(lines[i])
            i += 1
        i += 1  # the terminator
        if runs_body:
            executed.append("\n".join(body))
    return "\n".join(kept), executed


def _clauses(command: str):
    """Token-level clause split that respects quoting; newlines, ``(``/``)`` and
    backticks separate clauses too, so a substitution's command is a clause.
    Raises ValueError on shell shlex cannot read."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=_SEPARATORS)
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    clause: list[str] = []
    for tok in lex:
        if tok and set(tok) <= set(_SEPARATORS):
            if clause:
                yield clause
            clause = []
        else:
            clause.append(tok)
    if clause:
        yield clause


def _skip_options(tokens: list[str], i: int, value_opts: str, positionals: int = 0) -> int:
    """Index of the first word after a wrapper's options and positionals."""
    while i < len(tokens) and tokens[i].startswith("-") and tokens[i] != "-":
        opt = tokens[i]
        i += 1
        if len(opt) == 2 and opt[1] in value_opts:
            i += 1  # `-p 22`, `-n 1`; `-p22` carries its value
    return min(i + positionals, len(tokens))


def _ssh_remote(tokens: list[str], i: int) -> str:
    """The remote command of ``ssh [opts] host <command …>`` (``tokens[i]`` is
    the word after ``ssh``), joined as the remote shell will read it."""
    i = _skip_options(tokens, i, _SSH_VALUE_OPTS)
    return " ".join(tokens[i + 1 :])  # past the host


def _judge_clause(tokens: list[str], depth: int) -> str | None:
    i = 0
    while i < len(tokens):
        word = tokens[i]
        base = os.path.basename(word)
        if _ASSIGNMENT.match(word) or word in _PREFIXES or word == "$":
            i += 1
        elif base in _OPTION_WRAPPERS:
            i = _skip_options(tokens, i + 1, *_OPTION_WRAPPERS[base])
            while i < len(tokens) and _ASSIGNMENT.match(tokens[i]):  # `env A=1 cmd`
                i += 1
        elif base == "ssh":
            return _judge(_ssh_remote(tokens, i + 1), depth + 1)
        elif base in _SHELLS:
            j = _skip_options(tokens, i + 1, "")
            if any("c" in t for t in tokens[i + 1 : j] if not t.startswith("--")):
                return _judge(tokens[j] if j < len(tokens) else "", depth + 1)
            return None  # `bash script.sh` — a script, not a scheduler word
        elif base == "eval":
            return _judge(" ".join(tokens[i + 1 :]), depth + 1)
        else:
            break
    if i >= len(tokens):
        return None
    base = os.path.basename(tokens[i])
    if base in MUTATING:
        return base
    if _PYTHON.match(base):
        rest = tokens[i + 1 :]
        for j in range(len(rest) - 2):
            if rest[j] == "-m" and rest[j + 1] == "autofit.campaign":
                if rest[j + 2] == "submit" and "--dry-run" not in rest:
                    return "autofit.campaign submit"
                break
        return None
    if base == "scontrol":
        sub, j = "help", i + 1  # bare `scontrol` is its interactive prompt
        while j < len(tokens):
            t = tokens[j]
            if t in _SCONTROL_VALUE_OPTS:
                j += 2
            elif t.startswith("-") and t not in SCONTROL_READ_ONLY:
                j += 1
            else:
                sub = t
                break
        return None if sub.lower() in SCONTROL_READ_ONLY else f"scontrol {sub}"
    return None


def _judge(command: str, depth: int = 0) -> str | None:
    """The first scheduler mutation ``command`` runs, or None."""
    if depth > 8 or not _TRIGGER.search(command):
        return None
    command, bodies = _strip_heredocs(command)
    for clause in _clauses(command):
        found = _judge_clause(clause, depth)
        if found:
            return found
    for body in bodies:
        found = _judge(body, depth + 1)
        if found:
            return found
    return None


def check_command(command: str) -> str | None:
    """Return a denial reason, or None to allow."""
    if "PYAUTO_SKIP_SCHEDULER_GUARD=1" in command:
        return None
    try:
        word = _judge(command)
    except ValueError:
        return None  # unbalanced quotes — bash would refuse it too; fail open
    return DENY_REASON.format(word=word) if word else None


def main() -> None:
    raw = sys.stdin.read()
    if os.environ.get("PYAUTO_SKIP_SCHEDULER_GUARD") == "1":
        _allow()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        _allow()
    if not isinstance(payload, dict):
        _allow()
    if payload.get("tool_name") != "Bash":
        _allow()
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        _allow()
    command = tool_input.get("command") or ""
    try:
        reason = check_command(command)
    except Exception:
        _allow()  # the guard must never block on its own bugs
    if reason:
        _deny(reason)
    _allow()


if __name__ == "__main__":
    main()
