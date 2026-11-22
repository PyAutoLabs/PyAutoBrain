"""Task bundles keep flat repo names when canonical checkouts are grouped."""

import os
import subprocess

from _helpers import WORKTREE_SH, init_repo, source_worktree


def test_create_and_remove_from_grouped_checkout(tmp_path):
    main = tmp_path / "main"
    mind = main / "PyAutoMind"
    mind.mkdir(parents=True)
    (mind / "repos.yaml").write_text("repos:\n  Demo:\n    path: science/Demo\n")
    init_repo(main / "science" / "Demo", remote=tmp_path / "remote.git")

    bundle = tmp_path / "bundles" / "task"
    env = os.environ | {
        "PYAUTO_MAIN": str(main),
        "PYAUTO_WT_ROOT": str(bundle.parent),
        "PYAUTO_WT_FORCE": "1",
    }
    result = source_worktree("worktree_create task Demo", env)
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

    result = source_worktree("worktree_remove task", env)
    assert result.returncode == 0, result.stderr
    assert not bundle.exists()
