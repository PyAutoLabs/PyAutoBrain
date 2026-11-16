"""The `/cockpit` skill (PyAutoBrain#646): watch a shift and steer it from chat.

The witness: the Monitor command the skill tells a session to arm is the
canonical stream command the end-at-deliverable hook allows. It is checked
against the hook's own `STREAM_RE` and fed through the real hook script (this
repo's installed copy, byte-identical to PyAutoMind's canonical file and
drift-checked by `repos_sync.py --check`) with a fictional workspace and shift
record, mid-window. The steering verbs are the watcher's own, and the routers
send a cockpit-chat paste to `/add`, never to start_dev.
"""

import ast
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
SKILL = BRAIN / "skills" / "cockpit"
HOOK = BRAIN / ".claude" / "hooks" / "end-at-deliverable.sh"
SLOT = "2026-11-16-pm"


def _front(path: Path) -> dict:
    block = path.read_text().split("---", 2)[1]
    return dict(line.split(": ", 1) for line in block.strip().splitlines())


def _procedure() -> str:
    return (SKILL / "cockpit.md").read_text()


def _template() -> str:
    """The one Monitor command line the procedure gives, placeholders and all."""
    lines = [line.strip() for line in _procedure().splitlines()
             if "batch watch --stream --record" in line and "--for" in line]
    assert len(lines) == 1, lines
    return lines[0]


def _stream_re():
    """`STREAM_CHARS_RE` and `STREAM_RE`, taken from the hook's own source."""
    text = HOOK.read_text()
    start = text.index("STREAM_CHARS_RE = ")
    end = text.index("# Anything that reads the watcher's state")
    namespace = {"re": re}
    exec(text[start:end], namespace)  # noqa: S102 — the hook's own regex definitions
    return namespace["STREAM_CHARS_RE"], namespace["STREAM_RE"]


def _workspace(tmp_path, *, dispatched, review_at):
    """A fictional workspace: real Brain resolver, a CLI file, one record."""
    ws = tmp_path / "ws"
    for repo in ("PyAutoBrain", "PyAutoMind"):
        (ws / repo / ".git").mkdir(parents=True)
    (ws / "PyAutoBrain" / "agents").mkdir()
    shutil.copy(BRAIN / "agents" / "_repo_paths.py",
                ws / "PyAutoBrain" / "agents" / "_repo_paths.py")
    (ws / "PyAutoBrain" / "bin").mkdir()
    (ws / "PyAutoBrain" / "bin" / "pyauto-brain").write_text("#!/bin/sh\n")
    (ws / "PyAutoMind" / "batches").mkdir()
    stamp = "%Y-%m-%dT%H:%M:%SZ"
    (ws / "PyAutoMind" / "batches" / f"{SLOT}.md").write_text(
        f"# Batch {SLOT}\n- dispatched: {dispatched:{stamp}}\n"
        f"- review-at: {review_at:{stamp}}\n- brief:\n")
    return ws


def _command(ws, *, seq="42", first=False):
    cmd = _template()
    if first:
        cmd = cmd.replace(" --from <seq>", "")
    return (cmd.replace("<BRAIN>", str(ws / "PyAutoBrain"))
               .replace("<MIND>", str(ws / "PyAutoMind"))
               .replace("<slot>", SLOT).replace("<seq>", seq))


def _hook(ws, command):
    payload = json.dumps({"tool_name": "Monitor", "tool_input": {
        "command": command, "description": f"shift {SLOT} events",
        "timeout_ms": 1800000}})
    env = {**os.environ, "PYAUTO_ROOT": str(ws)}
    env.pop("PYAUTO_ALLOW_TIMERS", None)
    return subprocess.run([str(HOOK)], input=payload, capture_output=True,
                          text=True, env=env)


# -- the contract with the hook ------------------------------------------------

def test_the_skill_gives_one_canonical_monitor_command():
    assert _template() == (
        "<BRAIN>/bin/pyauto-brain batch watch --stream --record "
        "<MIND>/batches/<slot>.md --from <seq> --for 28")
    proc = _procedure()
    assert "timeout_ms: 1800000" in proc
    assert "--for 28" in proc  # one segment ends before Monitor's 30-minute cap


@pytest.mark.parametrize("first", [False, True])
def test_the_command_matches_the_hooks_stream_re(tmp_path, first):
    chars, stream = _stream_re()
    now = datetime.now(timezone.utc)
    ws = _workspace(tmp_path, dispatched=now - timedelta(hours=1),
                    review_at=now + timedelta(hours=1))
    cmd = _command(ws, first=first)
    assert chars.fullmatch(cmd), cmd
    assert stream.fullmatch(cmd), cmd


