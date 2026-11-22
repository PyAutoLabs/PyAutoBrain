"""Shared plumbing for the batch-conductor / shift-orchestrator tests.

Only what was byte-for-byte the same in several files: the import bootstrap
for `agents/conductors/batch`, the shift clock, the worker draft, and a Mind
that is a real clone of a bare remote. Helpers that merely share a name
(`_shift`, `_mind`, `_tick`) differ per file and stay there. Fictional
fixtures only.
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
BATCH = BRAIN / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BATCH))
import _batch  # noqa: E402,F401 — one loaded conductor for every test file
import _orchestrator as orch  # noqa: E402

NOW = _dt.datetime(2026, 11, 4, 9, 0, tzinfo=_dt.timezone.utc)


def at(minutes: float) -> _dt.datetime:
    """`minutes` after the shift clock's NOW (09:00Z; dispatched 08:30Z)."""
    return NOW + _dt.timedelta(minutes=minutes)


PROMPT = """\
# {name}

Type: feature
Target: PyAutoBrain
Repos:
- PyAutoBrain
Difficulty: small
Autonomy: supervised
Priority: normal
Status: formalised
Consequence: glance
Witness: a unit test
Review-minutes: 3
Unattended: ready

Body.
"""


def write_drafts(mind: Path, names) -> str:
    """One ready glance draft per name under `draft/feature/pyautobrain/`;
    returns the brief's `tasks:` lines naming them."""
    folder = mind / "draft" / "feature" / "pyautobrain"
    folder.mkdir(parents=True)
    for n in names:
        (folder / f"{n}.md").write_text(PROMPT.format(name=n))
    return "\n".join(f"    - draft/feature/pyautobrain/{n}.md" for n in names)


def tick_posting(brief, mind, home, now, claude, gh, agents=None):
    """One tick with the real spawner over a fake `claude`, whose shift-issue
    comments go through the real `gh_comment` over a fake `gh`."""
    return orch.tick(brief, mind, home=home, now=now, grace_s=0,
                     spawner=orch.RealSpawner(brief, "auto", run=claude),
                     agents=agents or orch.AgentsView([]), tokens=lambda s: 0,
                     poster=lambda issue, body: orch.gh_comment(issue, body, run=gh))


# --- a Mind with a real origin ----------------------------------------------------

LEDGER_MERGE = BRAIN.parent / "PyAutoMind" / "scripts" / "ledger_merge.py"
if not LEDGER_MERGE.is_file():
    LEDGER_MERGE = Path(os.environ.get("PYAUTO_MIND", "/nonexistent")) / "scripts" / "ledger_merge.py"

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
needs_ledger_merge = pytest.mark.skipif(
    not LEDGER_MERGE.is_file() or shutil.which("git") is None,
    reason="needs git and PyAutoMind's scripts/ledger_merge.py")


def git(cwd, *args, check=True, env=None):
    """`git <args>` in `cwd`, failing loudly unless `check=False`."""
    res = subprocess.run(["git", *map(str, args)], cwd=cwd, capture_output=True,
                         text=True, env=env)
    if check:
        assert res.returncode == 0, (args, res.stderr)
    return res


def git_as_t(repo, *args, check=True):
    """`git -C <repo> <args>` with the author and committer in the environment
    (no repo config needed)."""
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    return subprocess.run(["git", "-C", str(repo), *args], check=check, env=env,
                          capture_output=True, text=True)


def git_out(cwd, *args) -> str:
    return git(cwd, *args).stdout.strip()


def identify(repo) -> None:
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")


def clone(bare: Path, dest: Path, *, identity=True) -> Path:
    git(bare.parent, "clone", "-q", bare, dest)
    if identity:
        identify(dest)
    return dest


def bare_mind(tmp_path: Path, bare="mind.git", name="mind", *, identity=False):
    """(bare remote on `main`, a clone of it) under `tmp_path`."""
    bare = tmp_path / bare
    git(tmp_path, "init", "-q", "--bare", "-b", "main", bare)
    return bare, clone(bare, tmp_path / name, identity=identity)


def commit(repo, msg="seed") -> None:
    """Everything in the tree, as one commit (its own identity)."""
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-q",
        "-m", msg)


def push(repo, msg="seed") -> None:
    """`commit`, then push to `origin/main` (the clone's own ref follows)."""
    commit(repo, msg)
    git(repo, "push", "-q", "origin", "HEAD:main")


def ledger_mind(tmp_path: Path, monkeypatch):
    """(bare remote, canonical clone) for a test that lands a record through
    the one Mind writer: the clone has an identity and PyAutoMind's
    `scripts/ledger_merge.py`. Seed it, then `push(canon)`."""
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    bare, canon = bare_mind(tmp_path, "remote.git", "canon", identity=True)
    (canon / "scripts").mkdir()
    shutil.copy(LEDGER_MERGE, canon / "scripts" / "ledger_merge.py")
    return bare, canon
