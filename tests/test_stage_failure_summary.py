"""The nightly page's stage-failure detail line.

Shapes here mirror a REAL `stage_report.json` pulled from the 2026-08-04
release-fidelity run: `summary` counts scripts only, while `failures` also
carries non-script legs with `project: null` + a `reason`. The old inline
formatter mixed the two and printed

    1 failed: <project> database/start_here.py, None verify_install

— a count that disagrees with its own list, and a stringified null.
"""

import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "release"))

import stage_failure_summary as sfs  # noqa: E402


def _report(**over):
    report = {
        "summary": {"failed": 1, "passed": 654, "skipped": 102, "timeout": 0},
        "failures": [
            {
                "project": "libx",
                "script": "/runner/work/checkout/workspace/scripts/guides/results/database/start_here.py",
            },
            {
                "project": None,
                "script": "verify_install",
                "reason": "verify_install FAILED",
            },
        ],
    }
    report.update(over)
    return report


def test_the_two_regressions_are_gone():
    line = sfs.summarise(_report())

    # No stringified null, and the leg is named by its reason.
    assert "None" not in line
    assert "verify_install FAILED" in line
    # The script count still describes only the scripts it introduces.
    assert line.startswith("1 failed: libx database/start_here.py")
    # The leg is a separate segment, so "1 failed" is not read as covering it.
    assert line == "1 failed: libx database/start_here.py; verify_install FAILED"


def test_script_paths_are_shortened_to_their_tail():
    line = sfs.summarise(_report(failures=[
        {"project": "libx", "script": "/a/very/long/runner/path/imaging/modeling.py"},
    ]))
    assert line == "1 failed: libx imaging/modeling.py"


def test_a_check_only_failure_still_reports():
    # No scripts failed (summary all zero) but a leg did — the page must not be
    # blank, or the night looks unexplained.
    line = sfs.summarise({
        "summary": {"failed": 0, "timeout": 0},
        "failures": [{"project": None, "script": "verify_install",
                      "reason": "verify_install FAILED"}],
    })
    assert line == "verify_install FAILED"


def test_a_leg_without_a_reason_falls_back_to_its_name():
    line = sfs.summarise({
        "summary": {},
        "failures": [{"project": None, "script": "some_check"}],
    })
    assert line == "some_check"


def test_long_lists_are_truncated_with_a_count():
    failures = [
        {"project": "libx", "script": f"dir/script_{i}.py"} for i in range(5)
    ]
    line = sfs.summarise({"summary": {"failed": 5}, "failures": failures})
    assert line.startswith("5 failed: libx dir/script_0.py")
    assert line.endswith("+2 more")
    assert "script_3.py" not in line


def test_timeouts_are_named_alongside_failures():
    line = sfs.summarise({"summary": {"failed": 1, "timeout": 2}, "failures": []})
    assert line == "1 failed, 2 timeout"


def test_nothing_nameable_is_an_empty_line_not_an_error():
    assert sfs.summarise({}) == ""
    assert sfs.summarise({"summary": {"failed": 0}, "failures": []}) == ""


def test_malformed_report_does_not_raise():
    # A garbled count or a non-dict failure entry must not cost the whole page.
    line = sfs.summarise({
        "summary": {"failed": "not-a-number", "timeout": None},
        "failures": ["junk", {"project": "libx", "script": "d/s.py"}],
    })
    assert line == "failures: libx d/s.py"


def test_missing_file_prints_nothing_and_exits_zero(tmp_path, capsys):
    assert sfs.main(["prog", str(tmp_path / "absent.json")]) == 0
    assert capsys.readouterr().out == ""


def test_malformed_file_prints_nothing_and_exits_zero(tmp_path, capsys):
    bad = tmp_path / "stage_report.json"
    bad.write_text("{not json")
    assert sfs.main(["prog", str(bad)]) == 0
    assert capsys.readouterr().out == ""


def test_main_prints_the_line_for_a_real_shaped_report(tmp_path, capsys):
    import json

    path = tmp_path / "stage_report.json"
    path.write_text(json.dumps(_report()))
    assert sfs.main(["prog", str(path)]) == 0
    assert capsys.readouterr().out.strip() == (
        "1 failed: libx database/start_here.py; verify_install FAILED"
    )
