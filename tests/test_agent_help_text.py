"""The feature, build and bug agents print their header comment as ``--help``.

The help is the script's leading comment block, printed up to the first
non-comment line, so it neither leaks shell code nor stops short of the end of
the header.
"""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ["feature", "build", "bug"]


def _help(agent: str) -> str:
    script = ROOT / "agents" / "conductors" / agent / f"{agent}.sh"
    proc = subprocess.run(
        ["bash", str(script), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.mark.parametrize("agent", AGENTS)
def test_help_prints_header_only(agent):
    out = _help(agent)
    lines = out.splitlines()
    assert lines, f"{agent} --help printed nothing"
    assert "Usage:" in out
    # The header ends with the exit codes; nothing after them is printed.
    tail = out.rstrip("\n").split("\n\n")[-1]
    assert tail.startswith("Exit codes:"), tail
    assert not [line for line in lines if line.startswith("set ")]
    assert not [line for line in lines if line.startswith("#")]
    assert not [line for line in lines if line.startswith(("source ", "HERE=", "HEART_ISSUES_REPO="))]


def test_build_help_names_every_option_and_the_exit_codes():
    out = _help("build")
    for flag in ("--rehearsal-run-id", "--dry-run", "--json", "--force", "--accept-red"):
        assert flag in out, flag
    assert "Exit codes:" in out
    assert "5 invalid mode/action" in out