@pytest.mark.parametrize("first", [False, True])
def test_the_real_hook_allows_the_command_mid_window(tmp_path, first):
    now = datetime.now(timezone.utc)
    ws = _workspace(tmp_path, dispatched=now - timedelta(hours=1),
                    review_at=now + timedelta(hours=1))
    result = _hook(ws, _command(ws, first=first))
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_the_real_hook_refuses_the_same_command_after_the_window(tmp_path):
    """The other half of the carve-out: re-arming after the shift is refused."""
    now = datetime.now(timezone.utc)
    review_at = now - timedelta(minutes=46)
    ws = _workspace(tmp_path, dispatched=review_at - timedelta(hours=2),
                    review_at=review_at)
    result = _hook(ws, _command(ws))
    assert result.returncode == 2
    assert "outside its window" in result.stderr


def test_a_command_with_a_variable_left_in_is_refused(tmp_path):
    """The skill says literal text only: the hook refuses `$`."""
    now = datetime.now(timezone.utc)
    ws = _workspace(tmp_path, dispatched=now - timedelta(hours=1),
                    review_at=now + timedelta(hours=1))
    cmd = _command(ws).replace(str(ws / "PyAutoBrain"), "$BRAIN")
    assert _hook(ws, cmd).returncode == 2
    assert "No `$VAR`" in _procedure()


def test_the_hook_copy_is_the_one_the_harness_runs():
    settings = json.loads((BRAIN / ".claude" / "settings.json").read_text())
    matchers = [g.get("matcher", "") for g in settings["hooks"]["PreToolUse"]]
    assert any(re.match(m, "Monitor") for m in matchers if m), matchers


# -- re-arm and report ---------------------------------------------------------

def test_the_only_re_arm_is_at_segment_end():
    proc = _procedure()
    assert "segment-end next=--from N" in proc
    assert "This is the only re-arm." in proc
    assert "Do not arm again." in proc
    assert "re-arming after any exit but\n  `segment-end`" in proc


def test_only_needs_you_lines_are_pushed():
    proc = _procedure()
    assert "NEEDS YOU:" in proc and "PushNotification" in proc
    assert "Nothing else is pushed." in proc
    assert "one plain line per event" in proc
    assert "Never add `--json`" in proc


# -- steering ------------------------------------------------------------------

def _watcher_verbs() -> tuple:
    source = (BRAIN / "agents" / "conductors" / "batch" / "_orchestrator.py").read_text()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "COMMANDS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("no COMMANDS in _orchestrator.py")


def test_the_steering_table_covers_exactly_the_watchers_verbs():
    proc = _procedure()
    cells = [line.split("|")[2].strip() for line in proc.splitlines()
             if line.startswith("| \"")]
    # A comment cell starts with the command; "not a comment: the `/prm` …"
    # rows route elsewhere and post nothing.
    comments = [cell for cell in cells if cell.startswith("`/")]
    named = set(re.findall(r"`/([a-z]+)\b", " ".join(comments)))
    assert named == set(_watcher_verbs()), named
    assert all(cell.startswith("not ") for cell in cells if cell not in comments)


@pytest.mark.parametrize("verb", ["/stop", "/kill"])
def test_stop_and_kill_are_confirmed_first(verb):
    rows = [line for line in _procedure().splitlines()
            if line.startswith("| \"") and f"`{verb}" in line.split("|")[2]]
    assert rows and all("**yes**" in row for row in rows), rows


def test_steering_is_one_comment_from_the_humans_login():
    proc = _procedure()
    assert "gh issue comment <issue-url> --body-file -" in proc
    assert "(said in the cockpit:" in proc
    assert "gh api user --jq .login" in proc
    assert "batch premise <path>" in proc and "obsolete" in proc


# -- questions and routing -------------------------------------------------------

def test_questions_go_to_the_questions_skill_and_degrade_without_it():
    proc = _procedure()
    assert "`/questions`" in proc
    assert "origin/main:questions.md" in proc
    assert "the questions inbox is not\ninstalled yet" in proc


def test_the_skill_ships_and_says_a_paste_is_an_add():
    front = _front(SKILL / "SKILL.md")
    assert front["name"] == "cockpit"
    assert re.fullmatch(r"[a-z0-9-]+", front["name"])
    assert "never start dev" in front["description"]
    assert "It never means start dev" in (SKILL / "SKILL.md").read_text()


def test_the_routers_send_a_cockpit_chat_paste_to_add_not_start_dev():
    commands = (BRAIN / "skills" / "COMMANDS.md").read_text()
    assert "**`/cockpit`**" in commands and "never start dev" in commands
    route = (BRAIN / "skills" / "route" / "route.md").read_text()
    assert "A cockpit chat is not a dev request" in route
    assert "../cockpit/cockpit.md" in route
    start = BRAIN / "skills" / "start_dev" / "SKILL.md"
    assert "/cockpit chat" in _front(start)["description"]
    assert "../cockpit/cockpit.md" in start.read_text()


def test_the_skill_is_discoverable():
    """Committed discovery, as `install.sh --write-project-discovery` makes it."""
    assert (BRAIN / ".claude" / "skills" / "cockpit").resolve() == SKILL
    assert (BRAIN / ".codex" / "skills" / "cockpit").resolve() == SKILL
    assert (BRAIN / ".claude" / "commands" / "cockpit.md").read_text() == _procedure()
