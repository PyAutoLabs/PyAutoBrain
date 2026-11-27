"""The hygiene ledger and the one declared scan set (PyAutoBrain#735, Phase 14.0).

* the ledger (board/_hygiene_ledger.py): one line per UTC day, idempotent on a
  same-day re-run, per-finding keys stable across line drift, a non-empty
  history after two days, and a fetch that fails closed;
* the workflow's write path: a published sidecar, never a commit, with no
  permission beyond what the board already held;
* the scan set: derived from the body map, a declared repository missing on
  disk reported as NOT SCANNED, and references resolved against the tracked
  tree and the declared repo names rather than whatever happens to be on disk.

Fixture names are fakes (demo_workspace, HowToDemo, demo_workspace_test) per
the tenant firewall.
"""

from __future__ import annotations

import io
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest
import yaml

from _helpers import BRAIN_HOME, git_in, load_module

ledger = load_module("_hygiene_ledger", "board/_hygiene_ledger.py")
scan_mod = load_module("_hygiene_scan", "agents/conductors/hygiene/_hygiene_scan.py")
refs = load_module("_hygiene_refs_ledger", "agents/conductors/hygiene/_hygiene_refs.py")

WORKFLOW = BRAIN_HOME / ".github" / "workflows" / "brain_board.yml"


def _refs_row(line_shift=0):
    return {"mode": "refs", "status": "finding", "count": 2, "findings": [
        {"repo": "demo_workspace", "file": "scripts/a.py", "line": 10 + line_shift,
         "reference": "scripts/gone.py", "kind": "dead"},
        {"repo": "demo_workspace", "file": "README.md", "line": 3 + line_shift,
         "reference": "old_folder/", "kind": "dead"},
    ]}


def _rows(refs_count=2, line_shift=0):
    row = _refs_row(line_shift)
    row["count"] = refs_count
    return [
        {"mode": "perf", "status": "deferred"},
        {"mode": "crlf", "status": "clean", "count": 0},
        row,
        {"mode": "escapes", "status": "finding", "count": 1, "findings": [
            {"repo": "demo_workspace", "file": "scripts/b.py", "warned": 2, "silent": 1}]},
        {"mode": "docstrings", "status": "finding", "count": 2, "findings": [
            {"repo": "demo_workspace", "file": "scripts/c.py", "first_line": 1 + line_shift,
             "first_end_line": 3, "second_line": 4, "second_end_line": 6},
            {"repo": "demo_workspace", "file": "scripts/c.py", "first_line": 20 + line_shift,
             "first_end_line": 22, "second_line": 23, "second_end_line": 25}]},
    ]


# ------------------------------------------------------------------ ledger --


def test_same_day_rerun_replaces_the_line_never_adds_one(tmp_path):
    path = tmp_path / ledger.LEDGER_NAME
    ledger.record(path, _rows(refs_count=2), "2026-11-27", "aaa")
    ledger.record(path, _rows(refs_count=5), "2026-11-27", "bbb")
    text = path.read_text().splitlines()
    assert len(text) == 1
    line = json.loads(text[0])
    assert line["date"] == "2026-11-27" and line["sha"] == "bbb"
    assert line["rows"]["refs"] == 5  # the re-run's count, not the first


def test_line_shape_counts_and_keys(tmp_path):
    line = ledger.day_line(_rows(), "2026-11-27", "abc")
    assert set(line) == {"date", "sha", "rows", "findings"}
    assert line["rows"] == {"perf": None, "crlf": 0, "refs": 2, "escapes": 1,
                            "docstrings": 2}
    assert line["findings"]["refs"] == [
        "refs:demo_workspace:README.md:old_folder/",
        "refs:demo_workspace:scripts/a.py:scripts/gone.py",
    ]
    assert line["findings"]["escapes"] == ["escapes:demo_workspace:scripts/b.py:latex-escapes"]
    # Two findings in one file share the file-level key.
    assert line["findings"]["docstrings"] == [
        "docstrings:demo_workspace:scripts/c.py:adjacent-docstrings"]
    assert "crlf" not in line["findings"]  # no per-finding detail, no keys


def test_keys_are_stable_across_line_drift():
    before = ledger.day_line(_rows(), "2026-11-26", None)["findings"]
    after = ledger.day_line(_rows(line_shift=40), "2026-11-27", None)["findings"]
    assert before == after
    for keys in before.values():
        for key in keys:
            assert not any(part.isdigit() for part in key.split(":")), key


