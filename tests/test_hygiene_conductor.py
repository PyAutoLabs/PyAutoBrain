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
    "packaging", "docstrings", "refs", "optdeps", "extras",
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
    # Every pre-scan mode carries its kind; perf's timing is deferred in the
    # fast default scan (it spawns real imports).
    kinds = {row["mode"]: row.get("kind") for row in doc["rows"]}
    assert kinds["tidy"] == "debris"
    assert kinds["crlf"] == "debris" and kinds["artifacts"] == "debris"
    assert kinds["packaging"] == "debris"
    assert kinds["docstrings"] == "finding"
    assert kinds["refs"] == "finding"
    assert kinds["optdeps"] == "finding"
    assert kinds["extras"] == "finding"
    assert kinds["deps"] == "surface" and kinds["docs"] == "surface"
    assert kinds["config"] == "surface"
    assert kinds["noise"] == "advisory"
    perf = next(row for row in doc["rows"] if row["mode"] == "perf")
    assert perf["status"] == "deferred"
    # Nothing is staged any more — all modes are live.
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


def _write_docstring_fixture(root):
    script = root / "demo_workspace" / "scripts" / "cases.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "\n".join(
            [
                '\"\"\"π first\"\"\"',
                "",
                "'''second'''",
                '\"\"\"third\"\"\"',
                'assigned = "ordinary string"',
                '"ordinary expression"',
                '\"\"\"after ordinary expression\"\"\"',
                "separator_one = 1",
                '\"\"\"before comment\"\"\"',
                "# comments are not whitespace",
                '\"\"\"after comment\"\"\"',
                "separator_two = 2",
                '\"\"\"inline one\"\"\"; \"\"\"inline two\"\"\"',
                "def function():",
                '    \"\"\"nested one\"\"\"',
                '    \"\"\"nested two\"\"\"',
                "class Example:",
                '    \"\"\"nested class one\"\"\"',
                '    \"\"\"nested class two\"\"\"',
                "",
            ]
        )
    )
    return script


def test_docstrings_reports_only_adjacent_top_level_triple_quoted_blocks(tmp_path):
    _write_docstring_fixture(tmp_path)

    result = _run(["docstrings", "--json"], tmp_path)

    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)["row"]
    assert row["kind"] == "finding"
    assert row["status"] == "finding"
    assert row["count"] == 2
    assert row["delegate"] == "/refactor"
    assert row["parse_errors"] == []
    assert [
        (finding["first_end_line"], finding["second_line"])
        for finding in row["findings"]
    ] == [(1, 3), (3, 4)]


def test_docstrings_includes_root_level_entry_scripts(tmp_path):
    scripts = tmp_path / "demo_workspace" / "scripts"
    scripts.mkdir(parents=True)
    entry_script = tmp_path / "demo_workspace" / "start_here.py"
    entry_script.write_text('"""first"""\n\n"""second"""\n')

    result = _run(["docstrings", "--json"], tmp_path)

    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)["row"]
    assert row["count"] == 1
    assert row["findings"][0]["file"] == "start_here.py"
    assert row["findings"][0]["first_end_line"] == 1
    assert row["findings"][0]["second_line"] == 3


def test_docstrings_human_output_includes_exact_locations(tmp_path):
    _write_docstring_fixture(tmp_path)

    result = _run(["docstrings"], tmp_path)

    assert result.returncode == 0, result.stderr
    assert "2 adjacent documentation boundaries in 1 file" in result.stdout
    assert "demo_workspace/scripts/cases.py:1 -> 3" in result.stdout
    assert "demo_workspace/scripts/cases.py:3 -> 4" in result.stdout
    assert "route the mechanical merges to /refactor" in result.stdout


def test_default_json_includes_docstring_finding_locations(tmp_path):
    _write_docstring_fixture(tmp_path)

    result = _run(["--json"], tmp_path)

    assert result.returncode == 0, result.stderr
    rows = {row["mode"]: row for row in json.loads(result.stdout)["rows"]}
    assert rows["docstrings"]["count"] == 2
    assert len(rows["docstrings"]["findings"]) == 2


def test_default_human_worklist_ranks_docstring_findings(tmp_path):
    _write_docstring_fixture(tmp_path)

    result = _run([], tmp_path)

    assert result.returncode == 0, result.stderr
    assert "docstrings 2 findings" in result.stdout
    assert "Recommended next: hygiene docstrings (2 items)" in result.stdout
    assert "route exact findings to /refactor" in result.stdout


