"""hygiene ci — the slowest parts of CI, read off the Heart board.

The board is a fixture here (schema v3 `performance` block, trimmed to the
fields the helper reads), so these tests never reach Pages. What they pin:

* one candidate per script — the python legs fold and the SLOWEST leg is the
  cost (both legs run in parallel, so the gate waits for the slower one);
* a `seconds: null` row never ran and is never a candidate (the Heart's own
  rule — a fabricated 0 s row in a timing dataset is worse than no row);
* levers are read from the script text when it is checked out under the scan
  root, and reported as unread (never guessed) when it is not;
* an unreachable board is exit 3 with the places looked, never a clean zero.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN_HOME = Path(__file__).resolve().parents[1]
HYGIENE = BRAIN_HOME / "agents" / "conductors" / "hygiene"
HELPER = HYGIENE / "_hygiene_ci.py"
SCRIPT = HYGIENE / "hygiene.sh"

sys.path.insert(0, str(HYGIENE))
import _hygiene_ci as ci  # noqa: E402


def _board():
    return {
        "ts": "2026-09-07T09:56:44+00:00",
        "verdict": "green",
        "performance": {
            "epoch": {"date": "2026-09-06", "label": "fast-tests"},
            "scripts": {
                "repos": [
                    {"repo": "ws_a", "python": "3.12", "total_s": 100.0},
                    {"repo": "ws_a", "python": "3.13", "total_s": 80.0},
                ],
                "rows": [
                    {"repo": "ws_a", "entry": "scripts/slow.py", "python": "3.12", "seconds": 40.0,
                     "cap_s": 300.0, "cache_jax": "miss", "run_url": "https://x/1", "status": "passed"},
                    {"repo": "ws_a", "entry": "scripts/slow.py", "python": "3.13", "seconds": 55.0,
                     "cap_s": 300.0, "cache_jax": "hit", "run_url": "https://x/2", "status": "passed"},
                    {"repo": "ws_a", "entry": "scripts/quick.py", "python": "3.12", "seconds": 3.0},
                    {"repo": "ws_a", "entry": "scripts/never_ran.py", "python": "3.12", "seconds": None},
                ],
                "slowed": [],
            },
            "unit": {
                "tests": [
                    {"repo": "lib", "nodeid": "t/test_a.py::test_x", "python": "3.12", "seconds": 9.0,
                     "ratio": 1.5, "run_url": "https://x/u"},
                    {"repo": "lib", "nodeid": "t/test_a.py::test_x", "python": "3.13", "seconds": 7.0},
                    {"repo": "lib", "nodeid": "t/test_b.py::test_y", "python": "3.12", "seconds": 1.0},
                ],
                "slowed_tests": [{"nodeid": "t/test_a.py::test_x"}],
            },
            "gates": [
                {"repo": "lib", "workflow": "Tests", "median_s": 200.0, "max_s": 300.0,
                 "runs_counted": 10, "state": "ok", "actions_url": "https://x/a"},
                {"repo": "ws_a", "workflow": "Smoke Tests", "median_s": 600.0, "max_s": 900.0,
                 "runs_counted": 12, "state": "ok", "actions_url": "https://x/b"},
            ],
            "events": [],
        },
    }


def test_scripts_fold_python_legs_and_keep_the_slowest():
    items = ci.rank_scripts(_board()["performance"])
    assert [i["entry"] for i in items] == ["scripts/slow.py", "scripts/quick.py"]
    slow = items[0]
    assert slow["seconds"] == 55.0 and slow["python"] == "3.13"
    assert slow["legs"] == {"3.12": 40.0, "3.13": 55.0}
    # the share is of the SLOWEST leg's total, and the cache state travels with that leg
    assert slow["share_of_leg"] == pytest.approx(55.0 / 80.0, abs=1e-3)
    assert slow["cache_jax"] == "hit" and slow["run_url"] == "https://x/2"


def test_null_seconds_row_is_never_a_candidate():
    items = ci.rank_scripts(_board()["performance"])
    assert all(i["entry"] != "scripts/never_ran.py" for i in items)


def test_tests_and_gates_rank_by_seconds():
    perf = _board()["performance"]
    tests = ci.rank_tests(perf)
    assert tests[0]["entry"] == "t/test_a.py::test_x" and tests[0]["seconds"] == 9.0
    assert tests[0]["ratio"] == 1.5
    gates = ci.rank_gates(perf)
    assert [g["entry"] for g in gates] == ["Smoke Tests", "Tests"]


def test_levers_are_read_from_the_script_text():
    text = '''"""
