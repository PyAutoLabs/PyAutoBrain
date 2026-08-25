"""tests/test_branch_sweep.py — what the sweep REFUSES to delete.

branch_sweep.sh is the one PyAuto script whose job is irreversible from the
branch's point of view, and it runs unattended on Actions where nobody sees the
dashboard before it acts. Its value is therefore not the deletions — those are
one `git push --delete` — but the four gates that keep a branch out of the
delete set. Each gate gets a known-answer repo here, in the spirit of
test_branch_contribution.py: a gate that silently stopped working would look
exactly like a clean sweep.

The gates, and what breaking each one would cost:

  main / default branch     the repo
  archive/condemned/*       PyAutoGut's recovery path — these refs ARE the
                            backup for condemned work, so voiding one early
                            destroys the only copy
  open PR heads             someone's in-flight review
  unproven CONTRIBUTES      unmerged work, gone

`gh` is stubbed: the script refuses to run without it (it cannot rule out open
PRs blind), and these tests pin that refusal too.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "bin" / "branch_sweep.sh"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _commit(repo: Path, name: str, body: str, message: str) -> None:
    (repo / name).write_text(body)
    _git(repo, "add", name)
    _git(repo, "commit", "-qm", message)


@pytest.fixture
def world(tmp_path: Path):
    """An origin with one branch per verdict, and a clone that sweeps it."""
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
    _git(origin, "config", "user.email", "t@t")
    _git(origin, "config", "user.name", "t")
    _git(origin, "config", "receive.denyDeleteCurrent", "ignore")
    _commit(origin, "f", "base", "base")

    # merged: folded into main, so main contains its tip
    _git(origin, "checkout", "-q", "-b", "merged")
    _commit(origin, "m", "m", "merged work")
    _git(origin, "checkout", "-q", "main")
    _git(origin, "merge", "-q", "--no-ff", "merged", "-m", "Merge merged")

    # unmerged: unique content main has never seen
    _git(origin, "checkout", "-q", "-b", "unmerged", "main")
    _commit(origin, "u", "u", "unmerged work")

    # an open PR's head, and a Gut transit ref — both fully merged, so ONLY
    # their protection can keep them out of the delete set
    for name in ("open-pr-head", "archive/condemned/something"):
        _git(origin, "checkout", "-q", "-b", name, "main")
    _git(origin, "checkout", "-q", "main")

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(clone)], check=True
    )
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "auth" ]]; then exit 0; fi\n'
        'if [[ "$1" == "api" ]]; then exit 0; fi\n'
        'echo "open-pr-head"\n'
        "exit 0\n"
    )
    (bin_dir / "gh").chmod(0o755)
    return clone, origin, bin_dir


def _gh_free_path(tmp_path: Path) -> str:
    """A PATH with everything the script needs except `gh`.

    Emptying PATH would remove bash too and prove nothing, so link in the tools
    the script actually calls and leave `gh` out.
    """
    lean = tmp_path / "nogh"
    lean.mkdir(exist_ok=True)
    for tool in ("bash", "git", "sed", "awk", "grep", "sort", "head", "cut", "tr",
                 "dirname", "basename", "cat", "wc", "env", "uniq"):
        found = shutil.which(tool)
        if found and not (lean / tool).exists():
            (lean / tool).symlink_to(found)
    return str(lean)


def _sweep(clone: Path, bin_dir: Path | None, mode: str = "audit") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    else:
        env["PATH"] = _gh_free_path(clone.parent)
    return subprocess.run(
        ["bash", str(TOOL), "--repo", str(clone), "--owner", "o", "--name", "n",
         "--mode", mode],
        capture_output=True, text=True, env=env, timeout=120,
    )


def test_audit_classifies_every_branch(world):
    clone, _, bin_dir = world
    out = _sweep(clone, bin_dir).stdout
    assert "merged\tMERGED" in out
    assert "unmerged\tunmerged" in out
    assert "open-pr-head\topen-pr" in out
    assert "archive/condemned/something\tgut-transit-ref" in out


def test_symbolic_head_is_not_reported_as_a_branch(world):
    """refs/remotes/origin/HEAD must not surface as a branch called "origin".

    Git abbreviates that ref to bare `origin`, which slips past an `origin/`
    strip and a `!= HEAD` guard and then lands in KEEP with verdict UNKNOWN —
    a symbolic ref rendered as unmerged work. It was never deletable, so the
    cost is a wrong count and a reader misled about what is outstanding.
    """
    clone, _, bin_dir = world
    out = _sweep(clone, bin_dir).stdout
    assert "origin\tUNKNOWN" not in out
    assert "\n  origin\t" not in out
    # the real answer for this fixture, with nothing invented alongside it
    assert "1 unmerged" in out


def test_audit_never_deletes(world):
    clone, origin, bin_dir = world
    before = _git(origin, "for-each-ref", "--format=%(refname)", "refs/heads")
    assert _sweep(clone, bin_dir, mode="audit").returncode == 0
    assert _git(origin, "for-each-ref", "--format=%(refname)", "refs/heads") == before


def test_delete_removes_only_the_contained_branch(world):
    clone, origin, bin_dir = world
    assert _sweep(clone, bin_dir, mode="delete").returncode == 0
    remaining = _git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    remaining = set(remaining.split())
    assert "merged" not in remaining, "a contained branch should have been swept"
    # every gate held
    assert {"main", "unmerged", "open-pr-head", "archive/condemned/something"} <= remaining


def test_a_legacy_trunk_is_protected_even_when_fully_merged(tmp_path):
    """`master` after a main<-master migration is not an ordinary branch.

    It is protected on NAME, not on containment: once folded into main it looks
    exactly like spent work, and deleting it breaks every stale clone, bookmark
    and doc still pointing at it. The first org-wide audit found a repo whose
    `master` survived only because it happened to carry unique content — luck,
    not a gate.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
    _git(origin, "config", "user.email", "t@t")
    _git(origin, "config", "user.name", "t")
    _commit(origin, "f", "base", "base")
    # a legacy trunk fully contained in main — indistinguishable from spent work
    _git(origin, "branch", "master")

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text('#!/usr/bin/env bash\nexit 0\n')
    (bin_dir / "gh").chmod(0o755)

    assert _sweep(clone, bin_dir, mode="delete").returncode == 0
    remaining = set(_git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads").split())
    assert "master" in remaining, "a legacy trunk must never be swept"


def _readonly_origin(tmp_path: Path):
    """A world whose origin refuses ref deletion, like a read-only credential."""
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
    _git(origin, "config", "user.email", "t@t")
    _git(origin, "config", "user.name", "t")
    _commit(origin, "f", "base", "base")
    for i in range(5):
        _git(origin, "branch", f"spent{i}")           # all contained in main
    # the closest local stand-in for "this credential may not delete refs"
    _git(origin, "config", "receive.denyDeletes", "true")

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text('#!/usr/bin/env bash\nexit 0\n')
    (bin_dir / "gh").chmod(0o755)
    return clone, origin, bin_dir


def test_a_failed_delete_reports_why(tmp_path):
    """`FAILED <branch>` with no reason is barely better than silence.

    The first org-wide delete run failed 99 times and recorded nothing but the
    word FAILED, because the push was redirected to /dev/null. The error text
    is the only thing a failure carries; keep it.
    """
    clone, _, bin_dir = _readonly_origin(tmp_path)
    out = _sweep(clone, bin_dir, mode="delete").stdout
    assert "FAILED" in out
    assert "no error text returned" not in out, "the push error was swallowed"
    assert "denyDeletes" in out or "denied" in out.lower() or "error" in out.lower()


def test_repeated_delete_failures_stop_early(tmp_path):
    """Delete permission belongs to the credential, not the branch.

    Once a few in a row fail the answer is known for all of them, so grinding
    through the rest only buries the reason.
    """
    clone, origin, bin_dir = _readonly_origin(tmp_path)
    proc = _sweep(clone, bin_dir, mode="delete")
    assert proc.returncode == 2, "a run where nothing could be deleted must not report success"
    assert "Stopping:" in proc.stdout
    # stopped after the streak rather than attempting all five
    assert proc.stdout.count("FAILED") == 3
    remaining = set(_git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads").split())
    assert {f"spent{i}" for i in range(5)} <= remaining, "nothing should have been deleted"


def test_refuses_to_run_without_gh(world):
    """Blind to open PRs means blind to in-flight work: refuse, do not guess."""
    clone, _, _ = world
    proc = _sweep(clone, None)
    assert proc.returncode == 1
    assert "gh not found" in proc.stderr


def test_rejects_unknown_mode(world):
    clone, _, bin_dir = world
    proc = _sweep(clone, bin_dir, mode="purge")
    assert proc.returncode == 1
    assert "must be 'audit' or 'delete'" in proc.stderr