def test_docstrings_parse_errors_keep_json_valid_and_mark_scan_partial(tmp_path):
    script = tmp_path / "HowToBroken" / "scripts" / "broken.py"
    script.parent.mkdir(parents=True)
    script.write_text("if True print('broken')\n")

    result = _run(["docstrings", "--json"], tmp_path)

    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)["row"]
    assert row["status"] == "partial"
    assert row["count"] == 0
    assert row["findings"] == []
    assert row["parse_errors"][0]["repo"] == "HowToBroken"
    assert row["parse_errors"][0]["file"] == "scripts/broken.py"


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


# --- config --detail: the routable view of both signals. ----------------------
# The count alone cannot be routed to /refactor — these lock the fact that the
# key paths and orphan paths are printed, AND that asking for them never moves
# the default `count|summary` line the conductor's summary table parses.

CONFIG_HELPER = (
    BRAIN_HOME / "agents" / "conductors" / "hygiene" / "_hygiene_config.py"
)


def _run_config_helper(root, *args):
    _load_config_helper()  # skips (SystemExit) if PyYAML absent
    return subprocess.run(
        [sys.executable, str(CONFIG_HELPER), "--root", str(root), *args],
        capture_output=True, text=True,
    )


def _drifted_pair(root):
    """A real PAIRS pair (PyAutoFit <-> autofit_workspace) with nested and
    top-level key drift across two config files."""
    _fake_library(root, {
        "general.yaml": {"output": {"search_internal": 1}, "keep": 2},
        "logging.yaml": {"total_files_open": 1},
    })
    _fake_workspace(root, "autofit_workspace", {
        "general.yaml": {"output": {}, "keep": 2},   # missing output.search_internal
        "logging.yaml": {},                          # missing total_files_open
    })


def test_config_detail_groups_drifted_keys_under_the_file_missing_them(tmp_path):
    _drifted_pair(tmp_path)
    r = _run_config_helper(tmp_path, "--detail")
    assert r.returncode == 0, r.stderr
    # The key paths themselves — the thing the count could not hand over.
    assert "- output.search_internal" in r.stdout
    assert "- total_files_open" in r.stdout
    # ...each under the workspace file it is absent from, not a flat list.
    general = r.stdout.index("autofit_workspace/config/general.yaml")
    logging_ = r.stdout.index("autofit_workspace/config/logging.yaml")
    assert general < r.stdout.index("- output.search_internal") < logging_
    assert logging_ < r.stdout.index("- total_files_open")


def test_config_detail_groups_orphan_files_under_their_repo(tmp_path):
    """The orphan signal gets the same treatment, owner suppression intact."""
    _fake_library(tmp_path, {
        "general.yaml": {"a": 1},
        "non_linear/GridSearch.yaml": {"grid": 1},
    })
    _fake_workspace(tmp_path, "some_workspace", {
        "general.yaml": {"a": 1},                    # shared -> this IS a mirror
        "grids.yaml": {"radial_minimum": 1},         # orphan -> named
        "non_linear/nest.yaml": {"Nautilus": 1},     # orphan -> named
        "non_linear/GridSearch.yaml": {"grid": 1},   # mirrored -> absent
        "build/env_vars.yaml": {"X": 1},             # owned -> suppressed
    })
    r = _run_config_helper(tmp_path, "--detail")
    assert r.returncode == 0, r.stderr
    repo = r.stdout.index("some_workspace/config")
    assert repo < r.stdout.index("- grids.yaml")
    assert repo < r.stdout.index("- non_linear/nest.yaml")
    assert "GridSearch.yaml" not in r.stdout   # has a library counterpart
    assert "env_vars.yaml" not in r.stdout     # ORPHAN_OWNERS suppression


def test_config_default_output_is_still_one_count_summary_line(tmp_path):
    """The regression guard: `prescan_config` parses `${out%%|*}`, so adding
    --detail must not add a line, a prefix, or a newline to the default."""
    _drifted_pair(tmp_path)
    r = _run_config_helper(tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "2|2 library config keys absent downstream (review/mirror): "
        "autofit_workspace:2"
    ]


def test_config_detail_on_a_clean_tree_reports_in_sync_and_lists_nothing(tmp_path):
    r = _run_config_helper(tmp_path, "--detail")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "config in sync (no key drift or orphan files)"


