"""Phase 14.1 maintenance finding adapters (PyAutoBrain#731) — read-only.

Witness: fixture boards only (placeholder repo names, nothing read from a real
Heart or the network): key stability across run ids, worktree drift left out,
census/monitoring dedupe, the organ CI-red line, tier floors, the release
adapter against `_green.classify`, and the CLI's dry-run JSON and refusal.
"""

from __future__ import annotations

import copy
import datetime as dt
import io
import json
from contextlib import redirect_stderr, redirect_stdout

import pytest

from _shift_fixtures import _batch  # noqa: F401 — puts the batch package on sys.path
import _green  # noqa: E402
import _maintain  # noqa: E402

NOW = dt.datetime(2026, 11, 27, 15, 0, tzinfo=dt.timezone.utc)
TS = "2026-11-27T14:00:00+00:00"
ORGANS = {"OrganA", "OrganB"}


def _mon(family, subject, status="red", disc="", evidence=None, summary="failure"):
    return {"id": f"{family}:{subject}:{disc}", "family": family, "subject": subject,
            "status": status, "summary": summary, "observed_at": TS, "fresh": True,
            "source": f"snapshot.{family}", "owner": family, "evidence": evidence,
            "action": {"kind": "prompt", "payload": "x"}, "blocked_reason": None}


CENSUS_ROWS = [
    {"repo": "ws_alpha", "entry": "imaging/slow_one", "marker": "SLOW", "date": "2026-07-30",
     "reason": "times out at the 300s cap", "measured": False, "prompt": "Use the bug skill."},
    {"repo": "ws_beta", "entry": "graphical/ep.py", "marker": "NEEDS_FIX", "date": "2026-08-03",
     "reason": "EP parked", "measured": False, "prompt": "Use the bug skill."},
    {"repo": "ws_beta", "entry": "keep/forever.py", "marker": "permanent", "date": "2026-01-01",
     "reason": "by design", "measured": False, "prompt": ""},
]


def _board(run_id=111, census_rows=CENSUS_ROWS):
    smoke_ev = {"entry": "scripts/start_here.py", "python": "3.12", "run_id": run_id,
                "cap_s": 300.0, "exit_code": 1}
    findings = [
        _mon("smoke_timings", "ws_alpha/scripts/start_here.py/3.12", "red", str(run_id),
             smoke_ev, "timed out"),
        _mon("ci_status", "OrganA/workflows/Pages Dashboard", evidence={"conclusion": "failure"}),
        _mon("ci_status", "OrganA", evidence={"conclusion": "failure", "name": "OrganA"}),
        {**_mon("ci_status", "OrganA", "yellow", summary="CI x"), "id": "OrganA:ci"},
        _mon("ci_status", "libalpha/workflows/Tests", evidence={"conclusion": "failure"}),
        _mon("worktree_drift", "libalpha", "red", evidence={"repo": "libalpha", "dirty_files": 3}),
        _mon("repo_state", "OrganB:behind", "yellow", "behind"),
        _mon("ci_timing", "ws_alpha/Smoke Tests", "yellow", evidence={"median_s": 341.0}),
        {**_mon("ci_timing", "CI wall-clock", "yellow"), "id": "ci_timing:coverage"},
        _mon("required_workflow_drift", "libalpha/Tests", "red"),
        _mon("unit_test_timing", "libalpha/test_x.py::test_slow", "red",
             evidence={"repo": "libalpha", "ratio": 3.2}, summary="red"),
        _mon("verify_install", "C", "grey"),
        _mon("smoke_timings", "ws_alpha/scripts/old.py/3.12", "stale", str(run_id)),
    ] + [_mon("no_run_census", f"{r['repo']}/{r['entry']}", "yellow", evidence=dict(r),
              summary=r["reason"]) for r in census_rows if r["marker"] != "permanent"]
    return {"ts": TS, "verdict": "green",
            "monitoring": {"findings": findings},
            "performance": {"no_run": {"rows": census_rows[:1], "totals": {}}}}


def _census():
    return {"ts": TS, "rows": copy.deepcopy(CENSUS_ROWS)}


# --- keys ---------------------------------------------------------------------

def test_key_stable_across_run_ids():
    a = [f.key for f in _maintain.monitoring_findings(_board(run_id=111), ORGANS)]
    b = [f.key for f in _maintain.monitoring_findings(_board(run_id=999), ORGANS)]
    assert a == b
    assert "smoke_timings:ws_alpha/scripts/start_here.py/3.12" in a
    assert not any("111" in k for k in a)


def test_monitoring_key_drops_run_url_and_keeps_named_discriminators():
    f = _mon("ci_timing", "ws_alpha/Smoke", "yellow", "https://example.invalid/runs/7")
    assert _maintain.monitoring_key(f) == "ci_timing:ws_alpha/Smoke"
    f = _mon("repo_state", "OrganB", "yellow", "behind")
    assert _maintain.monitoring_key(f) == "repo_state:OrganB:behind"


def test_worktree_drift_and_local_state_excluded():
    fams = {f.evidence["family"] for f in _maintain.monitoring_findings(_board(), ORGANS)}
    assert "worktree_drift" not in fams and "repo_state" not in fams


def test_grey_stale_and_rollups_left_out():
    keys = [f.key for f in _maintain.monitoring_findings(_board(), ORGANS)]
    assert not any(k.endswith(":coverage") for k in keys)
    assert "verify_install:C" not in keys
    assert "smoke_timings:ws_alpha/scripts/old.py/3.12" not in keys
    # the repo-level CI roll-ups (both spellings) give way to the workflow row
    assert "ci:OrganA" not in keys and "OrganA:ci" not in keys
    assert "ci:OrganA:Pages Dashboard" in keys


# --- census + dedupe ----------------------------------------------------------

