"""Contract tests for the hygiene conductor's CLI footing.

Hermetic: PYAUTO_ROOT points at an empty temp dir so the read-only pre-scans
return zero/empty signals — the JSON *structure* and exit codes are asserted
without depending on the state of the real checkouts.
"""

import json
import os
import subprocess
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
BRAIN = BRAIN_HOME / "bin" / "pyauto-brain"
MODES = {"perf", "tidy", "noise", "deps", "docs"}


def _run(args, root):
    env = {**os.environ, "PYAUTO_ROOT": str(root)}
    return subprocess.run(
        [str(BRAIN), "hygiene", *args],
        capture_output=True, text=True, env=env,
    )


def test_default_json_is_a_hygiene_decision_with_all_modes(tmp_path):
    r = _run(["--json"], tmp_path)
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["decision"] == "HygieneDecision"
    assert doc["mode"] == "default"
    assert {row["mode"] for row in doc["rows"]} == MODES
    # perf is staged; the other four carry a pre-scan kind.
    kinds = {row["mode"]: row.get("kind") for row in doc["rows"]}
    assert kinds["tidy"] == "debris"
    assert kinds["deps"] == "surface" and kinds["docs"] == "surface"
    assert kinds["noise"] == "advisory"


def test_single_mode_json_round_trips(tmp_path):
    for mode in MODES - {"perf"}:
        r = _run([mode, "--json"], tmp_path)
        assert r.returncode == 0, r.stderr
        doc = json.loads(r.stdout)
        assert doc["mode"] == mode
        assert doc["row"]["mode"] == mode
        assert doc["row"]["delegate"].startswith("/")


def test_unknown_mode_exits_2(tmp_path):
    r = _run(["bogus"], tmp_path)
    assert r.returncode == 2
    assert "unknown argument" in r.stderr


def test_help_lists_the_usage_block(tmp_path):
    r = _run(["--help"], tmp_path)
    assert r.returncode == 0
    assert "hygiene.sh" in r.stdout
    assert "--json" in r.stdout