def test_hygiene_config_mode_hands_over_the_drifted_key_paths(tmp_path):
    """The whole point: `hygiene config` must surface routable findings, not a
    tally the operator has to re-derive by importing the module."""
    _load_config_helper()  # skips (SystemExit) if PyYAML absent
    _drifted_pair(tmp_path)
    r = _run(["config"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "output.search_internal" in r.stdout
    assert "total_files_open" in r.stdout
    assert "/refactor" in r.stdout


def test_hygiene_config_json_row_is_unchanged_by_detail(tmp_path):
    """The machine surface keeps reading the count line, not the detail."""
    _load_config_helper()  # skips (SystemExit) if PyYAML absent
    _drifted_pair(tmp_path)
    r = _run(["config", "--json"], tmp_path)
    assert r.returncode == 0, r.stderr
    row = json.loads(r.stdout)["row"]
    assert row["mode"] == "config" and row["kind"] == "surface"
    assert row["count"] == 2
    assert "output.search_internal" not in row["summary"]


def test_help_lists_the_usage_block(tmp_path):
    r = _run(["--help"], tmp_path)
    assert r.returncode == 0
    assert "hygiene.sh" in r.stdout
    assert "--json" in r.stdout


def _write_optdeps_fixture(root):
    """
    A workspace with one script of each interesting kind:

      unguarded.py   smoke-listed, constructs a gated API, no guard  -> FLAG
      guarded.py     smoke-listed, constructs it, has the guard      -> clean
      loose.py       NOT smoke-listed, constructs it, no guard       -> ignored
      prose.py       smoke-listed, names it only in a doc block      -> ignored
    """
    ws = root / "autolens_workspace"
    (ws / "scripts").mkdir(parents=True)
    (ws / ".git").mkdir()
    (ws / "smoke_tests.txt").write_text("unguarded.py\nguarded.py\nprose.py\n")

    (ws / "scripts" / "unguarded.py").write_text(
        "import autolens as al\n"
        "d = al.Interferometer.from_fits(transformer_class=al.TransformerNUFFT)\n"
    )
    (ws / "scripts" / "guarded.py").write_text(
        "import importlib.util, sys\n"
        'if importlib.util.find_spec("nufftax") is None:\n'
        '    print("Skipping"); sys.exit(0)\n'
        "import autolens as al\n"
        "d = al.Interferometer.from_fits(transformer_class=al.TransformerNUFFT)\n"
    )
    (ws / "scripts" / "loose.py").write_text(
        "import autolens as al\nx = al.TransformerNUFFT\n"
    )
    (ws / "scripts" / "prose.py").write_text(
        '"""\nWe describe TransformerNUFFT here but never build it.\n"""\nx = 1\n'
    )
    return ws


def test_optdeps_flags_only_the_unguarded_smoke_listed_script(tmp_path):
    _write_optdeps_fixture(tmp_path)

    result = _run(["optdeps", "--json"], tmp_path)

    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)["row"]
    assert row["count"] == 1
    assert row["mode"] == "optdeps" and row["kind"] == "finding"
    assert [f["script"] for f in row["findings"]] == ["unguarded.py"]
    assert row["findings"][0]["dependency"] == "nufftax"


def test_optdeps_is_clean_when_every_smoke_listed_script_is_guarded(tmp_path):
    ws = _write_optdeps_fixture(tmp_path)
    (ws / "smoke_tests.txt").write_text("guarded.py\nprose.py\n")

    result = _run(["optdeps", "--json"], tmp_path)

    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)["row"]
    assert row["count"] == 0 and row["status"] == "clean"


def test_optdeps_findings_reach_the_default_worklist(tmp_path):
    _write_optdeps_fixture(tmp_path)

    result = _run([], tmp_path)

    assert result.returncode == 0, result.stderr
    assert "optdeps   1 findings" in result.stdout
    assert "route exact findings to /refactor" in result.stdout


_SMOKE_WORKFLOW = """\
jobs:
  run_scripts:
    steps:
      - name: "Install third-party deps (libs run from source) [mode=smoke]"
        if: needs.find_scripts.outputs.mode == 'smoke'
        run: |
          pip install "top-layer[optional]"
{extra_installs}\
      - name: "Install TestPyPI wheels [mode=release]"
        if: needs.find_scripts.outputs.mode == 'release'
        run: |
          pip install \\
            "base-layer[optional]==$V" \\
            "mid-layer[optional]==$V" \\
            "top-layer[optional]==$V"
"""

