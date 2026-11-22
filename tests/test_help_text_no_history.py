"""Tools whose module docstring is their ``--help`` describe what they do.

These modules pass ``description=__doc__`` (or its first line) to argparse, so
their docstring is program output. It says what the tool does, in the present
tense: no dates, milestone tags or issue references from how it came to be.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

TOOLS = [
    "agents/_repo_paths.py",
    "agents/conductors/clone/_clone.py",
    "agents/conductors/clone/check_boundary.py",
    "agents/conductors/community/_community.py",
    "agents/conductors/docs/_docs.py",
    "agents/conductors/hygiene/_hygiene_ci.py",
    "agents/conductors/hygiene/_hygiene_extras.py",
    "agents/conductors/hygiene/_hygiene_optdeps.py",
    "agents/conductors/hygiene/_hygiene_repos.py",
    "agents/conductors/hygiene/_hygiene_tokens.py",
    "agents/conductors/workspace/_workspace.py",
    "bin/codex_usage.py",
    "bin/dataset_provenance.py",
    "bin/lane_backfill.py",
    "bin/project_discovery.py",
    "bin/regroup_workspace.py",
    "bin/shift_ledger.py",
    "bin/sync_feedback.py",
    "bin/workspace_instructions.py",
    "board/_board.py",
    "board/_publish.py",
]

HISTORY = re.compile(
    r"\b20\d\d-[01]\d-[0-3]\d\b"      # a date
    r"|\bM\d+\.\d+[a-z]?\b"            # a programme milestone tag (M1.3, M3.6j)
    r"|\bPyAuto[A-Za-z]+#\d+"          # an issue/PR reference
    r"|\bv[0-2]\b"                     # a roadmap version (v0, v1, v2)
)


@pytest.mark.parametrize("tool", TOOLS)
def test_help_names_no_history(tool):
    proc = subprocess.run(
        [sys.executable, str(ROOT / tool), "--help"],
        capture_output=True, text=True, timeout=60, cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip()
    hits = [m.group(0) for m in HISTORY.finditer(proc.stdout)]
    assert not hits, f"{tool} --help names {hits}"
