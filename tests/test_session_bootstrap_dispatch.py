"""bin/pyauto-brain runs the Mind's session bootstrap in remote sessions.

Regression: ensure_session_environment called resolve_mind, which is defined
in agents/_common.sh and was never sourced by the dispatcher, so every verb in
a remote session printed "resolve_mind: command not found" and silently
skipped the bootstrap.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]


def _run(tmp_path: Path, **env_overrides: str) -> tuple[subprocess.CompletedProcess, Path]:
    mind = tmp_path / "PyAutoMind"
    (mind / "scripts").mkdir(parents=True)
    marker = tmp_path / "bootstrapped"
    boot = mind / "scripts" / "session_bootstrap.sh"
    boot.write_text(f"#!/usr/bin/env bash\ntouch {marker}\n")
    boot.chmod(0o755)
    env = {
        **os.environ,
        "CLAUDE_CODE_REMOTE": "true",
        "PYAUTO_MIND": str(mind),
    }
    env.pop("PYAUTO_SKIP_BOOTSTRAP", None)
    env.update(env_overrides)
    # An unknown agent still passes through ensure_session_environment, then
    # exits 2 without running anything else.
    result = subprocess.run(
        ["bash", str(BRAIN / "bin" / "pyauto-brain"), "no-such-agent"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    return result, marker


def test_remote_session_runs_mind_bootstrap(tmp_path):
    result, marker = _run(tmp_path)
    assert result.returncode == 2
    assert "command not found" not in result.stderr
    assert marker.exists()


def test_skip_bootstrap_is_honoured(tmp_path):
    result, marker = _run(tmp_path, PYAUTO_SKIP_BOOTSTRAP="1")
    assert result.returncode == 2
    assert "command not found" not in result.stderr
    assert not marker.exists()