# Keyed by CHECKOUT DIRECTORY, deliberately named nothing like the distribution
# each one declares: the scan derives its library set from the [mode=release]
# install step above and resolves each name through `project.name`, so a folder
# name must not be able to influence the result. (Instance-free by the same
# rule the tenant firewall applies to organ code.)
_PYPROJECTS = {
    # the base layer; its [jax] extra is what the chain reaches.
    "checkout_a": """\
[project]
name = "base-layer"
dependencies = []
[project.optional-dependencies]
jax = ["jax>=0.7"]
optional = ["base-layer[jax]", "astropy>=5.0"]
""",
    # mid-layer declares an optional dep NO sibling's chain reaches — the drift.
    "checkout_b": """\
[project]
name = "mid-layer"
dependencies = ["base-layer"]
[project.optional-dependencies]
jax = ["base-layer[jax]"]
optional = ["mid-layer[jax]", "numba", "tfp-nightly==0.26.0.dev1"]
""",
    # top-layer[optional] chains to top-layer[jax] -> base-layer[jax]; it never
    # reaches mid-layer[optional], which is the whole point of the scan.
    "checkout_c": """\
[project]
name = "top-layer"
dependencies = ["mid-layer", "base-layer"]
[project.optional-dependencies]
jax = ["base-layer[jax]"]
optional = ["top-layer[jax]", "numba", "astropy>=5.0"]
""",
}


def _write_extras_fixture(root, extra_installs=""):
    """Library checkouts + a PyAutoHeart workflow whose smoke leg under-installs.

    `numba` is reachable from `top-layer[optional]`. `astropy` is declared
    optional by TWO libraries — base-layer (not reached) and top-layer (reached)
    — so it must NOT be flagged; only a dependency no reached extra supplies is
    drift. `tfp-nightly` is declared ONLY by `mid-layer[optional]`, which the
    chain never reaches -> FLAG.
    """
    for repo, body in _PYPROJECTS.items():
        (root / repo).mkdir(parents=True, exist_ok=True)
        (root / repo / "pyproject.toml").write_text(body)

    workflow = root / "PyAutoHeart" / ".github" / "workflows"
    workflow.mkdir(parents=True, exist_ok=True)
    (workflow / "workspace-validation.yml").write_text(
        _SMOKE_WORKFLOW.format(extra_installs=extra_installs)
    )
    return root


def test_extras_flags_an_optional_dep_the_smoke_leg_never_installs(tmp_path):
    _write_extras_fixture(tmp_path)

    result = _run(["extras", "--json"], tmp_path)

    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)["row"]
    assert row["count"] == 1
    assert row["mode"] == "extras" and row["kind"] == "finding"
    assert row["delegate"] == "/bug"
    finding = row["findings"][0]
    assert finding["dependency"] == "tfp-nightly"
    assert finding["declared_by"] == ["mid-layer[optional]"]
    # Named by the CHECKOUT the distribution was resolved to, not by any
    # assumption about what that folder is called.
    assert finding["repos"] == ["checkout_b"]


def test_extras_resolves_libraries_by_distribution_not_by_folder(tmp_path):
    # A checkout the [mode=release] step never installs is NOT a library, so its
    # unreachable optional dep is none of this scan's business — even though it
    # sits beside the real ones and declares the same shape of extra.
    _write_extras_fixture(tmp_path)
    outsider = tmp_path / "checkout_z"
    outsider.mkdir()
    (outsider / "pyproject.toml").write_text(
        '[project]\nname = "not-a-library"\ndependencies = []\n'
        '[project.optional-dependencies]\noptional = ["never-installed-pkg"]\n'
    )

    result = _run(["extras", "--json"], tmp_path)

    row = json.loads(result.stdout)["row"]
    assert [f["dependency"] for f in row["findings"]] == ["tfp-nightly"]


def test_extras_is_clean_once_the_declaring_extra_is_installed(tmp_path):
    # The house fix: install the declaring library's whole [optional] extra.
    _write_extras_fixture(
        tmp_path, extra_installs='          pip install "mid-layer[optional]"\n'
    )

    result = _run(["extras", "--json"], tmp_path)

    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)["row"]
    assert row["count"] == 0 and row["status"] == "clean"


