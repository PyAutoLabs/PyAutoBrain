"""_hygiene_extras.py degrades to a "skipped" row without tomllib (PyAutoBrain#581).

`tomllib` is Python >= 3.11, and a bare `python3` can be older (3.10 on the WSL
laptop), where the extras mode used to die with ModuleNotFoundError. CI runs
3.12+, so the old-interpreter path is simulated by blocking both `tomllib` and
its `tomli` fallback before the helper is imported.
"""

import json
import subprocess
import sys
from pathlib import Path

HELPER = (
    Path(__file__).resolve().parents[1]
    / "agents" / "conductors" / "hygiene" / "_hygiene_extras.py"
)

_BLOCK = """
import importlib.abc, runpy, sys
class _Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name in ("tomllib", "tomli"):
            raise ModuleNotFoundError(name)
sys.modules.pop("tomllib", None)
sys.meta_path.insert(0, _Block())
sys.argv = [sys.argv[1]] + sys.argv[2:]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


def _run(tmp_path, *flags):
    return subprocess.run(
        [sys.executable, "-c", _BLOCK, str(HELPER), "--root", str(tmp_path), *flags],
        capture_output=True,
        text=True,
    )


def test_json_row_without_tomllib_is_an_error_row_not_a_traceback(tmp_path):
    result = _run(tmp_path, "--json-row")
    # runpy re-raises SystemExit(0) from main(); a traceback would mean the import crashed.
    assert "Traceback" not in result.stderr, result.stderr
    row = json.loads(result.stdout)
    assert row["mode"] == "extras"
    assert row["status"] == "error"
    assert row["count"] is None
    assert "Python >= 3.11" in row["summary"]


def test_summary_without_tomllib_renders_advisory_not_clean(tmp_path):
    result = _run(tmp_path, "--summary")
    assert "Traceback" not in result.stderr, result.stderr
    count, _, text = result.stdout.strip().partition("|")
    assert count == "-1"  # hygiene.sh renders -1 as "advisory"; 0 would read "clean"
    assert text.startswith("skipped:")


def test_hygiene_sh_runs_extras_on_a_tomllib_interpreter():
    script = HELPER.parent / "hygiene.sh"
    text = script.read_text()
    assert 'helper_row _hygiene_extras.py extras "$TOML_PY"' in text
    assert 'python3 "$HERE/_hygiene_extras.py"' not in text