def test_other_mode_keys():
    assert ledger.finding_key("optdeps", {"workspace": "w", "script": "s.py",
                                          "dependency": "d", "symbols": ["x"]}) \
        == "optdeps:w:s.py:d"
    assert ledger.finding_key("extras", {"dependency": "d", "declared_by": ["a[x]"],
                                         "repos": ["b", "a"]}) \
        == "extras:a+b:pyproject.toml:d"


def test_history_is_non_empty_after_two_days_with_one_point_per_day(tmp_path):
    path = tmp_path / ledger.LEDGER_NAME
    ledger.record(path, _rows(refs_count=2), "2026-11-26", "a")
    lines = ledger.record(path, _rows(refs_count=7), "2026-11-27", "b")
    hist = ledger.history(lines)
    assert [h["date"] for h in hist] == ["2026-11-26", "2026-11-27"]
    assert ledger.series(hist, "refs") == [2, 7]
    assert "findings" not in hist[0]  # the keys stay in the sidecar
    assert len(ledger.sparkline(ledger.series(hist, "refs"))) == 2
    assert ledger.sparkline([3]) == ""  # one point is not a trend


def test_malformed_ledger_line_is_dropped_not_fatal(tmp_path):
    path = tmp_path / ledger.LEDGER_NAME
    path.write_text('{"date":"2026-11-25","rows":{"refs":1}}\nnot json\n')
    lines = ledger.record(path, _rows(), "2026-11-26", None)
    assert [e["date"] for e in lines] == ["2026-11-25", "2026-11-26"]


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _raiser(error):
    def opener(url, timeout):
        raise error
    return opener


def test_fetch_404_starts_an_empty_ledger(tmp_path):
    out = tmp_path / "l.jsonl"
    err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    assert ledger.fetch("u", out, opener=_raiser(err)) == "absent"
    assert out.read_text() == ""


def test_fetch_success_writes_the_body(tmp_path):
    out = tmp_path / "l.jsonl"
    body = b'{"date":"2026-11-26","rows":{}}\n'
    assert ledger.fetch("u", out, opener=lambda url, timeout: _Response(body)) == "fetched"
    assert out.read_bytes() == body


@pytest.mark.parametrize("error", [
    urllib.error.HTTPError("u", 500, "boom", {}, None),
    urllib.error.URLError("no route"),
])
def test_fetch_fails_closed_on_anything_but_404(tmp_path, error):
    with pytest.raises(urllib.error.URLError):
        ledger.fetch("u", tmp_path / "l.jsonl", opener=_raiser(error))


def test_fetch_cli_exits_nonzero_on_an_unreachable_ledger(tmp_path):
    r = subprocess.run(
        ["python3", str(BRAIN_HOME / "board" / "_hygiene_ledger.py"), "fetch",
         "--url", f"file://{tmp_path}/missing/hygiene_ledger.jsonl",
         "--out", str(tmp_path / "l.jsonl")],
        capture_output=True, text=True)
    assert r.returncode == 1
    assert "refusing to publish" in r.stderr


# ---------------------------------------------------------------- workflow --


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def _steps():
    return _workflow()["jobs"]["publish"]["steps"]