def test_extras_is_clean_when_the_single_package_is_pinned_directly(tmp_path):
    # Pinning the one package also closes it (it just does not self-heal).
    _write_extras_fixture(
        tmp_path,
        extra_installs='          pip install "tfp-nightly==0.26.0.dev1"\n',
    )

    result = _run(["extras", "--json"], tmp_path)

    row = json.loads(result.stdout)["row"]
    assert row["count"] == 0 and row["status"] == "clean"


def test_extras_reports_not_scannable_without_the_workflow(tmp_path):
    # Library checkouts but no PyAutoHeart workflow: report nothing rather than
    # inventing findings — an absent workflow is not exposure drift.
    for repo, body in _PYPROJECTS.items():
        (tmp_path / repo).mkdir(parents=True, exist_ok=True)
        (tmp_path / repo / "pyproject.toml").write_text(body)

    result = _run(["extras", "--json"], tmp_path)

    row = json.loads(result.stdout)["row"]
    assert row["count"] == 0 and row["status"] == "clean"
    assert "not scannable" in row["summary"]


def test_extras_findings_reach_the_default_worklist(tmp_path):
    _write_extras_fixture(tmp_path)

    result = _run([], tmp_path)

    assert result.returncode == 0, result.stderr
    assert "extras    1 findings" in result.stdout
    assert "route the missing installs to /bug" in result.stdout


def _write_refs_fixture(root):
    """A workspace whose READMEs drift from its real tree.

    Real layout: scripts/{imaging/{data_preparation/,features/},guides/advanced/}
    plus config/{general.yaml,priors/}.
    """
    workspace = root / "demo_workspace"
    for folder in (
        "scripts/imaging/data_preparation",
        "scripts/imaging/features",
        "scripts/guides/advanced",
        "config/priors",
    ):
        (workspace / folder).mkdir(parents=True)
    (workspace / "scripts/imaging/modeling.py").write_text("x = 1\n")
    (workspace / "config/general.yaml").write_text("a: 1\n")

    # Root README: a structure list whose quorum holds, with two dead entries.
    (workspace / "README.md").write_text(
        "\n".join(
            [
                "# Demo",
                "",
                "- `scripts`: example scripts.",
                "- `config`: configuration files.",
                "- `slam_pipeline`: the SLaM pipelines.",
                "",
            ]
        )
    )
    # A parameter glossary — nothing resolves, so the whole block is skipped.
    (workspace / "scripts/imaging/README.md").write_text(
        "\n".join(
            [
                "- `intensity`: the brightness of the profile.",
                "- `effective_radius`: the half-light radius.",
                "- `sersic_index`: the concentration.",
                "",
            ]
        )
    )
    # Reversed relative path + a typo'd leading segment; `modeling` resolves via
    # the dropped-extension rule, and `bulge/disk` is prose, not a path.
    (workspace / "scripts/guides/advanced/README.md").write_text(
        "\n".join(
            [
                "The `data_preparation/imaging` folder prepares data.",
                "The `guide/advanced` folder holds guides.",
                "See `imaging/modeling` for the workflow.",
                "A `bulge/disk` decomposition is standard.",
                "Results land in `/hpc/data/username/output` on the cluster.",
                "",
            ]
        )
    )
    # Config inventory listing YAML that is no longer shipped.
    (workspace / "config/README.md").write_text(
        "\n".join(
            [
                "- `general.yaml`: general settings.",
                "- `mcmc.yaml`: MCMC settings.",
                "",
            ]
        )
    )
    return workspace


def _refs_row(tmp_path):
    result = _run(["refs", "--json"], tmp_path)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["row"]


def test_refs_reports_dead_structure_list_entries(tmp_path):
    _write_refs_fixture(tmp_path)

    found = {(f["file"], f["reference"]) for f in _refs_row(tmp_path)["findings"]}

    # `slam_pipeline` is dead; `scripts`/`config` resolve and form the quorum
    # that proves this block is a structure list rather than prose.
    assert ("README.md", "slam_pipeline") in found


def test_refs_skips_bullet_lists_that_are_not_structure_lists(tmp_path):
    _write_refs_fixture(tmp_path)

    found = {f["reference"] for f in _refs_row(tmp_path)["findings"]}

    # A parameter glossary: no name resolves, so the quorum is never met and the
    # whole block is skipped rather than reported as three dead references.
    assert {"intensity", "effective_radius", "sersic_index"}.isdisjoint(found)


