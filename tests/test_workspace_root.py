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

The second half pins the mirror-image failure. The sibling-organ probe asks
only "does this directory hold an organ?", so a family directory such as
`organs/` satisfies it the moment the organs move into one, and the root
resolves ONE LEVEL TOO DEEP — where every `root / <repo>` join misses and,
again, nothing raises. A `.pyauto-root` marker file walked up to from the
checkout answers it instead. The probe is kept as a fallback, not replaced: a
remote session clones one repo with no workspace root above it to mark, so
`test_flat_workspace_without_a_marker_*` is the proof that this change can
only ADD correctness.
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
        # The value is used whether or not a marker confirms it; only the
        # reason says which (see the env-override test below).
        assert _pyauto_root.workspace_root_reason()[1].startswith("PYAUTO_ROOT")
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
        # A developer box marks its root; CI checks three repos out side by
        # side with no marker and resolves by the sibling probe. Both are
        # correct, and both must name the same directory.
        if (BRAIN_HOME.parent / _pyauto_root.ROOT_MARKER).is_file():
            assert reason == f"{_pyauto_root.ROOT_MARKER} marker"
        else:
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


# ---------------------------------------------------------------------------
# The marker walk: fake workspaces in tmp_path
#
# Each fixture is a real tree with a real copy of both resolvers in it —
# copies, not symlinks, because both resolvers deliberately follow symlinks
# (`Path.resolve()`, `readlink -f`) to find the checkout they live in, and a
# symlinked fixture would resolve back to this repo.
# ---------------------------------------------------------------------------

MARKER = _pyauto_root.ROOT_MARKER


def _fake_workspace(tmp_path, brain="PyAutoBrain", also=(), marker=True):
    """Build a workspace under tmp_path; return (root, brain checkout).

    `brain` is where the Brain checkout sits relative to the root ("PyAutoBrain"
    for a flat layout, "organs/PyAutoBrain" for a grouped one) and `also` are
    further directories to create, organ or library checkouts alike.
    """
    root = tmp_path.resolve()
    brain_home = root / brain
    (brain_home / "agents").mkdir(parents=True)
    (brain_home / "bin").mkdir(parents=True)
    (brain_home / "agents" / "_pyauto_root.py").write_text(
        PY_RESOLVER.read_text(encoding="utf-8"), encoding="utf-8"
    )
    shell = brain_home / "bin" / "_pyauto_root.sh"
    shell.write_text(SHELL_RESOLVER.read_text(encoding="utf-8"), encoding="utf-8")
    for extra in also:
        (root / extra).mkdir(parents=True, exist_ok=True)
    if marker:
        (root / MARKER).write_text("# fixture workspace root\n", encoding="utf-8")
    return root, brain_home


def _clean_env(env_overrides=None):
    env = dict(os.environ)
    env.pop("PYAUTO_ROOT", None)
    env.pop("PYAUTO_WT_ROOT", None)
    env.update(env_overrides or {})
    return env


def _python_resolved(brain_home, env_overrides=None):
    """(root, reason) as the copied Python resolver in `brain_home` sees it."""
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        " import _pyauto_root as r;"
        " root, why = r.workspace_root_reason();"
        " print(root); print(why)"
    )
    r = subprocess.run(
        [sys.executable, "-c", code, str(brain_home / "agents")],
        capture_output=True, text=True, env=_clean_env(env_overrides), timeout=30,
    )
    assert r.returncode == 0, r.stderr
    root, reason = r.stdout.splitlines()
    return Path(root), reason


def _shell_resolved(brain_home, env_overrides=None):
    """(root, reason) as the copied shell resolver in `brain_home` sees it."""
    script = (
        f'. "{brain_home / "bin" / "_pyauto_root.sh"}";'
        ' printf "%s\\n%s\\n" "$PYAUTO_ROOT" "$PYAUTO_ROOT_REASON"'
    )
    r = subprocess.run(
        ["bash", "-c", script],
        capture_output=True, text=True, env=_clean_env(env_overrides), timeout=30,
    )
    assert r.returncode == 0, r.stderr
    root, reason = r.stdout.splitlines()
    return Path(root), reason


