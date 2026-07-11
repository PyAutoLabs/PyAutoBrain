"""Contract tests for the hygiene conductor's CLI footing.

Hermetic: PYAUTO_ROOT points at an empty temp dir so the read-only pre-scans
return zero/empty signals — the JSON *structure* and exit codes are asserted
without depending on the state of the real checkouts.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
BRAIN = BRAIN_HOME / "bin" / "pyauto-brain"
MODES = {"perf", "tidy", "noise", "deps", "docs"}

_PROFILE_TARGET = """
def my_hot_function():
    s = 0
    for i in range(400000):
        s += i
    return s

def log_likelihood_function():
    s = 0
    for i in range(600000):
        s += i * i
    return s

def top():
    my_hot_function()
    log_likelihood_function()

top()
"""


def _run(args, root, extra=None):
    env = {**os.environ, "PYAUTO_ROOT": str(root)}
    if extra:
        env.update(extra)
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
    # the four pre-scan modes carry their kind; perf's timing is deferred in the
    # fast default scan (it spawns real imports).
    kinds = {row["mode"]: row.get("kind") for row in doc["rows"]}
    assert kinds["tidy"] == "debris"
    assert kinds["deps"] == "surface" and kinds["docs"] == "surface"
    assert kinds["noise"] == "advisory"
    perf = next(row for row in doc["rows"] if row["mode"] == "perf")
    assert perf["status"] == "deferred"
    # nothing is staged any more — all five modes are live.
    assert all(row.get("status") != "staged" for row in doc["rows"])


def test_single_mode_json_round_trips(tmp_path):
    for mode in MODES - {"perf"}:
        r = _run([mode, "--json"], tmp_path)
        assert r.returncode == 0, r.stderr
        doc = json.loads(r.stdout)
        assert doc["mode"] == mode
        assert doc["row"]["mode"] == mode
        assert doc["row"]["delegate"].startswith("/")


def _no_heart(tmp_path):
    # Point HEART_STATE_DIR at an empty dir so perf falls back to its own
    # subprocess timing instead of reading a real ~/.pyauto-heart import_time leg.
    return str(tmp_path / "noheart")


def test_perf_times_imports_in_a_subprocess(tmp_path):
    # Fast stdlib modules keep the test hermetic + quick; the point is the row
    # shape, not the science libs (which need the PyAuto venv).
    r = _run(["perf", "--json"], tmp_path,
             extra={"HYGIENE_PERF_LIBS": "sys json", "HEART_STATE_DIR": _no_heart(tmp_path)})
    assert r.returncode == 0, r.stderr
    row = json.loads(r.stdout)["row"]
    assert row["mode"] == "perf"
    assert row["kind"] == "timing"
    assert row["delegate"] == "/refactor"
    assert row["status"] in {"clean", "timing"}  # sys/json import well under threshold


def test_perf_advisory_when_nothing_importable(tmp_path):
    r = _run(["perf", "--json"], tmp_path,
             extra={"HYGIENE_PERF_LIBS": "nope_not_a_module_xyz", "HEART_STATE_DIR": _no_heart(tmp_path)})
    assert r.returncode == 0, r.stderr
    row = json.loads(r.stdout)["row"]
    assert row["status"] == "advisory" and row["count"] is None


def test_perf_prefers_heart_timing_legs_when_present(tmp_path):
    # When a Heart dev-loop timing leg has produced a reading, perf surfaces the
    # tracked baseline/regression view instead of its own one-shot timing.
    heart = tmp_path / "heart"
    heart.mkdir()
    (heart / "import_time.json").write_text(json.dumps({"red_count": 1, "yellow_count": 1}))
    r = _run(["perf", "--json"], tmp_path, extra={"HEART_STATE_DIR": str(heart)})
    assert r.returncode == 0, r.stderr
    row = json.loads(r.stdout)["row"]
    assert row["mode"] == "perf" and row["kind"] == "timing"
    assert row["count"] == 2  # red + yellow regressions
    assert "import_time" in row["summary"]


def test_perf_aggregates_multiple_heart_timing_legs(tmp_path):
    heart = tmp_path / "heart"
    heart.mkdir()
    (heart / "import_time.json").write_text(json.dumps({"red_count": 1, "yellow_count": 1}))
    (heart / "unit_test_timing.json").write_text(json.dumps({"red_count": 2, "yellow_count": 0}))
    r = _run(["perf", "--json"], tmp_path, extra={"HEART_STATE_DIR": str(heart)})
    row = json.loads(r.stdout)["row"]
    assert row["count"] == 4  # 2 + 2 regressions across both legs
    assert "import_time" in row["summary"] and "unit_test_timing" in row["summary"]


def test_unknown_mode_exits_2(tmp_path):
    r = _run(["bogus"], tmp_path)
    assert r.returncode == 2
    assert "unknown argument" in r.stderr


def test_profile_missing_script_exits_2(tmp_path):
    r = _run(["perf", "--profile", str(tmp_path / "nope.py")], tmp_path)
    assert r.returncode == 2


def test_profile_needs_a_script_arg(tmp_path):
    r = _run(["perf", "--profile"], tmp_path)
    assert r.returncode == 2


def test_profile_ranks_nonlikelihood_and_excludes_likelihood(tmp_path):
    # A real cProfile run of a tiny normal-mode script: the likelihood entry
    # point must be excluded; the ordinary hot function must be surfaced.
    script = tmp_path / "prof_target.py"
    script.write_text(_PROFILE_TARGET)
    r = _run(["perf", "--profile", str(script), "--json"], tmp_path,
             extra={"HYGIENE_PYTHON": sys.executable})
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["mode"] == "perf-profile" and doc["delegate"] == "/refactor"
    names = [c["function"] for c in doc["candidates"]]
    assert "my_hot_function" in names
    assert "log_likelihood_function" not in names


def test_help_lists_the_usage_block(tmp_path):
    r = _run(["--help"], tmp_path)
    assert r.returncode == 0
    assert "hygiene.sh" in r.stdout
    assert "--json" in r.stdout
