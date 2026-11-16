"""The `/queue` skill (PyAutoBrain#640): `queue.md` is maintained in chat.

The witness: in a chat that ran `/queue`, a pasted task means "add it to the
queue" and never routes to start_dev; the add goes through the Mind's
`scripts/queue_edit.py` (never a hand edit), and the line the dashboard's 📋
copies is a line that script takes. The script's own contract (add, remove,
move, `lifecycle.py check` clean) is the Mind's `tests/test_queue_edit.py`;
the end-to-end leg here runs when the sibling Mind is checked out.
"""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
SKILL = BRAIN / "skills" / "queue"
MIND = BRAIN.parent / "PyAutoMind"

_spec = importlib.util.spec_from_file_location(
    "_intake_queue_skill_under_test", BRAIN / "agents" / "conductors" / "intake" / "_intake.py")
_intake = importlib.util.module_from_spec(_spec)
sys.modules["_intake_queue_skill_under_test"] = _intake
_spec.loader.exec_module(_intake)


def _front(path: Path) -> dict:
    text = path.read_text()
    block = text.split("---", 2)[1]
    return dict(line.split(": ", 1) for line in block.strip().splitlines())


def test_the_skill_ships_and_says_a_paste_is_an_add():
    front = _front(SKILL / "SKILL.md")
    assert front["name"] == "queue"
    assert "never start dev" in front["description"]
    body = (SKILL / "SKILL.md").read_text() + (SKILL / "queue.md").read_text()
    assert "never means start dev" in body
    assert "never a start-dev" in body


def test_the_procedure_writes_through_the_script_and_a_detached_worktree():
    proc = (SKILL / "queue.md").read_text()
    for verb in ("add -", "remove ", "move ", "show"):
        assert f"queue_edit.py` {verb}" in proc or f"`{verb}" in proc, verb
    assert "worktree add -q --detach" in proc and "origin/main" in proc
    assert "PROMPT_SYNC_PUSH_TO=main" in proc and "prompt_sync_push" in proc
    assert re.search(r'prompt_sync_push "queue: [^"]*" queue\.md', proc)
    assert "python3 scripts/lifecycle.py check" in proc
    assert "never by hand" in (SKILL / "SKILL.md").read_text()
    assert "Never hand-edit `queue.md`" in proc


def test_the_routers_send_a_queue_chat_paste_to_queue_not_start_dev():
    commands = (BRAIN / "skills" / "COMMANDS.md").read_text()
    assert "**`/queue`**" in commands and "never start dev" in commands
    route = (BRAIN / "skills" / "route" / "route.md").read_text()
    assert "A queue chat is not a dev request" in route
    assert "never `/start_dev`" in route
    start = (BRAIN / "skills" / "start_dev" / "SKILL.md").read_text()
    assert "/queue chat" in _front(BRAIN / "skills" / "start_dev" / "SKILL.md")["description"]
    assert "../queue/queue.md" in start


def test_the_dashboard_copy_line_is_the_one_the_skill_names():
    line = _intake._prompt_payload("draft/feature/widgets/sprockets.md")
    assert line == "Use the start-dev skill. draft/feature/widgets/sprockets.md"
    assert "`Use the start-dev skill. <path>`" in (SKILL / "SKILL.md").read_text()


def test_the_install_scan_picks_the_skill_up():
    """`bin/install.sh` installs every `skills/<dir>/` with a SKILL.md (Claude
    and Codex) and its `<dir>.md` as a slash command."""
    assert (SKILL / "SKILL.md").is_file() and (SKILL / "queue.md").is_file()
    assert re.fullmatch(r"[a-z0-9-]+", _front(SKILL / "SKILL.md")["name"])


@pytest.mark.skipif(not (MIND / "scripts" / "queue_edit.py").is_file(),
                    reason="sibling PyAutoMind with queue_edit.py not checked out")
def test_a_pasted_copy_line_is_written_as_a_queue_entry(tmp_path):
    root = tmp_path / "mind"
    (root / "scripts").mkdir(parents=True)
    for name in ("lifecycle.py", "queue_edit.py"):
        shutil.copy(MIND / "scripts" / name, root / "scripts" / name)
    prompt = root / "draft" / "feature" / "widgets" / "sprockets.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("# Sprockets\n\nType: feature\n")
    (root / "queue.md").write_text("# Queue\n\n## Retired\n")
    paste = _intake._prompt_payload("draft/feature/widgets/sprockets.md")
    env = dict(os.environ, LIFECYCLE_NO_GH="1")
    res = subprocess.run([sys.executable, "scripts/queue_edit.py", "add", "-"], cwd=root,
                         input=paste, env=env, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert "1. Sprockets — draft/feature/widgets/sprockets.md" in res.stdout
    assert ("## 1. Sprockets\n- kind: prompt\n- ref: draft/feature/widgets/sprockets.md\n"
            in (root / "queue.md").read_text())
    # Nothing but queue.md moved: no active/ entry, no registry row, no claim.
    assert not (root / "active").exists() and not (root / "active.md").exists()
    check = subprocess.run([sys.executable, "scripts/lifecycle.py", "check"], cwd=root,
                           env=env, capture_output=True, text=True)
    assert "queue.md" not in check.stdout, check.stdout