def test_refs_reports_config_yaml_that_is_no_longer_shipped(tmp_path):
    _write_refs_fixture(tmp_path)

    found = {(f["file"], f["reference"]) for f in _refs_row(tmp_path)["findings"]}

    # An extension-bearing name bypasses the quorum — one dead entry beside one
    # live one is still a finding.
    assert ("config/README.md", "mcmc.yaml") in found
    assert ("config/README.md", "general.yaml") not in found


def test_refs_reports_slashless_directory_paths(tmp_path):
    _write_refs_fixture(tmp_path)

    found = {f["reference"] for f in _refs_row(tmp_path)["findings"]}

    # Reversed order (real path is imaging/data_preparation) and a typo'd head.
    assert "data_preparation/imaging" in found
    assert "guide/advanced" in found


def test_refs_suppresses_prose_slashes_and_absolute_paths(tmp_path):
    _write_refs_fixture(tmp_path)

    found = {f["reference"] for f in _refs_row(tmp_path)["findings"]}

    # `bulge/disk` is prose shorthand, not a path; an absolute cluster path can
    # never resolve against a checkout; `imaging/modeling` resolves through the
    # dropped-extension rule (the file is modeling.py).
    assert "bulge/disk" not in found
    assert "/hpc/data/username/output" not in found
    assert "imaging/modeling" not in found


def test_refs_resolves_dot_directory_references(tmp_path):
    workspace = tmp_path / "demo_workspace"
    (workspace / "scripts").mkdir(parents=True)
    (workspace / ".claude" / "skills").mkdir(parents=True)
    # `.github/` exists but holds no `workflows/`, so the reference below is
    # anchored (the guard will judge it) yet genuinely dead.
    (workspace / ".github").mkdir()
    (workspace / "README.md").write_text(
        "\n".join(
            [
                "- `scripts`: example scripts.",
                "See `.claude/skills` for agent skills and `.github/workflows` for CI.",
                "",
            ]
        )
    )

    found = {f["reference"] for f in _refs_row(tmp_path)["findings"]}

    # A leading dot must survive prefix-stripping. Before the fix, `lstrip("./")`
    # ate it: `.claude/skills` became `claude/skills` and was reported dead even
    # though it exists, and `.github/workflows` was reported under a mangled name.
    assert ".claude/skills" not in found
    assert ".github/workflows" in found
    assert "github/workflows" not in found
    assert "claude/skills" not in found


def test_refs_findings_reach_the_default_worklist(tmp_path):
    _write_refs_fixture(tmp_path)

    result = _run(["--json"], tmp_path)

    assert result.returncode == 0, result.stderr
    rows = {row["mode"]: row for row in json.loads(result.stdout)["rows"]}
    assert rows["refs"]["count"] == len(_refs_row(tmp_path)["findings"]) > 0


# --- Body-map-derived coverage -------------------------------------------------
#
# The conductor scans repositories, so WHICH repositories must come from the body
# map rather than from arrays in the script. It used to come from arrays, and they
# drifted: five libraries where the map declared six, four organs of seven, and a
# CRLF count of 5 against a true 127. Nothing caught it, because a repo that is
# never scanned produces no findings and reads as clean.
#
# These tests name no repository. That is deliberate on two counts: a literal here
# would be an instance fact in an organ test (the tenant firewall's concern), and
# a test that hardcodes the very list under test can only ever agree with itself.

HELPER = BRAIN_HOME / "agents" / "conductors" / "hygiene" / "_hygiene_repos.py"


def _derived(category, root=None, parser="auto", mind=None):
    env = {**os.environ}
    if root is not None:
        env["PYAUTO_ROOT"] = str(root)
    if mind is not None:
        env["PYAUTO_MIND"] = str(mind)
    result = subprocess.run(
        [sys.executable, str(HELPER), "--category", category, "--parser", parser],
        capture_output=True, text=True, env=env,
    )
    return result, [line for line in result.stdout.splitlines() if line.strip()]


def _manifest_categories():
    """The declared sets, read straight from the body map."""
    import yaml

    path = BRAIN_HOME.parent / "PyAutoMind" / "repos.yaml"
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text())
    grouped = {}
    for name, entry in data["repos"].items():
        grouped.setdefault(entry["category"], set()).add(name)
    return grouped


