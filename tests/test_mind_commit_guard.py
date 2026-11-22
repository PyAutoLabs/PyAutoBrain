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


@pytest.fixture
def mind(tmp_path):
    """A stand-in shared Mind checkout: two files and one directory to name as
    pathspecs. `{mind}` in a table row below is this path."""
    mind = tmp_path / "PyAutoMind"
    (mind / "active").mkdir(parents=True)
    (mind / "active.md").write_text("x")
    (mind / "planned.md").write_text("x")
    return mind


def _check(mind, command, cwd):
    fill = lambda text: text.replace("{mind}", str(mind))  # noqa: E731
    return check_command(fill(command), cwd=fill(cwd)) if cwd else check_command(fill(command))


# (command, cwd the hook is handed or None, text the refusal must carry or None)
DENIED = [
    pytest.param(f'cd {MIND} && git commit -m "msg"', None, "explicit `-- <files>`",
                 id="bare-commit-in-mind"),
    pytest.param(f'git -C {MIND} commit -m "msg"', None, None,
                 id="commit-dash-C-without-pathspecs"),
    pytest.param('git -C {mind} commit -m "msg" -- active/', None, "DIRECTORY",
                 id="directory-pathspec"),
    pytest.param('git commit -m "msg"', "{mind}", None, id="cwd-detection"),
    pytest.param('cd {mind} && git add -A && git commit -m "m"', None, None,
                 id="compound-second-clause-checked"),
    # v1.1: a `;` inside the quoted message must not hide a bare commit.
    pytest.param('cd {mind} && git commit -q -m "msg; with semicolon" && echo ok',
                 None, None, id="bare-commit-in-compound-with-quotes"),
    # v1.2: a `cd` / `-C` INTO Mind from elsewhere is still a Mind commit.
    pytest.param('cd /home/x/PyAutoMind && git commit -m "m"', "/tmp/elsewhere", None,
                 id="cd-into-mind-then-bare-commit"),
    pytest.param('git -C /home/x/PyAutoMind commit -m "m"', "/home/x/wt/PyAutoHands",
                 None, id="git-dash-C-into-mind-from-other-cwd"),
    # v1.3: `for`/`done` inside a commit message are one shlex token, so they
    # must NOT be read as compound keywords — the bare-commit denial still
    # fires (the narrowing below cannot silently widen).
    pytest.param('git -C {mind} commit -m "done waiting for the run"', None, None,
                 id="compound-word-inside-quoted-message-does-not-fail-open"),
]


@pytest.mark.parametrize("command,cwd,needle", DENIED)
def test_denied(mind, command, cwd, needle):
    refusal = _check(mind, command, cwd)
    assert refusal is not None
    if needle:
        assert needle in refusal


ALLOWED = [
    pytest.param('git -C {mind} commit -m "msg" -- active.md', None,
                 id="file-pathspecs"),
    pytest.param('git -C /home/x/PyAutoFit commit -m "msg"', None, id="non-mind-commit"),
    pytest.param(f"git -C {MIND} status", None, id="non-commit-mind-command"),
    pytest.param(f'PYAUTO_SKIP_MIND_GUARD=1 git -C {MIND} commit -m "bulk"', None,
                 id="escape-hatch"),
    pytest.param('cd {mind} && git add planned.md && git commit -m "m" -- planned.md',
                 None, id="compound-second-clause-checked"),
    pytest.param('git -C {mind} commit --amend --no-edit', None, id="amend-is-exempt"),
    # --- v1.1: the two live false positives from the guard's first hour ---
    # First live firing: a `gh issue comment` whose BODY prose mentioned the
    # trigger words. Quoted bodies are single tokens; no git-commit clause.
    pytest.param('gh issue comment 130 --repo X --body "the Mind commit guard denies '
                 'bare commits in the shared PyAutoMind checkout via git" '
                 "&& echo done", None, id="gh-comment-prose-does-not-trigger"),
    # Second live firing: a `;` INSIDE the quoted -m message made v1.0's raw
    # regex split strand the `--` in the next pseudo-clause.
    pytest.param('cd {mind} && git pull --ff-only -q && '
                 'git commit -q -m "prompt: task complete; all phases complete" '
                 "-- active.md && git push -q origin main", None,
                 id="semicolon-inside-commit-message-keeps-pathspecs"),
    # --- v1.2: honour a `cd` away from Mind ---
    # The 2026-07-17 false positive: session cwd was PyAutoMind (what the hook
    # is handed) but the command cd's to a PyAutoHands worktree first. That is
    # NOT a Mind commit — a bare `git commit` there is fine.
    pytest.param('cd /home/x/wt/PyAutoHands && git add a && git commit -m "m"',
                 "/home/x/PyAutoMind", id="cd-to-other-repo-before-commit"),
    pytest.param('git -C /home/x/wt/PyAutoHands commit -m "m"', "/home/x/PyAutoMind",
                 id="git-dash-C-to-other-repo-from-mind-cwd"),
    # --- v1.3: fail open on shell the clause walk cannot attribute ---
    # Every live firing of the guard was a false positive on its own author.
    # Each of the three shapes below is allowed now.
    # The 3rd false positive (2026-07-17): the `cd` follows `do`, so it is not
    # a clause-leading token and v1.2 resolved the commit to the ambient Mind
    # cwd. These commits were all in workspace repos.
    pytest.param('for r in alpha_workspace beta_workspace; do cd /home/x/$r && '
                 'git commit -m "floors" -- config/general.yaml; done',
                 "/home/x/PyAutoMind", id="for-loop-with-inner-cd"),
    pytest.param('(cd /home/x/wt/PyAutoHands && git commit -m "m")',
                 "/home/x/PyAutoMind", id="subshell-cd-then-commit"),
    pytest.param('while read -r f; do git commit -m "m" -- "$f"; done < list.txt',
                 "/home/x/PyAutoMind", id="while-loop-commit"),
]


@pytest.mark.parametrize("command,cwd", ALLOWED)
def test_allowed(mind, command, cwd):
    assert _check(mind, command, cwd) is None


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
