#!/usr/bin/env python3
"""agents/_pyauto_root.py — the single answer to "where is the workspace root?".

The Python half of `bin/_pyauto_root.sh`; the two must agree, because a shell
agent and the Python it shells out to have to resolve the same tree. Keep the
order below identical to the shell file's.

The workspace root is the directory holding the organ checkouts side by side
(PyAutoBrain/, PyAutoMind/, PyAutoHeart/, ...). It is *derived*, never named:

1. an explicit ``PYAUTO_ROOT`` in the environment — the operator's word, taken
   verbatim;
2. the parent of this checkout, when that parent holds at least one sibling
   organ. It asks where the code actually *is* rather than where it is usually
   kept, so it is true on a developer box and in a remote session alike;
3. the parent of this checkout regardless — the best available guess, reported
   as unverified so a caller can say "I looked here and it was not a
   workspace" instead of silently finding nothing.

Consumers used to default to a hardcoded developer-box path instead of step 2.
On that box it was right; in a remote session ``$HOME`` is ``/root`` while the
checkouts are under ``/home/user``, so every consumer resolved into a directory
that does not exist. Nothing raised — these consumers all degrade — so they
reported empty. That is the failure mode this module exists to remove, and
naming any absolute workspace path here would reintroduce it for the next
environment that does not match.

Stdlib only.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "pyauto_root",
    "pyauto_wt_root",
    "workspace_root_reason",
    "SIBLING_ORGANS",
]

# Any one of these beside a directory marks it as a workspace root. PyAutoMind
# is the strongest signal (it carries repos.yaml, the body map most consumers
# want) but a Brain-only remote session is still a legitimate root.
SIBLING_ORGANS = (
    "PyAutoMind",
    "PyAutoHeart",
    "PyAutoHands",
    "PyAutoMemory",
    "PyAutoGut",
    "PyAutoNerves",
)

_BRAIN_HOME = Path(__file__).resolve().parents[1]


def _is_root(path: Path) -> bool:
    """True when `path` holds at least one sibling organ checkout."""
    return any((path / organ).is_dir() for organ in SIBLING_ORGANS)


def pyauto_root() -> Path:
    """The workspace root, by the order documented above."""
    return Path(workspace_root_reason()[0])


def workspace_root_reason() -> tuple[Path, str]:
    """(root, why) — the root and the rule that produced it.

    Callers that degrade when the root is wrong should report the reason: the
    whole point of this module is that "resolved to a directory that does not
    exist" stops being indistinguishable from "resolved fine, found nothing".
    """
    env = os.environ.get("PYAUTO_ROOT")
    if env:
        return Path(env), "PYAUTO_ROOT"
    parent = _BRAIN_HOME.parent
    if _is_root(parent):
        return parent, "beside this checkout"
    # No sibling organ next to us. Still the best guess available — but say so,
    # so a degraded caller can report "looked in X, not a workspace" rather
    # than an empty result that reads like "nothing to do".
    return parent, "unverified (no sibling organ beside this checkout)"


def pyauto_wt_root() -> Path:
    """Where task worktrees live: beside the workspace root, suffixed ``-wt``.

    Derived from the resolved root rather than from ``$HOME`` for the same
    reason the root itself is — an environment whose checkouts are not under
    ``~/Code`` has its worktrees elsewhere too.
    """
    env = os.environ.get("PYAUTO_WT_ROOT")
    if env:
        return Path(env)
    root = pyauto_root()
    return root.parent / f"{root.name}-wt"
