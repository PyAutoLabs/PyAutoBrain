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


def _clauses(command: str):
    """Token-level clause split that respects quoting (v1.1).

    v1.0 split clauses with a regex over the raw text, which cut inside
    quoted commit messages and heredoc bodies — its first live firing was a
    false positive on its own author's closeout command, minutes after
    deployment. shlex with punctuation_chars keeps `&&`/`;`/`|` as tokens
    while quoted strings (commit messages, gh comment bodies) stay single
    tokens that cannot leak trigger words or swallow the `--`.
    """
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lex.whitespace_split = True
    clause: list[str] = []
    try:
        for tok in lex:
            if tok and set(tok) <= set(";&|"):
                if clause:
                    yield clause
                clause = []
            else:
                clause.append(tok)
    except ValueError:
        return  # unparseable (heredocs, unbalanced quotes) — fail open
    if clause:
        yield clause


def _under_mind(path: Path) -> Path | None:
    """If ``path`` is inside a PyAutoMind checkout, return that checkout root;
    else None."""
    p = path
    while True:
        if p.name == MIND_MARKER:
            return p
        if p == p.parent:
            return None
        p = p.parent


def _cd_target(tokens: list[str], cur: Path | None) -> Path | None:
    """New effective cwd after a ``cd`` clause, or ``cur`` if not a plain cd.

    Honouring a leading ``cd`` is what fixes the v1.1 false positive: a command
    that ``cd``s into PyAutoHands before committing is NOT a Mind commit, even
    when the session's ambient cwd (what the hook is handed) is PyAutoMind.
    """
    if not tokens or tokens[0] != "cd":
        return cur
    args = [t for t in tokens[1:] if not t.startswith("-")]
    if not args:
        return cur  # `cd` with no path → home; unknowable, keep current
    dest = Path(os.path.expanduser(args[0]))
    if dest.is_absolute() or cur is None:
        return dest
    return cur / dest


def check_command(command: str, cwd: str = "") -> str | None:
    """Return a denial reason, or None to allow."""
    if "PYAUTO_SKIP_MIND_GUARD=1" in command:
        return None
    if "git" not in command or "commit" not in command:
        return None
    # Cheap pre-filter: a Mind commit needs PyAutoMind named in the command
    # (a `cd`/`git -C` path) or in the ambient cwd. If neither, nothing to do.
    if MIND_MARKER not in command and MIND_MARKER not in (cwd or ""):
        return None

    effective_cwd: Path | None = Path(cwd) if cwd else None

    # Walk clauses in order, tracking cwd so `cd`s before a commit are honoured.
    for tokens in _clauses(command):
        if tokens and tokens[0] == "cd":
            effective_cwd = _cd_target(tokens, effective_cwd)
            continue
        if "git" not in tokens or "commit" not in tokens:
            continue
        if tokens.index("git") > tokens.index("commit"):
            continue
        if "--amend" in tokens or "--dry-run" in tokens:
            continue
        # Which repo does THIS commit target? `git -C <path>` wins; else the
        # effective cwd. Only guard when that repo is a PyAutoMind checkout.
        target_dir = effective_cwd
        if "-C" in tokens:
            ci = tokens.index("-C")
            if ci + 1 < len(tokens):
                cpath = Path(os.path.expanduser(tokens[ci + 1]))
                target_dir = cpath if cpath.is_absolute() or effective_cwd is None else effective_cwd / cpath
        mind_root = _under_mind(target_dir) if target_dir else None
        if mind_root is None:
            continue  # not a PyAutoMind commit — e.g. a PyAutoHands worktree
        root = mind_root
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
