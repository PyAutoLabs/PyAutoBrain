"""Task bundles keep flat repo names when canonical checkouts are grouped."""

import os
import subprocess
from pathlib import Path


WORKTREE_SH = Path(__file__).resolve().parents[1] / "bin/worktree.sh"


def _git(*args):
    subprocess.run(["git", *map(str, args)], check=True, capture_output=True)


def test_create_and_remove_from_grouped_checkout(tmp_path):
    main = tmp_path / "main"
    mind = main / "PyAutoMind"
    mind.mkdir(parents=True)
    (mind / "repos.yaml").write_text("repos:\n  Demo:\n    path: science/Demo\n")
    demo = main / "science" / "Demo"
    demo.mkdir(parents=True)
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

    bundle = tmp_path / "bundles" / "task"
    env = os.environ | {
        "PYAUTO_MAIN": str(main),
        "PYAUTO_WT_ROOT": str(bundle.parent),
        "PYAUTO_WT_FORCE": "1",
    }
    result = subprocess.run(
        ["bash", "-c", f'source "{WORKTREE_SH}"; worktree_create task Demo'],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (bundle / "Demo" / ".git").is_file()
    assert (bundle / "PyAutoMind").is_symlink()
    assert not (bundle / "science").exists()
    lookup = subprocess.run(
        ["python3", str(WORKTREE_SH.parents[1] / "agents" / "_repo_paths.py"),
         "path", "Demo", "--root", str(bundle), "--required"],
        capture_output=True, text=True,
    )
    assert lookup.returncode == 0, lookup.stderr
    assert lookup.stdout.strip() == str(bundle / "Demo")

    result = subprocess.run(
        ["bash", "-c", f'source "{WORKTREE_SH}"; worktree_remove task'],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not bundle.exists()
