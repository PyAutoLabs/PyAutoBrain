"""bin/pyauto-brain runs the Mind's session bootstrap in a remote session.

Regression: the dispatcher called ``resolve_mind`` without sourcing
``agents/_common.sh``, so every remote verb printed "resolve_mind: command not
found" and silently skipped the bootstrap.
"""

import os
import subprocess
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
BRAIN = BRAIN_HOME / "bin" / "pyauto-brain"


def _fake_mind(tmp_path):
    mind = tmp_path / "PyAutoMind"
    (mind / "scripts").mkdir(parents=True)
    marker = tmp_path / "bootstrapped"
    boot = mind / "scripts" / "session_bootstrap.sh"
    boot.write_text(f"#!/usr/bin/env bash\ntouch {marker}\n")
    boot.chmod(0o755)
    return mind, marker


def _run(tmp_path, mind, remote):
    env = {k: v for k, v in os.environ.items() if k != "PYAUTO_SKIP_BOOTSTRAP"}
    env["PYAUTO_MIND"] = str(mind)
    env["CLAUDE_CODE_REMOTE"] = "true" if remote else "false"
    return subprocess.run(
        [str(BRAIN), "no-such-verb"], env=env, capture_output=True, text=True, cwd=tmp_path
    )


def test_remote_session_runs_the_mind_bootstrap(tmp_path):
    mind, marker = _fake_mind(tmp_path)
    proc = _run(tmp_path, mind, remote=True)
    assert proc.returncode == 2, proc.stderr  # bootstrap runs, then dispatch rejects the verb
    assert "command not found" not in proc.stderr
    assert marker.exists()


def test_local_session_skips_the_bootstrap(tmp_path):
    mind, marker = _fake_mind(tmp_path)
    proc = _run(tmp_path, mind, remote=False)
    assert proc.returncode == 2, proc.stderr  # no bootstrap; dispatch still rejects the verb
    assert not marker.exists()
