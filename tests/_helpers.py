"""Shared test plumbing — the pieces that were copy-pasted across test files.

Only what is genuinely the same everywhere lives here: loading a private module
by path, running git, sourcing `bin/worktree.sh`, and invoking the Brain
router. A helper that merely shares a NAME across files (`_run`, `_mind`,
`_prompt`, `_feed`) is a different function in each and stays where it is.

Names no repository and no owner (the tenant firewall reads this file too).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
BRAIN = BRAIN_HOME / "bin" / "pyauto-brain"
WORKTREE_SH = BRAIN_HOME / "bin" / "worktree.sh"


def load_module(name: str, path, *, register: bool = True):
    """Import the file at `path` (absolute, or relative to the Brain checkout)
    as the module `name` — the loader for scripts that are not on a package
    path. `register` puts it in `sys.modules` before executing it, which a
    module defining dataclasses under `from __future__ import annotations`
    needs; pass False to leave `sys.modules` untouched.
    """
    spec = importlib.util.spec_from_file_location(name, BRAIN_HOME / path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def git(*args, **kwargs):
    """`git <args>`, failing loudly; returns the completed process (text)."""
    return subprocess.run(["git", *map(str, args)], check=True,
                          capture_output=True, text=True, **kwargs)


def git_in(repo, *args, **kwargs):
    """`git -C <repo> <args>`."""
    return git("-C", repo, *args, **kwargs)


def init_repo(repo: Path, *, remote: Path | None = None, quiet_branch: str = "main") -> Path:
    """A checkout at `repo` with a test identity and one commit (`README.md`)
    on `main`; with `remote`, a bare origin at that path that `main` tracks."""
    repo.mkdir(parents=True, exist_ok=True)
    git("init", "-q", "-b", quiet_branch, repo)
    git_in(repo, "config", "user.email", "test@example.com")
    git_in(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("x\n")
    git_in(repo, "add", "README.md")
    git_in(repo, "commit", "-q", "-m", "initial")
    if remote is not None:
        git("init", "-q", "--bare", remote)
        git_in(repo, "remote", "add", "origin", remote)
        git_in(repo, "push", "-q", "-u", "origin", quiet_branch)
    return repo


def source_worktree(snippet: str, env: dict, **kwargs):
    """Source `bin/worktree.sh` and run `snippet` in that shell."""
    return subprocess.run(["bash", "-c", f'source "{WORKTREE_SH}"; {snippet}'],
                          env=env, capture_output=True, text=True, **kwargs)


def hermetic_worktree_env(tmp_path: Path, main: Path | None = None) -> dict:
    """The sealed environment the worktree guards run under: nothing of the
    caller's, `PYAUTO_MAIN` at the fixture (default `<tmp_path>/main`)."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "PYAUTO_MAIN": str(main or tmp_path / "main"),
        "PYAUTO_WT_ROOT": str(tmp_path / "wt"),
    }


def run_brain(verb: str, args, root=None, env: dict | None = None, **kwargs):
    """`pyauto-brain <verb> <args>` under the caller's environment, with
    `PYAUTO_ROOT` at `root` (when given) and `env` layered on top."""
    full = dict(os.environ)
    if root is not None:
        full["PYAUTO_ROOT"] = str(root)
    full.update(env or {})
    return subprocess.run([str(BRAIN), verb, *args],
                          capture_output=True, text=True, env=full, **kwargs)