def test_census_findings_shape():
    fs = _maintain.census_findings(_census())
    assert [f.key for f in fs] == ["no_run:ws_alpha/imaging/slow_one",
                                   "no_run:ws_beta/graphical/ep.py"]
    f = fs[0]
    assert (f.source, f.repo, f.tier_floor) == ("census", "ws_alpha", "glance")
    assert "no_run.yaml" in f.witness and "smoke cap" in f.witness


def test_census_and_monitoring_dedupe_prefers_census():
    fs = _maintain.collect(census=_census(), board=_board(), organs=ORGANS,
                           sources=("census", "monitoring"))
    keys = [f.key for f in fs]
    assert len(keys) == len(set(keys))
    nr = [f for f in fs if f.key.startswith("no_run:")]
    assert len(nr) == 2 and all(f.source == "census" for f in nr)


# --- tiers ----------------------------------------------------------------------

def test_tier_floors():
    by = {f.key: f for f in _maintain.monitoring_findings(_board(), ORGANS)}
    assert by["ci:OrganA:Pages Dashboard"].tier_floor == "glance"
    assert by["ci:libalpha:Tests"].tier_floor == "judge"
    assert by["required_workflow_drift:libalpha/Tests"].tier_floor == "judge"
    assert by["unit_test_timing:libalpha/test_x.py::test_slow"].tier_floor == "judge"
    assert by["no_run:ws_beta/graphical/ep.py"].tier_floor == "glance"


# --- release ------------------------------------------------------------------

REASONS = [
    {"severity": "red", "text": "libalpha: CI failure", "heart_key": "", "repo": ""},
    {"severity": "red", "text": "OrganA/workflows/Pages Dashboard: failure",
     "heart_key": "", "repo": ""},
    {"severity": "red", "text": "libalpha/test_lib/test_x.py::test_y", "heart_key": "",
     "repo": ""},
    {"severity": "yellow", "text": "libalpha: on branch feature/x (not main)",
     "heart_key": "", "repo": ""},
    {"severity": "stale", "text": "libbeta: CI failure", "heart_key": "", "repo": ""},
    {"severity": "red", "text": "release validation failed", "heart_key": "", "repo": ""},
]


def test_organ_ci_red_line_unmatched_by_green_but_classified_here():
    line = REASONS[1]
    assert [c["rule"] for c in _green.classify(line)] == ["unmatched"]
    fs = _maintain.release_findings({"reasons": [line]}, ORGANS)
    assert [(f.key, f.repo, f.tier_floor) for f in fs] == [
        ("ci:OrganA:Pages Dashboard", "OrganA", "glance")]


def test_release_adapter_matches_green_fixable_set():
    green = {c["key"] for r in REASONS if r["severity"] != "stale"
             for c in _green.classify(r) if c["cls"] == "fixable-dev" and c["key"]}
    fs = _maintain.release_findings({"reasons": REASONS}, ORGANS)
    keys = {f.key for f in fs}
    assert green and green <= keys
    assert keys - green == {"ci:OrganA:Pages Dashboard"}
    assert all(f.tier_floor == "judge" for f in fs if f.repo not in ORGANS)


def test_release_and_monitoring_share_the_ci_key():
    fs = _maintain.collect(board=_board(), heart={"reasons": REASONS[1:2]}, organs=ORGANS)
    assert [f.key for f in fs].count("ci:OrganA:Pages Dashboard") == 1


# --- CLI ----------------------------------------------------------------------

def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = _batch.main(argv)
    return rc, out.getvalue(), err.getvalue()


def test_cli_refuses_without_dry_run():
    rc, out, err = _run(["maintain"])
    assert rc != 0 and "14.2" in err and not out


def test_cli_dry_run_json_shape(tmp_path):
    board, census, heart = tmp_path / "board.json", tmp_path / "census.json", tmp_path / "h.json"
    board.write_text(json.dumps(_board()))
    census.write_text(json.dumps(_census()))
    heart.write_text(json.dumps({"verdict": "RED", "ts": TS,
                                 "red_reasons": [r["text"] for r in REASONS
                                                 if r["severity"] == "red"]}))
    rc, out, _ = _run(["maintain", "--dry-run", "--json", "--board-json", str(board),
                       "--census-json", str(census), "--heart-json", str(heart),
                       "--at", NOW.isoformat()])
    assert rc == 0
    doc = json.loads(out)
    assert doc["dry_run"] is True and doc["count"] == len(doc["findings"]) >= 5
    for f in doc["findings"]:
        assert set(f) == {"key", "source", "repo", "paths", "summary", "witness",
                          "tier_floor", "lane", "evidence"}
        assert f["tier_floor"] in ("glance", "judge") and f["witness"]
    assert {f["source"] for f in doc["findings"]} == {"census", "monitoring", "release"}
    assert doc["reads"]["board"]["age_hours"] == pytest.approx(1.0)


def test_cli_sources_subset_and_bad_source(tmp_path):
    census = tmp_path / "census.json"
    census.write_text(json.dumps(_census()))
    rc, out, _ = _run(["maintain", "--dry-run", "--json", "--sources", "census",
                       "--census-json", str(census)])
    assert rc == 0 and {f["source"] for f in json.loads(out)["findings"]} == {"census"}
    rc, _, err = _run(["maintain", "--dry-run", "--sources", "census,bogus"])
    assert rc != 0 and "bogus" in err


def test_maintain_writes_nothing_and_tick_never_calls_it():
    src = (_maintain.__file__)
    text = open(src, encoding="utf-8").read()
    assert ".write_text(" not in text and "open(" not in text.replace("urlopen(", "")
    import _watch
    import _orchestrator
    for mod in (_watch, _orchestrator):
        assert "_maintain" not in open(mod.__file__, encoding="utf-8").read()
