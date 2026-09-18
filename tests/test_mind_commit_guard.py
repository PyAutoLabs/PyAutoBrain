"""tests/test_mind_commit_guard.py — the shared-Mind commit refusal.

docs/agent_failure_modes.md mitigation 2: E1 + F1 (x3) — four swept-index
incidents in two days. The guard refuses commits in the shared PyAutoMind
checkout that lack explicit file pathspecs, or that pass directories.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from mind_commit_guard import check_command  # noqa: E402

MIND = "/home/jammy/Code/PyAutoLabs/PyAutoMind"
HOOK = Path(__file__).resolve().parents[1] / "bin" / "mind_commit_guard.py"


def run_codex_hook(payload):
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(HOOK)], input=body, capture_output=True, text=True
    )


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


# --- v1.1: the two live false positives from the guard's first hour ------------

def test_gh_comment_prose_does_not_trigger():
    # First live firing: a `gh issue comment` whose BODY prose mentioned the
    # trigger words. Quoted bodies are single tokens; no git-commit clause.
    cmd = (
        'gh issue comment 130 --repo X --body "the Mind commit guard denies '
        'bare commits in the shared PyAutoMind checkout via git" '
        "&& echo done"
    )
    assert check_command(cmd) is None


def test_semicolon_inside_commit_message_keeps_pathspecs(tmp_path):
    # Second live firing: a `;` INSIDE the quoted -m message made v1.0's raw
    # regex split strand the `--` in the next pseudo-clause.
    mind = tmp_path / "PyAutoMind"
    mind.mkdir()
    (mind / "active.md").write_text("x")
    cmd = (
        f'cd {mind} && git pull --ff-only -q && '
        f'git commit -q -m "prompt: task complete; all phases complete" '
        f"-- active.md && git push -q origin main"
    )
    assert check_command(cmd) is None


def test_bare_commit_still_denied_in_compound_with_quotes(tmp_path):
    mind = tmp_path / "PyAutoMind"
    mind.mkdir()
    cmd = f'cd {mind} && git commit -q -m "msg; with semicolon" && echo ok'
    assert check_command(cmd) is not None


# --- v1.2: honour a `cd` away from Mind (false positive on a PyAutoHands commit) ---
def test_cd_to_other_repo_before_commit_is_allowed():
    # The 2026-07-17 false positive: session cwd was PyAutoMind (what the hook
    # is handed) but the command cd's to a PyAutoHands worktree first. That is
    # NOT a Mind commit — a bare `git commit` there is fine.
    r = check_command(
        'cd /home/x/wt/PyAutoHands && git add a && git commit -m "m"',
        cwd="/home/x/PyAutoMind",
    )
    assert r is None


def test_git_dash_C_to_other_repo_from_mind_cwd_is_allowed():
    r = check_command(
        'git -C /home/x/wt/PyAutoHands commit -m "m"', cwd="/home/x/PyAutoMind"
    )
    assert r is None


def test_cd_into_mind_then_bare_commit_still_denied():
    r = check_command(
        'cd /home/x/PyAutoMind && git commit -m "m"', cwd="/tmp/elsewhere"
    )
    assert r is not None


def test_git_dash_C_into_mind_from_other_cwd_still_denied():
    r = check_command(
        'git -C /home/x/PyAutoMind commit -m "m"', cwd="/home/x/wt/PyAutoHands"
    )
    assert r is not None


# --- v1.3: fail open on shell the clause walk cannot attribute --------------
# Every live firing of the guard was a false positive on its own author. Each
# of the three shapes below is allowed now; the narrow high-confidence denials
# are re-asserted underneath so the narrowing cannot silently widen.


def test_for_loop_with_inner_cd_is_allowed():
    # The 3rd false positive (2026-07-17): the `cd` follows `do`, so it is not
    # a clause-leading token and v1.2 resolved the commit to the ambient Mind
    # cwd. These commits were all in workspace repos.
    r = check_command(
        'for r in alpha_workspace beta_workspace; do cd /home/x/$r && '
        'git commit -m "floors" -- config/general.yaml; done',
        cwd="/home/x/PyAutoMind",
    )
    assert r is None


def test_subshell_cd_then_commit_is_allowed():
    r = check_command(
        '(cd /home/x/wt/PyAutoHands && git commit -m "m")',
        cwd="/home/x/PyAutoMind",
    )
    assert r is None


def test_while_loop_commit_is_allowed():
    r = check_command(
        'while read -r f; do git commit -m "m" -- "$f"; done < list.txt',
        cwd="/home/x/PyAutoMind",
    )
    assert r is None


def test_compound_word_inside_quoted_message_does_not_fail_open(tmp_path):
    # `for`/`done` inside a commit message are one shlex token, so they must
    # NOT be read as compound keywords — the bare-commit denial still fires.
    mind = tmp_path / "PyAutoMind"
    mind.mkdir()
    r = check_command(f'git -C {mind} commit -m "done waiting for the run"')
    assert r is not None


def test_simple_shapes_still_denied_after_v13(tmp_path):
    mind = tmp_path / "PyAutoMind"
    (mind / "active").mkdir(parents=True)
    assert check_command(f'cd {mind} && git commit -m "m"') is not None
    assert check_command(f'git -C {mind} commit -m "m" -- active/') is not None


def test_codex_pre_tool_use_payload_denies_unsafe_mind_commit(tmp_path):
    mind = tmp_path / "PyAutoMind"
    mind.mkdir()
    result = run_codex_hook({
        "session_id": "codex-session",
        "turn_id": "turn-1",
        "tool_name": "Bash",
        "tool_use_id": "call-1",
        "cwd": str(mind),
        "hook_event_name": "PreToolUse",
        "tool_input": {"command": 'git commit -m "unsafe"'},
    })
    assert result.returncode == 0
    decision = json.loads(result.stdout)["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"


def test_codex_pre_tool_use_payload_allows_safe_mind_commit(tmp_path):
    mind = tmp_path / "PyAutoMind"
    mind.mkdir()
    (mind / "active.md").write_text("task\n")
    result = run_codex_hook({
        "turn_id": "turn-2",
        "tool_name": "Bash",
        "cwd": str(mind),
        "hook_event_name": "PreToolUse",
        "tool_input": {
            "command": 'git commit -m "safe" -- active.md'
        },
    })
    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.parametrize("payload", ["not-json", "[]", '{"tool_name":"Bash","tool_input":7}'])
def test_codex_malformed_payload_fails_open_without_crashing(payload):
    result = run_codex_hook(payload)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_codex_project_config_registers_mind_and_deliverable_guards():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / ".codex" / "hooks.json").read_text())
    groups = config["hooks"]["PreToolUse"]
    commands = [group["hooks"][0]["command"] for group in groups]
    assert [group["matcher"] for group in groups][0] == "Bash"
    assert all("git rev-parse --show-toplevel" in command for command in commands)
    assert any("bin/mind_commit_guard.py" in command for command in commands)
    assert any("end-at-deliverable.sh" in command for command in commands)
