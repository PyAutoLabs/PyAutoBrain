"""worktree_create never writes through a symlinked activate.sh (#469).

The sibling-symlink loop used to link the workspace root's activate.sh into
the bundle, and the bundle's activate.sh was then written THROUGH that link,
clobbering the unversioned root file and retargeting every earlier bundle.
Hermetic: everything lives under tmp_path; the real workspace is never read
or written.
"""

import os
import subprocess
from pathlib import Path

import pytest


WORKTREE_SH = Path(__file__).resolve().parents[1] / "bin/worktree.sh"
ROOT_ACTIVATE = b"# fabricated root activate.sh - must never change\nexport FAKE_ROOT=1\n"


def _git(*args):
    subprocess.run(["git", *map(str, args)], check=True, capture_output=True)


@pytest.fixture
def workspace(tmp_path):
    main = tmp_path / "main"
    mind = main / "PyAutoMind"
    mind.mkdir(parents=True)
    (mind / "repos.yaml").write_text("repos:\n  Demo:\n    path: Demo\n")
    (main / "activate.sh").write_bytes(ROOT_ACTIVATE)
    demo = main / "Demo"
    demo.mkdir()
    remote = tmp_path / "remote.git"
    _git("init", "--bare", remote)
    _git("init", "-b", "main", demo)
    _git("-C", demo, "config", "user.email", "test@example.com")
    _git("-C", demo, "config", "user.name", "Test")
    (demo / "README.md").write_text("demo\n")
    _git("-C", demo, "add", "README.md")
    _git("-C", demo, "commit", "-m", "initial")
    _git("-C", demo, "remote", "add", "origin", remote)
    _git("-C", demo, "push", "-u", "origin", "main")

    bundles = tmp_path / "bundles"
    env = os.environ | {
        "PYAUTO_MAIN": str(main),
        "PYAUTO_WT_ROOT": str(bundles),
        "PYAUTO_WT_FORCE": "1",
    }
    return main, bundles, env


def _run(env, cmd):
    result = subprocess.run(
        ["bash", "-c", f'source "{WORKTREE_SH}"; {cmd}'],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return result


def _assert_own_activate(bundle, task):
    activate = bundle / "activate.sh"
    assert not activate.is_symlink()
    assert activate.is_file()
    text = activate.read_text()
    assert f'export PYAUTO_TASK="{task}"' in text
    # The bundle's own library paths are on its PYTHONPATH. PyAutoNerves (an
    # organ, first in PYAUTO_LIBS) stands in for the library list: satellite
    # repo names in organ code trip the tenant firewall
    # (PyAutoMind/scripts/repos_sync.py).
    assert f'export PYAUTO_ROOT="{bundle}"' in text
    assert f'export PYTHONPATH="{bundle}/PyAutoNerves:' in text


def test_create_leaves_root_activate_untouched(workspace, tmp_path):
    main, bundles, env = workspace
    _run(env, "worktree_create task Demo")
    bundle = bundles / "task"
    assert tmp_path in bundle.parents
    assert (main / "activate.sh").read_bytes() == ROOT_ACTIVATE
    _assert_own_activate(bundle, "task")
    assert (bundle / ".pyauto-root").is_file()
    assert not (bundle / ".pyauto-root").is_symlink()


def test_second_bundle_does_not_retarget_first(workspace):
    main, bundles, env = workspace
    _run(env, "worktree_create first Demo")
    _run(env, "worktree_create second Demo")
    assert (main / "activate.sh").read_bytes() == ROOT_ACTIVATE
    _assert_own_activate(bundles / "first", "first")
    _assert_own_activate(bundles / "second", "second")


def test_repair_converts_symlinked_bundle_activate(workspace):
    main, bundles, env = workspace
    _run(env, "worktree_create task Demo")
    bundle = bundles / "task"
    # Recreate the pre-fix damage: the bundle's activate.sh is a link to root.
    (bundle / "activate.sh").unlink()
    (bundle / "activate.sh").symlink_to(main / "activate.sh")

    _run(env, "worktree_repair_activate task")

    assert (main / "activate.sh").read_bytes() == ROOT_ACTIVATE
    _assert_own_activate(bundle, "task")


def test_repair_defaults_to_every_bundle(workspace):
    main, bundles, env = workspace
    _run(env, "worktree_create one Demo")
    _run(env, "worktree_create two Demo")
    for task in ("one", "two"):
        (bundles / task / "activate.sh").unlink()
        (bundles / task / "activate.sh").symlink_to(main / "activate.sh")

    _run(env, "worktree_repair_activate")

    assert (main / "activate.sh").read_bytes() == ROOT_ACTIVATE
    _assert_own_activate(bundles / "one", "one")
    _assert_own_activate(bundles / "two", "two")
