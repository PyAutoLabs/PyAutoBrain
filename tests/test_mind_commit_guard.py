"""tests/test_mind_commit_guard.py — the shared-Mind commit refusal.

docs/agent_failure_modes.md mitigation 2: E1 + F1 (x3) — four swept-index
incidents in two days. The guard refuses commits in the shared PyAutoMind
checkout that lack explicit file pathspecs, or that pass directories.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from mind_commit_guard import check_command  # noqa: E402

MIND = "/home/jammy/Code/PyAutoLabs/PyAutoMind"


def test_bare_commit_in_mind_denied():
    r = check_command(f'cd {MIND} && git commit -m "msg"')
    assert r and "explicit `-- <files>`" in r


def test_commit_dash_c_without_pathspecs_denied():
    r = check_command(f'git -C {MIND} commit -m "msg"')
    assert r is not None


def test_commit_with_file_pathspecs_allowed(tmp_path):
    mind = tmp_path / "PyAutoMind"
    mind.mkdir()
    (mind / "active.md").write_text("x")
    r = check_command(f'git -C {mind} commit -m "msg" -- active.md')
    assert r is None


def test_commit_with_directory_pathspec_denied(tmp_path):
    mind = tmp_path / "PyAutoMind"
    (mind / "active").mkdir(parents=True)
    r = check_command(f'git -C {mind} commit -m "msg" -- active/')
    assert r and "DIRECTORY" in r


def test_non_mind_commit_allowed():
    assert check_command('git -C /home/x/PyAutoFit commit -m "msg"') is None


def test_non_commit_mind_command_allowed():
    assert check_command(f"git -C {MIND} status") is None


def test_escape_hatch_allows():
    assert (
        check_command(f'PYAUTO_SKIP_MIND_GUARD=1 git -C {MIND} commit -m "bulk"')
        is None
    )


def test_cwd_detection(tmp_path):
    mind = tmp_path / "PyAutoMind"
    mind.mkdir()
    r = check_command('git commit -m "msg"', cwd=str(mind))
    assert r is not None


def test_compound_command_second_clause_checked(tmp_path):
    mind = tmp_path / "PyAutoMind"
    mind.mkdir()
    (mind / "planned.md").write_text("x")
    ok = f'cd {mind} && git add planned.md && git commit -m "m" -- planned.md'
    assert check_command(ok) is None
    bad = f'cd {mind} && git add -A && git commit -m "m"'
    assert check_command(bad) is not None


def test_amend_and_dry_run_are_exempt(tmp_path):
    mind = tmp_path / "PyAutoMind"
    mind.mkdir()
    assert check_command(f'git -C {mind} commit --amend --no-edit') is None
