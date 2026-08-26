"""The workspace root is derived, never named.

Regression cover for the mobile-performance review: `agents/_common.sh` and
five Python entrypoints each defaulted the workspace root to a hardcoded
developer-box path under `$HOME`. On that box it is right; in a remote session
`$HOME` is `/root` while the checkouts sit under `/home/user`, so every one of
them resolved into a directory that does not exist. None of them crashed — they
are all written to degrade — so `pyauto-brain board` printed a plausible board
with hollow sections at exit 0, and the community leg reported "body map not
found" for a file that was present one directory up from the script reading it.

The rule these tests pin: exactly one shell resolver and one Python resolver,
they agree, and no other source file resolves the root for itself.
"""

import os
import subprocess
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN_HOME / "agents"))

import _pyauto_root  # noqa: E402

SHELL_RESOLVER = BRAIN_HOME / "bin" / "_pyauto_root.sh"
PY_RESOLVER = BRAIN_HOME / "agents" / "_pyauto_root.py"

# Shapes that mean "this file resolved the workspace root for itself". The
# resolvers name no absolute path at all, so any $HOME-relative workspace guess
# in executable code is drift by construction.
SELF_RESOLVE_MARKERS = (
    'PYAUTO_ROOT:-$HOME/',
    'PYAUTO_MAIN:-$HOME/',
    'PYAUTO_WT_ROOT:-$HOME/',
    'os.environ.get("PYAUTO_ROOT", Path.home()',
    'os.environ.get("PYAUTO_ROOT", Path(os.path.expanduser',
    'expanduser("~/Code',
    'Path.home() / "Code"',
)


def _sourced_shell_root(env_overrides=None):
    env = dict(os.environ)
    env.pop("PYAUTO_ROOT", None)
    env.pop("PYAUTO_WT_ROOT", None)
    env.update(env_overrides or {})
    r = subprocess.run(
        ["bash", "-c", f'. "{SHELL_RESOLVER}"; printf "%s" "$PYAUTO_ROOT"'],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_shell_and_python_resolvers_agree():
    """A shell agent and the Python it shells out to must see one tree."""
    env_root = os.environ.get("PYAUTO_ROOT")
    if env_root:
        expected = env_root
    else:
        expected = str(_pyauto_root.pyauto_root())
    assert _sourced_shell_root() == expected


def test_explicit_override_wins_in_both_resolvers():
    """An operator pointing the tooling elsewhere is taken at their word."""
    assert _sourced_shell_root({"PYAUTO_ROOT": "/tmp/elsewhere"}) == "/tmp/elsewhere"
    old = os.environ.get("PYAUTO_ROOT")
    os.environ["PYAUTO_ROOT"] = "/tmp/elsewhere"
    try:
        assert _pyauto_root.pyauto_root() == Path("/tmp/elsewhere")
        assert _pyauto_root.workspace_root_reason()[1] == "PYAUTO_ROOT"
    finally:
        if old is None:
            del os.environ["PYAUTO_ROOT"]
        else:
            os.environ["PYAUTO_ROOT"] = old


def test_root_resolves_beside_this_checkout():
    """This checkout's own parent is a workspace root, and is found as one."""
    old = os.environ.pop("PYAUTO_ROOT", None)
    try:
        root, reason = _pyauto_root.workspace_root_reason()
        assert reason == "beside this checkout"
        assert root == BRAIN_HOME.parent
        # ...and the resolved root really holds a sibling organ, which is the
        # whole claim: the old default could not have said this.
        assert any((root / o).is_dir() for o in _pyauto_root.SIBLING_ORGANS)
    finally:
        if old is not None:
            os.environ["PYAUTO_ROOT"] = old


def test_no_entrypoint_resolves_the_root_for_itself():
    """Every consumer delegates; nobody re-derives the root from $HOME."""
    allowed = {SHELL_RESOLVER.resolve(), PY_RESOLVER.resolve()}
    offenders = []
    for pattern in ("bin/**/*.sh", "agents/**/*.sh", "agents/**/*.py",
                    "board/**/*.py"):
        for path in BRAIN_HOME.glob(pattern):
            if path.resolve() in allowed:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for marker in SELF_RESOLVE_MARKERS:
                if marker in text:
                    offenders.append(f"{path.relative_to(BRAIN_HOME)}: {marker}")
    assert not offenders, (
        "these resolve the workspace root themselves instead of using "
        "bin/_pyauto_root.sh / agents/_pyauto_root.py:\n  "
        + "\n  ".join(offenders)
    )


def test_worktree_root_derives_from_the_resolved_root():
    """Worktrees live beside the root, wherever the root turned out to be."""
    old = os.environ.pop("PYAUTO_WT_ROOT", None)
    try:
        root = _pyauto_root.pyauto_root()
        assert _pyauto_root.pyauto_wt_root() == root.parent / f"{root.name}-wt"
    finally:
        if old is not None:
            os.environ["PYAUTO_WT_ROOT"] = old
