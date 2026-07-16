#!/usr/bin/env python3
"""PreToolUse(Bash) gate: refuse unsafe commits in the shared PyAutoMind checkout.

Motivation (docs/agent_failure_modes.md, mitigation 2 — the highest-frequency
error in the catalogue): the canonical PyAutoMind checkout is shared by every
concurrent session, and they stage into the SAME index. Four incidents in two
days (E1 + F1 x3, in both directions) came from commits that took more than
their own files: a bare ``git commit`` takes the whole index, and a
*directory* pathspec sweeps whatever a concurrent session staged under it. A
memory note about this trap, written the same morning, did not prevent three
of the four — this guard is that note, converted into a refusal.

Rule: a ``git commit`` that targets the PyAutoMind checkout must name explicit
**file** pathspecs after ``--``. Denied otherwise:

  - no ``--`` section  →  the commit takes the shared index wholesale
  - a pathspec after ``--`` resolves to a directory  →  directory pathspecs
    sweep concurrent sessions' staged work under them

Detection is textual + cheap filesystem checks; anything ambiguous is allowed
(fail-open — a guard that misfires trains bypass-by-default). Escape hatch:
``PYAUTO_SKIP_MIND_GUARD=1`` in the environment or as a prefix in the command
text (for the deliberate exceptional case, e.g. a bulk migration).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

MIND_MARKER = "PyAutoMind"


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


def _mind_root(command: str, cwd: str) -> Path | None:
    """Best-effort resolution of the PyAutoMind checkout this command targets."""
    m = re.search(r"(?:-C\s+|cd\s+)(\S*PyAutoMind)\b", command)
    if m:
        return Path(os.path.expanduser(m.group(1)))
    if cwd and MIND_MARKER in cwd:
        p = Path(cwd)
        while p.name != MIND_MARKER and p != p.parent:
            p = p.parent
        return p if p.name == MIND_MARKER else None
    return None


def check_command(command: str, cwd: str = "") -> str | None:
    """Return a denial reason, or None to allow."""
    if "PYAUTO_SKIP_MIND_GUARD=1" in command:
        return None
    if "git" not in command or "commit" not in command:
        return None
    # Only reason about commands that clearly target PyAutoMind.
    if MIND_MARKER not in command and MIND_MARKER not in (cwd or ""):
        return None
    root = _mind_root(command, cwd)

    # Examine each `git ... commit ...` clause in the (possibly compound) command.
    for clause in re.split(r"&&|\|\||;", command):
        if not re.search(r"\bgit\b.*\bcommit\b", clause):
            continue
        if "--amend" in clause or "--dry-run" in clause:
            continue
        try:
            tokens = shlex.split(clause)
        except ValueError:
            return None  # unparseable — fail open
        if "--" not in tokens:
            return (
                "PyAutoMind is a SHARED checkout: concurrent sessions stage into "
                "the same index, and a commit without explicit `-- <files>` takes "
                "all of it (this swept other sessions' work 4x in 2 days). "
                "Re-run as: git commit -m '<msg>' -- <file> [<file> ...]  "
                "(files, not directories). Deliberate exception: prefix "
                "PYAUTO_SKIP_MIND_GUARD=1."
            )
        pathspecs = tokens[tokens.index("--") + 1 :]
        if not pathspecs:
            return (
                "PyAutoMind commit has an empty `--` pathspec list — name the "
                "exact files to commit (the shared index carries other sessions' "
                "staged work)."
            )
        if root and root.is_dir():
            for spec in pathspecs:
                target = (root / spec) if not os.path.isabs(spec) else Path(spec)
                if target.is_dir():
                    return (
                        f"PyAutoMind commit pathspec '{spec}' is a DIRECTORY — "
                        "directory pathspecs sweep whatever concurrent sessions "
                        "staged under them (this exact shape hit twice on "
                        "2026-07-16). List the individual files. Deliberate "
                        "exception: prefix PYAUTO_SKIP_MIND_GUARD=1."
                    )
    return None


def main() -> None:
    raw = sys.stdin.read()
    if os.environ.get("PYAUTO_SKIP_MIND_GUARD") == "1":
        _allow()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        _allow()
    if payload.get("tool_name") != "Bash":
        _allow()
    command = (payload.get("tool_input") or {}).get("command") or ""
    cwd = payload.get("cwd") or ""
    try:
        reason = check_command(command, cwd)
    except Exception:
        _allow()  # the guard must never block on its own bugs
    if reason:
        _deny(reason)
    _allow()


if __name__ == "__main__":
    main()