def test_workflow_keeps_read_only_contents_and_never_commits():
    wf = _workflow()
    assert wf["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}
    for job in wf["jobs"].values():
        assert "permissions" not in job  # no job widens the workflow's grant
    for step in _steps():
        run = step.get("run", "")
        assert "git push" not in run and "git commit" not in run, step


def test_workflow_fetches_the_ledger_before_rendering_and_publishes_it():
    steps = _steps()
    names = [s.get("name", "") for s in steps]
    fetch_i = next(i for i, s in enumerate(steps)
                   if "_hygiene_ledger.py fetch" in s.get("run", ""))
    render_i = names.index("render the board")
    deploy_i = next(i for i, s in enumerate(steps) if s.get("id") == "deployment")
    assert fetch_i < render_i < deploy_i
    fetch_run = steps[fetch_i]["run"]
    assert f"/{ledger.LEDGER_NAME}" in fetch_run and "--out hygiene_ledger.jsonl" in fetch_run
    assert "continue-on-error" not in steps[fetch_i]  # fail closed
    env = steps[render_i]["env"]
    assert env["BOARD_HYGIENE_LEDGER"].endswith("/hygiene_ledger.jsonl")
    assert "--apply --out _site" in steps[render_i]["run"]


def test_workflow_clones_every_category_the_workspace_scanners_declare():
    clone = next(s["run"] for s in _steps()
                 if s.get("name", "").startswith("check out the hygiene scan set"))
    for category in scan_mod.USER_FACING_CATEGORIES:
        assert f'"{category}"' in clone, category


# ---------------------------------------------------------------- scan set --


def _mind(root, entries):
    mind = root / "PyAutoMind"
    (mind / ".git").mkdir(parents=True)
    body = "repos:\n" + "".join(
        f"  {name}:\n    category: {category}\n" for name, category in entries)
    (mind / "repos.yaml").write_text(body)


def _workspace(root, name):
    repo = root / name
    (repo / ".git").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "example.py").write_text("pass\n")
    return repo


def test_scan_set_comes_from_the_body_map_and_reports_missing(tmp_path):
    _mind(tmp_path, [("demo_workspace", "workspace"), ("HowToDemo", "howto"),
                     ("demo_workspace_test", "workspace_test")])
    present = _workspace(tmp_path, "demo_workspace")
    _workspace(tmp_path, "undeclared_workspace")  # on disk, not declared
    paths, missing = scan_mod.scan_set(tmp_path)
    assert paths == [present.resolve()]
    assert missing == ["HowToDemo"]


@pytest.mark.parametrize("module", ["_hygiene_refs", "_hygiene_docstrings", "_hygiene_escapes"])
def test_missing_declared_repo_is_not_scanned_never_clean(tmp_path, module):
    _mind(tmp_path, [("demo_workspace", "workspace"), ("HowToDemo", "howto")])
    _workspace(tmp_path, "demo_workspace")
    mod = load_module(f"{module}_t", f"agents/conductors/hygiene/{module}.py")
    row = mod.row_for(tmp_path)
    assert row["not_scanned"] == ["HowToDemo"]
    assert row["status"] == "partial"
    assert "NOT SCANNED" in row["summary"] and "HowToDemo" in row["summary"]


def test_without_a_body_map_the_scan_falls_back_to_disk(tmp_path):
    repo = _workspace(tmp_path, "demo_workspace")
    assert scan_mod.scan_set(tmp_path) == ([repo.resolve()], [])


def _git_workspace(root, name):
    repo = root / name
    (repo / "scripts" / "hpc").mkdir(parents=True)
    git_in(root, "init", "-q", name)
    git_in(repo, "config", "user.email", "t@example.com")
    git_in(repo, "config", "user.name", "T")
    return repo


def test_tracked_file_absent_from_a_sparse_checkout_still_resolves(tmp_path):
    """The cloud board's sparse clone omits extension-less files (`submit`);
    the tracked tree still lists them, so the laptop and the cloud agree."""
    _mind(tmp_path, [("demo_workspace", "workspace")])
    repo = _git_workspace(tmp_path, "demo_workspace")
    (repo / "scripts" / "hpc" / "submit").write_text("#!/bin/sh\n")
    (repo / "scripts" / "hpc" / "run.py").write_text(
        '"""Submit with `scripts/hpc/submit` (see `scripts/hpc/nothere`)."""\n')
    git_in(repo, "add", "-A")
    git_in(repo, "commit", "-q", "-m", "x")
    (repo / "scripts" / "hpc" / "submit").unlink()  # what a sparse clone leaves
    row = refs.row_for(tmp_path)
    dead = {f["reference"] for f in row["findings"]}
    assert "scripts/hpc/submit" not in dead
    assert "scripts/hpc/nothere" in dead  # a genuinely dead ref still is


def test_reference_into_a_declared_but_absent_repo_is_skipped_not_dead(tmp_path):
    _mind(tmp_path, [("demo_workspace", "workspace"),
                     ("demo_workspace_test", "workspace_test")])
    repo = _workspace(tmp_path, "demo_workspace")
    (repo / "scripts" / "example.py").write_text(
        '"""See `demo_workspace_test/scripts/parity/check.py`."""\n')
    row = refs.row_for(tmp_path)
    assert row["findings"] == []