Doc.

__Env__
ENV: jax full_datasets
"""
import os, subprocess
N = int(os.environ.get("MY_SAMPLES", "75"))
if al.util.dataset.should_simulate(p):
    subprocess.run([sys.executable, "sim.py"], check=True)
f = jax.jit(g)
aplt.subplot(x)
'''
    levers = {l["lever"]: l for l in ci.levers_from_text(text)}
    assert set(levers) == {"env_knob", "simulates", "jax_jit", "full_datasets", "subprocess", "plots"}
    assert "MY_SAMPLES (default 75)" == levers["env_knob"]["detail"]
    assert "real_search" not in levers


def test_real_output_token_releases_every_var():
    levers = {l["lever"] for l in ci.levers_from_text('"""\n__Env__\nENV: real_output\n"""\n')}
    assert {"jax_jit", "full_datasets", "real_search"} <= levers


def test_attach_levers_marks_unread_when_script_absent(tmp_path):
    root = tmp_path / "root"
    (root / "ws_a" / "scripts").mkdir(parents=True)
    (root / "ws_a" / "scripts" / "slow.py").write_text(
        'import os\nN = int(os.environ.get("KNOB", "10"))\n', encoding="utf-8")
    items = ci.rank_scripts(_board()["performance"])
    ci.attach_levers(items, root)
    by = {i["entry"]: i for i in items}
    assert by["scripts/slow.py"]["levers"][0]["lever"] == "env_knob"
    assert by["scripts/quick.py"]["script_path"] is None
    assert by["scripts/quick.py"]["levers"] == []


def test_build_emits_a_prompt_per_item_and_counts():
    decision = ci.build(_board(), top=1, lane="all", scripts_root=None)
    assert decision["decision"] == "HygieneDecision" and decision["mode"] == "ci"
    assert decision["counts"] == {"scripts_timed": 3, "tests": 3, "gates": 2,
                                  "slowed_scripts": 0, "slowed_tests": 1, "hang_events": 0}
    for lane in ("scripts", "tests", "gates"):
        assert len(decision["lanes"][lane]) == 1
        assert decision["lanes"][lane][0]["prompt"].startswith("/ci_speedup ")
    assert "55.0s on py3.13" in decision["lanes"]["scripts"][0]["prompt"]


def _run(args, env_extra, cwd=None):
    env = os.environ | env_extra
    return subprocess.run([str(SCRIPT), *args], capture_output=True, text=True, env=env, cwd=cwd)


def test_conductor_ci_mode_round_trips_json(tmp_path):
    board = tmp_path / "board.json"
    board.write_text(json.dumps(_board()), encoding="utf-8")
    r = _run(["ci", "--top", "1", "--lane", "scripts", "--json"],
             {"HYGIENE_HEART_BOARD": str(board), "PYAUTO_ROOT": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["mode"] == "ci" and list(d["lanes"]) == ["scripts"]
    assert d["lanes"]["scripts"][0]["entry"] == "scripts/slow.py"
    assert d["source"] == str(board)


def test_conductor_ci_mode_human_output_names_the_delegate(tmp_path):
    board = tmp_path / "board.json"
    board.write_text(json.dumps(_board()), encoding="utf-8")
    r = _run(["ci", "--top", "2"], {"HYGIENE_HEART_BOARD": str(board), "PYAUTO_ROOT": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    assert "HygieneDecision (ci" in r.stdout
    assert "/ci_speedup ws_a scripts/slow.py" in r.stdout
    assert "levers unread" in r.stdout


def test_unreachable_board_is_exit_3_not_a_clean_zero(tmp_path):
    r = subprocess.run([sys.executable, str(HELPER), "--board", str(tmp_path / "missing.json"), "--json"],
                       capture_output=True, text=True,
                       env=os.environ | {"HYGIENE_HEART_BOARD": str(tmp_path / "also_missing.json"),
                                         "PYAUTO_ROOT": str(tmp_path), "PYAUTO_MIND": str(tmp_path)})
    assert r.returncode == 3
    d = json.loads(r.stdout)
    assert d["status"] == "unreachable" and str(tmp_path / "missing.json") in d["tried"]
    # no body map under PYAUTO_MIND → no Pages URL can be derived, and none is invented
    assert not any(t.startswith("http") for t in d["tried"])
