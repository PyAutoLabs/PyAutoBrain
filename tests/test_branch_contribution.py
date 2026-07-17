"""tests/test_branch_contribution.py — the blessed branch-contribution instrument.

docs/agent_failure_modes.md item 4 (D1/D2): "does this branch contribute content
to main?" was hand-rolled three times, two ways wrong. This drives the tool's own
self-test, which constructs known-answer repos (CONTRIBUTES / MERGED / ABSORBED /
squash-limitation / UNKNOWN) and asserts each verdict — the "validate the
instrument against known ground truth" habit (D2's one clean save) as CI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "bin" / "branch_contribution.sh"


def test_self_test_passes():
    proc = subprocess.run(
        ["bash", str(TOOL), "--self-test"], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all 5 verdicts correct" in proc.stdout


def _verdict(tmp_path: Path, setup: list[list[str]]) -> tuple[int, str]:
    repo = tmp_path / "r"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True,
                                    capture_output=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    run("config", "user.email", "t@t"); run("config", "user.name", "t")
    (repo / "f").write_text("base"); run("add", "f"); run("commit", "-qm", "base")
    for cmd in setup:
        run(*cmd)
    proc = subprocess.run(
        ["bash", str(TOOL), str(repo), "feat", "main"], capture_output=True, text=True
    )
    return proc.returncode, proc.stdout.strip()


def test_contributes(tmp_path):
    rc, out = _verdict(tmp_path, [["checkout", "-q", "-b", "feat"]])
    # feat with a unique commit
    repo = tmp_path / "r"
    (repo / "g").write_text("w")
    subprocess.run(["git", "-C", str(repo), "add", "g"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "w"], check=True)
    proc = subprocess.run(["bash", str(TOOL), str(repo), "feat", "main"],
                          capture_output=True, text=True)
    assert proc.returncode == 0 and proc.stdout.startswith("CONTRIBUTES")


def test_unknown_branch_is_fail_safe(tmp_path):
    rc, out = _verdict(tmp_path, [])
    assert rc == 4 and out.startswith("UNKNOWN")
