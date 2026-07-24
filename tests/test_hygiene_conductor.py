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
MODES = {
    "perf", "tidy", "noise", "deps", "docs", "crlf", "config", "artifacts",
    "packaging",
}

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
    assert kinds["crlf"] == "debris" and kinds["artifacts"] == "debris"
    assert kinds["packaging"] == "debris"
    assert kinds["deps"] == "surface" and kinds["docs"] == "surface"
    assert kinds["config"] == "surface"
    assert kinds["noise"] == "advisory"
    perf = next(row for row in doc["rows"] if row["mode"] == "perf")
    assert perf["status"] == "deferred"
    # nothing is staged any more — all five modes are live.
    assert all(row.get("status") != "staged" for row in doc["rows"])


def test_single_mode_json_round_trips(tmp_path):
    # perf defers (own test); tidy is now an action mode (the PyAutoGut condemn
    # plan, its own test), not a generic delegating scan-row.
    for mode in MODES - {"perf", "tidy"}:
        r = _run([mode, "--json"], tmp_path)
        assert r.returncode == 0, r.stderr
        doc = json.loads(r.stdout)
        assert doc["mode"] == mode
        assert doc["row"]["mode"] == mode
        if mode == "packaging":
            assert doc["row"]["delegate"].endswith("bin/clean_slate.sh --packaging")
        else:
            assert doc["row"]["delegate"].startswith("/")


def _init_git_repo(path):
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def test_packaging_finds_only_ignored_untracked_root_products(tmp_path):
    galaxy = tmp_path / "PyAutoGalaxy"
    _init_git_repo(galaxy)
    (galaxy / ".gitignore").write_text("*.egg-info/\nbuild/\n")
    (galaxy / "autogalaxy.egg-info").mkdir()
    (galaxy / "build").mkdir()
    (galaxy / "src" / "build").mkdir(parents=True)  # nested: out of scope

    fit = tmp_path / "PyAutoFit"
    _init_git_repo(fit)
    (fit / ".gitignore").write_text("build/\n")
    (fit / "build").mkdir()
    (fit / "build" / "tracked.txt").write_text("keep")
    subprocess.run(
        ["git", "-C", str(fit), "add", "-f", "build/tracked.txt"], check=True
    )

    array = tmp_path / "PyAutoArray"
    _init_git_repo(array)
    (array / "autoarray.egg-info").mkdir()  # not ignored: out of scope

    r = _run(["packaging", "--json"], tmp_path)
    assert r.returncode == 0, r.stderr
    row = json.loads(r.stdout)["row"]
    assert row["count"] == 2
    assert "PyAutoGalaxy:2" in row["summary"]
    assert "PyAutoFit" not in row["summary"]


def test_tidy_emits_an_async_condemn_plan(tmp_path):
    # tidy drives PyAutoGut: with an empty root there are no candidates, but the
    # plan's structure (the condemn contract) is asserted.
    r = _run(["tidy", "--json"], tmp_path)
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["decision"] == "HygieneDecision"
    assert doc["mode"] == "tidy" and doc["action"] == "condemn"
    assert doc["candidates"] == []
    assert "transit_days" in doc and "sweep_after" in doc


def test_sweep_classifies_manifest_entries_by_transit_clock(tmp_path):
    mind = tmp_path / "PyAutoMind"
    mind.mkdir()
    (mind / "condemned.md").write_text(
        "# Condemned material\n"
        "## due-one\n- type: branch\n- locator: feature/old\n- sweep-after: 2000-01-01\n"
        "## pending-one\n- type: stash\n- locator: stash@{0}\n- sweep-after: 2999-12-31\n"
        "<!-- ## ignored\n- type: branch\n- locator: feature/example -->\n"
    )
    r = _run(["sweep", "--json"], tmp_path, extra={"PYAUTO_MIND": str(mind)})
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["total"] == 2  # the HTML-commented example is excluded
    assert [e["name"] for e in doc["due"]] == ["due-one"]
    assert [e["name"] for e in doc["pending"]] == ["pending-one"]


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