def _both_resolvers_say(brain_home, env_overrides=None):
    """(root, reason), asserted identical in Python and shell.

    The module's stated invariant: "the two must agree, because a shell agent
    and the Python it shells out to have to resolve the same tree".
    """
    py = _python_resolved(brain_home, env_overrides)
    sh = _shell_resolved(brain_home, env_overrides)
    assert py == sh, f"python said {py}, shell said {sh}"
    return py


def test_marker_wins_in_a_nested_workspace(tmp_path):
    """Checkouts grouped into subdirectories; the marked root is still the root.

    The grouping is what is under test, not which repos do it, so the checkouts
    are fictional: one library family beside a directory of organs.
    """
    root, brain = _fake_workspace(
        tmp_path, also=("family/LibOne", "family/LibTwo", "organs/OrganOne")
    )
    assert _both_resolvers_say(brain) == (root, f"{MARKER} marker")


def test_marker_wins_from_inside_a_family_directory(tmp_path):
    """The Brain itself grouped under organs/ — the root is still one level up."""
    root, brain = _fake_workspace(
        tmp_path, brain="organs/PyAutoBrain", also=("organs/PyAutoMind",)
    )
    assert _both_resolvers_say(brain) == (root, f"{MARKER} marker")


def test_the_organs_family_directory_is_what_the_old_rule_got_wrong(tmp_path):
    """The defect, pinned: the sibling probe alone answers `organs/`.

    `_is_root("<root>/organs")` is true — it holds PyAutoMind — so the
    pre-marker order returned the family directory, one level too deep, and
    every `root / <repo>` join below it missed silently. Removing the marker
    from the fixture reproduces exactly that; the marker is what fixes it.
    """
    root, brain = _fake_workspace(
        tmp_path, brain="organs/PyAutoBrain", also=("organs/PyAutoMind",),
        marker=False,
    )
    assert _pyauto_root._is_root(root / "organs")
    assert _both_resolvers_say(brain) == (root / "organs", "beside this checkout")

    # ...and with the marker written, the same tree resolves to the real root.
    (root / MARKER).write_text("# fixture workspace root\n", encoding="utf-8")
    assert _both_resolvers_say(brain) == (root, f"{MARKER} marker")


def test_flat_workspace_without_a_marker_still_resolves(tmp_path):
    """The remote-session case: one clone layer, no root above it to mark.

    This is the regression guard for the whole change. The sibling probe is
    demoted, never removed, so a workspace that resolved correctly before must
    still resolve correctly — and by the same reason string.
    """
    root, brain = _fake_workspace(tmp_path, also=("PyAutoMind",), marker=False)
    assert _both_resolvers_say(brain) == (root, "beside this checkout")


def test_lone_checkout_without_marker_or_sibling_is_reported_unverified(tmp_path):
    """Nothing to go on: the parent anyway, and said so."""
    root, brain = _fake_workspace(tmp_path, marker=False)
    assert _both_resolvers_say(brain) == (
        root, "unverified (no sibling organ beside this checkout)"
    )


def test_env_override_is_honoured_and_the_marker_only_changes_the_reason(tmp_path):
    """The operator's word stands; whether it is confirmed is visible."""
    root, brain = _fake_workspace(tmp_path, also=("PyAutoMind",))
    elsewhere = tmp_path.resolve() / "elsewhere"
    elsewhere.mkdir()

    # Unconfirmed: still used — a hook exporting a wrong value is not
    # overridden, only reported.
    assert _both_resolvers_say(brain, {"PYAUTO_ROOT": str(elsewhere)}) == (
        elsewhere, f"PYAUTO_ROOT (unverified - no {MARKER} marker)"
    )

    # Confirmed by a marker of its own.
    (elsewhere / MARKER).write_text("# fixture workspace root\n", encoding="utf-8")
    assert _both_resolvers_say(brain, {"PYAUTO_ROOT": str(elsewhere)}) == (
        elsewhere, "PYAUTO_ROOT"
    )

    # Either way it beats the marker this checkout actually sits under.
    assert elsewhere != root