def test_derived_repo_sets_equal_the_body_map(tmp_path):
    declared = _manifest_categories()
    if declared is None:
        return  # body map not checked out here; the drift check owns this leg
    for category in ("library", "organ", "workspace"):
        result, names = _derived(category, tmp_path)
        assert result.returncode == 0, result.stderr
        assert set(names) == declared[category], category


def test_the_pyyaml_free_reader_agrees_with_the_body_map(tmp_path):
    # The fallback runs only where PyYAML is absent, so nothing else would ever
    # catch it silently dropping a repo — the exact shape of the original bug.
    declared = _manifest_categories()
    if declared is None:
        return
    for category in ("library", "organ", "workspace"):
        result, names = _derived(category, tmp_path, parser="minimal")
        assert result.returncode == 0, result.stderr
        assert set(names) == declared[category], category


def test_crlf_covers_every_library_the_body_map_declares(tmp_path):
    # One checkout per declared library, each with a single CRLF .py. The count
    # must equal the number of libraries: any repo the conductor fails to derive
    # is one this assertion misses. No library is named here — that is the point.
    _, libraries = _derived("library", tmp_path)
    assert libraries, "body map returned no libraries"
    for name in libraries:
        repo = tmp_path / name
        _init_git_repo(repo)
        (repo / "mod.py").write_bytes(b"x = 1\r\ny = 2\r\n")
        subprocess.run(["git", "-C", str(repo), "add", "-f", "mod.py"], check=True)

    row = json.loads(_run(["crlf", "--json"], tmp_path).stdout)["row"]

    assert row["status"] != "unscanned"
    assert f"{len(libraries)} .py w/ CRLF" in row["summary"]


ARRAY_MODES = {"tidy", "crlf", "artifacts", "deps", "docs", "packaging"}


def test_repo_array_modes_report_unscanned_not_clean_on_an_empty_root(tmp_path):
    # A zero from "nothing was scanned" and a zero from "nothing was wrong" are
    # indistinguishable to a consumer, so the first must not be called `clean`.
    rows = {row["mode"]: row for row in json.loads(_run(["--json"], tmp_path).stdout)["rows"]}

    for mode in ARRAY_MODES:
        assert rows[mode]["status"] == "unscanned", mode
        assert rows[mode]["count"] is None, mode
        assert rows[mode]["repos_present"] == 0, mode
        assert "no managed checkouts" in rows[mode]["reason"], mode


def test_an_empty_root_is_reported_in_the_default_envelope_and_banner(tmp_path):
    doc = json.loads(_run(["--json"], tmp_path).stdout)
    assert doc["repos_present"] == 0
    assert doc["repos_declared"] > 0
    assert "no managed checkouts" in doc["unscanned_reason"]

    human = _run([], tmp_path).stdout
    assert "SCANNED 0 REPOS" in human
    assert "NOT a clean bill of health" in human


def test_helper_backed_modes_still_report_findings_on_an_empty_root(tmp_path):
    # docstrings/refs/optdeps/extras discover their own targets by walking the
    # root, so they can legitimately find material the body map never names.
    # Suppressing them alongside the repo-array modes would hide real findings.
    _write_docstring_fixture(tmp_path)

    rows = {row["mode"]: row for row in json.loads(_run(["--json"], tmp_path).stdout)["rows"]}

    assert rows["docstrings"]["status"] != "unscanned"
    assert rows["docstrings"]["count"] > 0
    assert "Recommended next: hygiene docstrings" in _run([], tmp_path).stdout


def test_an_unreachable_body_map_reports_unscanned_rather_than_clean(tmp_path):
    # Pointed at a directory holding no body map: the conductor knows of no
    # repository at all, which must not read as a clean organism.
    mind = tmp_path / "no-map"
    mind.mkdir()
    root = tmp_path / "root"
    root.mkdir()

    result = subprocess.run(
        [str(BRAIN), "hygiene", "crlf", "--json"],
        capture_output=True, text=True,
        env={**os.environ, "PYAUTO_ROOT": str(root), "PYAUTO_MIND": str(mind)},
    )

    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)["row"]
    assert row["status"] == "unscanned"
    assert "body map unreachable" in row["reason"]


def test_an_explicit_body_map_override_is_authoritative(tmp_path):
    # Falling through to a sibling checkout would scan a different organism than
    # the operator named, and silently.
    mind = tmp_path / "no-map"
    mind.mkdir()

    result, names = _derived("library", tmp_path, mind=mind)

    assert result.returncode == 3
    assert names == []