def _load_config_helper():
    import importlib.util
    path = BRAIN_HOME / "agents" / "conductors" / "hygiene" / "_hygiene_config.py"
    spec = importlib.util.spec_from_file_location("_hygiene_config", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_config_helper_recursive_key_diff(tmp_path):
    cfg = _load_config_helper()  # skips (SystemExit) if PyYAML absent
    import yaml
    lib = tmp_path / "lib" / "config"; ws = tmp_path / "ws" / "config"
    lib.mkdir(parents=True); ws.mkdir(parents=True)
    # library adds a nested key + a top-level key the workspace lacks.
    (lib / "general.yaml").write_text(yaml.safe_dump(
        {"a": {"x": 1, "y": 2}, "b": 3, "c": 4}))
    (ws / "general.yaml").write_text(yaml.safe_dump(
        {"a": {"x": 1}, "b": 3}))  # missing a.y and c
    total, detail = cfg.diff(str(tmp_path), pairs=[("lib/config", "ws/config")])
    assert total == 2  # 'a.y' and 'c'


def _fake_library(root, files):
    """Write a fake PyAutoFit library config tree under `root`; `files` maps a
    config-relative path to a trivial mapping."""
    import yaml
    for rel, data in files.items():
        p = root / "PyAutoFit" / "autofit" / "config" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(data))


def _fake_workspace(root, name, files):
    import yaml
    for rel, data in files.items():
        p = root / name / "config" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(data))


def test_orphan_files_flags_unmirrored_and_suppresses_owned(tmp_path):
    """The core reachability contract: a workspace config file with no library
    counterpart is an orphan (flagged), UNLESS it lives under an owned subtree
    (build/, priors/). This is the grids.yaml / non_linear regression: the
    library ships non_linear/GridSearch.yaml (kept) but not nest.yaml (flagged).
    """
    cfg = _load_config_helper()
    _fake_library(tmp_path, {
        "general.yaml": {"a": 1},
        "non_linear/GridSearch.yaml": {"grid": 1},  # the LIVE non_linear file
    })
    _fake_workspace(tmp_path, "some_workspace", {
        "general.yaml": {"a": 1},                    # shared -> this IS a mirror
        "grids.yaml": {"radial_minimum": 1},         # orphan  -> FLAG (the 2025 bug)
        "non_linear/nest.yaml": {"Nautilus": 1},     # orphan  -> FLAG (dead)
        "non_linear/GridSearch.yaml": {"grid": 1},   # mirrored -> keep (live)
        "build/env_vars.yaml": {"X": 1},             # owned by Hands -> suppress
        "priors/MyClass.yaml": {"p": 1},             # user class prior -> suppress
    })
    total, detail = cfg.orphan_files(str(tmp_path))
    assert total == 2, detail                        # grids.yaml + non_linear/nest.yaml
    assert detail == ["some_workspace:2"]


def test_orphan_files_skips_non_mirror_repos(tmp_path):
    """A repo whose config/ shares nothing with the library set (an organ repo
    like Brain/Heart with its own config) is not a mirror and is not scanned —
    so its own files are never mis-flagged as orphans."""
    cfg = _load_config_helper()
    _fake_library(tmp_path, {"general.yaml": {"a": 1}})
    _fake_workspace(tmp_path, "some_organ", {
        "policy.yaml": {"own": 1},     # nothing shared with the library set
        "internal.yaml": {"own": 2},
    })
    total, detail = cfg.orphan_files(str(tmp_path))
    assert total == 0 and detail == []


def test_help_lists_the_usage_block(tmp_path):
    r = _run(["--help"], tmp_path)
    assert r.returncode == 0
    assert "hygiene.sh" in r.stdout
    assert "--json" in r.stdout
