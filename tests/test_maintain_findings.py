"""Phase 14.1 maintenance finding adapters (PyAutoBrain#731) — read-only.

Witness: fixture boards only (placeholder repo names, nothing read from a real
Heart or the network): key stability across run ids, one key per defect,
excluded families, census rows from every source in one shape, tier floors
(glance only for a census marker removal and an organ's own on-head workflow
red), the release adapter against `_green.classify`, unread and stale reads
never looking all-clear, and the CLI's dry-run JSON and refusal.
"""

from __future__ import annotations

import copy
import datetime as dt
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from _shift_fixtures import _batch  # noqa: F401 — puts the batch package on sys.path
import _green  # noqa: E402
import _maintain  # noqa: E402

BRAIN = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 11, 27, 15, 0, tzinfo=dt.timezone.utc)
TS = "2026-11-27T14:00:00+00:00"
ORGANS = {"OrganA", "OrganB"}


def _mon(family, subject, status="red", disc="", evidence=None, summary="failure",
         fresh=True):
    return {"id": f"{family}:{subject}:{disc}", "family": family, "subject": subject,
            "status": status, "summary": summary, "observed_at": TS, "fresh": fresh,
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
#: Only on the board's monitoring rows, not in the local census file.
BOARD_ONLY_ROW = {"entry": "cluster/start_here", "marker": "SLOW", "date": "2026-09-01",
                  "reason": "takes 120.5s, under the 300s cap", "measured": True,
                  "prompt": "Use the bug skill."}


def _board(run_id=111, census_rows=CENSUS_ROWS, ts=TS):
    smoke_ev = {"entry": "scripts/start_here.py", "python": "3.12", "run_id": run_id,
                "cap_s": 300.0, "exit_code": 1}
    findings = [
        _mon("smoke_timings", "ws_alpha/scripts/start_here.py/3.12", "red", str(run_id),
             smoke_ev, "timed out"),
        _mon("ci_status", "OrganA/workflows/Pages Dashboard",
             evidence={"conclusion": "failure", "on_head": True}),
        _mon("ci_status", "OrganA/workflows/Nightly Release",
             evidence={"conclusion": "failure", "on_head": True}),
        _mon("ci_status", "OrganB/workflows/Dashboard",
             evidence={"conclusion": "failure", "on_head": False}),
        _mon("ci_status", "OrganA", evidence={"conclusion": "failure", "name": "OrganA"}),
        {**_mon("ci_status", "OrganA", "yellow", summary="CI x"), "id": "OrganA:ci"},
        {**_mon("ci_status", "libgamma", "yellow", summary="CI x"), "id": "libgamma:ci"},
        _mon("ci_status", "libalpha/workflows/Tests",
             evidence={"conclusion": "failure", "on_head": True}),
        _mon("worktree_drift", "libalpha", "red", evidence={"repo": "libalpha", "dirty_files": 3}),
        _mon("repo_state", "OrganB:behind", "yellow", "behind"),
        _mon("ci_timing", "ws_alpha/Smoke Tests", "yellow", evidence={"median_s": 341.0}),
        {**_mon("ci_timing", "CI wall-clock", "yellow"), "id": "ci_timing:coverage"},
        _mon("required_workflow_drift", "libalpha/Tests", "red"),
        _mon("version_skew", "ws_alpha", "yellow", fresh=False),
        _mon("unit_test_timing", "libalpha/test_x.py::test_slow", "red",
             evidence={"repo": "libalpha", "ratio": 3.2}, summary="red"),
        _mon("verify_install", "C", "grey"),
        _mon("smoke_timings", "ws_alpha/scripts/old.py/3.12", "stale", str(run_id)),
        _mon("no_run_census", "ws_gamma/cluster/start_here", "yellow",
             evidence=dict(BOARD_ONLY_ROW), summary=BOARD_ONLY_ROW["reason"]),
    ] + [_mon("no_run_census", f"{r['repo']}/{r['entry']}", "yellow", evidence=dict(r),
              summary=r["reason"]) for r in census_rows if r["marker"] != "permanent"]
    return {"ts": ts, "verdict": "green",
            "monitoring": {"findings": findings},
            "performance": {"no_run": {"rows": census_rows[:1], "totals": {}}}}


def _census():
    return {"ts": TS, "rows": copy.deepcopy(CENSUS_ROWS)}


def _keys(fs):
    return [f.key for f in fs]


# --- keys ---------------------------------------------------------------------

def test_key_stable_across_run_ids():
    a = _keys(_maintain.collect(census=_census(), board=_board(run_id=111), organs=ORGANS))
    b = _keys(_maintain.collect(census=_census(), board=_board(run_id=999), organs=ORGANS))
    assert a == b and not any("111" in k for k in a)


def test_monitoring_key_normalisers():
    f = _mon("smoke_timings", "ws_alpha/scripts/x.py/3.12", "red", "4242", {"run_id": 4242})
    assert _maintain.monitoring_key(f) == "smoke_timings:ws_alpha/scripts/x.py"
    f = _mon("ci_timing", "ws_alpha/Smoke", "yellow", "https://example.invalid/runs/7")
    assert _maintain.monitoring_key(f) == "ci_timing:ws_alpha/Smoke"
    f = _mon("repo_state", "OrganB", "yellow", "behind")
    assert _maintain.monitoring_key(f) == "repo_state:OrganB:behind"
    f = {**_mon("ci_status", "libgamma", "yellow"), "id": "libgamma:ci"}
    assert _maintain.monitoring_key(f) == "ci:libgamma"
    f = _mon("ci_status", "libgamma/workflows/ Tests ", "red")
    assert _maintain.monitoring_key(f) == "ci:libgamma:Tests"


def test_one_key_per_defect_repo_ci_gives_way_to_workflow_ci():
    heart = {"reasons": [{"severity": "red", "text": "libalpha: CI failure",
                          "heart_key": "", "repo": ""}]}
    fs = _maintain.collect(board=_board(), heart=heart, organs=ORGANS)
    keys = _keys(fs)
    assert len(keys) == len(set(keys))
    assert "ci:libalpha" not in keys and "ci:libalpha:Tests" in keys
    assert "ci:OrganA" not in keys and "OrganA:ci" not in keys
    assert "ci:libgamma" in keys  # no workflow row for it: the repo row stays


def test_excluded_families_grey_stale_and_rollups():
    fams = {f.evidence["family"] for f in _maintain.monitoring_findings(_board(), ORGANS)}
    assert not fams & {"worktree_drift", "repo_state", "smoke_timings", "unit_test_timing",
                       "ci_timing", "no_run_census", "verify_install"}
    keys = _keys(_maintain.monitoring_findings(_board(), ORGANS))
    assert not any(k.endswith(":coverage") for k in keys)


# --- census -------------------------------------------------------------------

def test_census_findings_shape_and_tiers():
    fs = _maintain.census_findings(_census())
    assert _keys(fs) == ["no_run:ws_alpha/imaging/slow_one", "no_run:ws_beta/graphical/ep.py"]
    assert all(f.tier_floor == "judge" for f in fs)  # unmeasured SLOW, NEEDS_FIX
    f = fs[0]
    assert (f.source, f.repo) == ("census", "ws_alpha")
    assert "no_run.yaml" in f.witness and "smoke cap" in f.witness
    glance = _maintain.census_findings({"rows": [dict(BOARD_ONLY_ROW, repo="ws_gamma")]})
    assert [f.tier_floor for f in glance] == ["glance"]
    over = dict(BOARD_ONLY_ROW, repo="ws_gamma", reason="takes 420.0s, over the 300s cap")
    assert _maintain.census_findings({"rows": [over]})[0].tier_floor == "judge"


def test_census_rows_from_every_source_are_census_findings():
    fs = _maintain.collect(census=_census(), board=_board(), organs=ORGANS,
                           sources=("census", "monitoring"))
    nr = [f for f in fs if f.key.startswith("no_run:")]
    assert len(nr) == 3 and all(f.source == "census" for f in nr)
    assert "no_run:ws_gamma/cluster/start_here" in _keys(nr)
    only = _maintain.collect(census=None, board=_board(), sources=("census",))
    assert {f.source for f in only} == {"census"} and len(only) == 3


# --- tiers ----------------------------------------------------------------------

def test_tier_floors():
    by = {f.key: f for f in _maintain.monitoring_findings(_board(), ORGANS)}
    assert by["ci:OrganA:Pages Dashboard"].tier_floor == "glance"
    assert by["ci:OrganA:Nightly Release"].tier_floor == "judge"   # release execution
    assert by["ci:OrganB:Dashboard"].tier_floor == "judge"         # not on head
    assert by["ci:libalpha:Tests"].tier_floor == "judge"           # not an organ
    assert by["required_workflow_drift:libalpha/Tests"].tier_floor == "judge"
    none = {f.key: f for f in _maintain.monitoring_findings(_board(), set())}
    assert none["ci:OrganA:Pages Dashboard"].tier_floor == "judge"


def test_glance_organs_derived_from_body_map(monkeypatch):
    import _sizing
    specs = {"OrganA": {"category": "organ"},
             "OrganPkg": {"category": "organ", "package": "organpkg"},
             "OrganSelf": {"category": "organ", "organ": "Brain"},
             "libalpha": {"category": "library", "package": "libalpha"}}
    monkeypatch.setattr(_sizing, "_body_map_specs", lambda: specs)
    assert _maintain.glance_organs() == {"OrganA"}


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
    # no on_head evidence in the verdict: judge
    assert [(f.key, f.repo, f.tier_floor) for f in fs] == [
        ("ci:OrganA:Pages Dashboard", "OrganA", "judge")]
    both = _maintain.collect(board=_board(), heart={"reasons": [line]}, organs=ORGANS)
    row = [f for f in both if f.key == "ci:OrganA:Pages Dashboard"]
    assert len(row) == 1 and row[0].source == "monitoring" and row[0].tier_floor == "glance"


def test_release_adapter_matches_green_fixable_set():
    green = {c["key"] for r in REASONS if r["severity"] != "stale"
             for c in _green.classify(r) if c["cls"] == "fixable-dev" and c["key"]}
    fs = _maintain.release_findings({"reasons": REASONS}, ORGANS)
    keys = {f.key for f in fs}
    assert green and green <= keys
    assert keys - green == {"ci:OrganA:Pages Dashboard"}
    assert all(f.tier_floor == "judge" for f in fs)


# --- reads and freshness --------------------------------------------------------

def test_stale_sources_and_not_fresh_rows_flagged():
    fs = _maintain.collect(board=_board(), organs=ORGANS, sources=("monitoring",))
    by = {f.key: f for f in fs}
    assert by["version_skew:ws_alpha"].stale and not by["ci:libalpha:Tests"].stale
    fs = _maintain.collect(board=_board(), organs=ORGANS, sources=("monitoring",),
                           stale_sources={"monitoring"})
    assert all(f.stale for f in fs)


def test_board_over_six_hours_reads_stale():
    old = (NOW - dt.timedelta(hours=7)).isoformat()
    r = _maintain._read(_board(ts=old), "file x", "", 7.0)
    assert r["ok"] and r["stale"]


# --- CLI ----------------------------------------------------------------------

def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = _batch.main(argv)
    return rc, out.getvalue(), err.getvalue()


def _files(tmp_path, verdict="RED", heart_ts=TS):
    board, census, heart = tmp_path / "board.json", tmp_path / "census.json", tmp_path / "h.json"
    board.write_text(json.dumps(_board()))
    census.write_text(json.dumps(_census()))
    heart.write_text(json.dumps({"verdict": verdict, "ts": heart_ts,
                                 "red_reasons": [r["text"] for r in REASONS
                                                 if r["severity"] == "red"]}))
    return board, census, heart


def test_cli_refuses_without_dry_run():
    rc, out, err = _run(["maintain"])
    assert rc != 0 and "14.2" in err and not out


def test_cli_dry_run_json_shape(tmp_path):
    board, census, heart = _files(tmp_path)
    rc, out, _ = _run(["maintain", "--dry-run", "--json", "--board-json", str(board),
                       "--census-json", str(census), "--heart-json", str(heart),
                       "--at", NOW.isoformat()])
    assert rc == 0
    doc = json.loads(out)
    assert doc["dry_run"] is True and doc["unread"] == []
    assert doc["count"] == len(doc["findings"]) >= 5
    for f in doc["findings"]:
        assert set(f) == {"key", "source", "repo", "paths", "summary", "witness",
                          "tier_floor", "lane", "evidence", "stale"}
        assert f["tier_floor"] in ("glance", "judge") and f["witness"]
    assert {f["source"] for f in doc["findings"]} == {"census", "monitoring", "release"}
    for r in doc["reads"].values():
        assert r["ok"] is True and r["stale"] is False
    assert doc["reads"]["monitoring"]["age_hours"] == pytest.approx(1.0)


def test_cli_missing_board_is_unread_not_all_clear(tmp_path):
    rc, out, err = _run(["maintain", "--dry-run", "--json", "--sources", "monitoring",
                         "--board-json", str(tmp_path / "absent.json")])
    doc = json.loads(out)
    assert rc == 3 and doc["unread"] == ["monitoring"] and "not all-clear" in err
    assert doc["reads"]["monitoring"]["ok"] is False
    rc, out, _ = _run(["maintain", "--dry-run", "--sources", "monitoring",
                       "--board-json", str(tmp_path / "absent.json")])
    assert rc == 3 and "UNREAD" in out


def test_cli_unreachable_board_is_unread(monkeypatch):
    monkeypatch.setattr(_maintain, "board_url", lambda: ("https://example.invalid/b.json", ""))
    monkeypatch.setattr(_maintain, "fetch_board", lambda url: (None, "board.json unreachable"))
    rc, out, _ = _run(["maintain", "--dry-run", "--json", "--sources", "monitoring"])
    assert rc == 3 and json.loads(out)["count"] == 0


def test_cli_stale_release_verdict(tmp_path):
    board, census, heart = _files(tmp_path, verdict="STALE")
    rc, out, _ = _run(["maintain", "--dry-run", "--json", "--sources", "release",
                       "--heart-json", str(heart), "--at", NOW.isoformat()])
    r = json.loads(out)["reads"]["release"]
    assert rc == 0 and r["status"] == "stale" and r["stale"] is True
    assert all(f["stale"] for f in json.loads(out)["findings"])
    old = (NOW - dt.timedelta(hours=9)).isoformat()
    board, census, heart = _files(tmp_path, verdict="RED", heart_ts=old)
    rc, out, _ = _run(["maintain", "--dry-run", "--json", "--sources", "release",
                       "--heart-json", str(heart), "--at", NOW.isoformat()])
    assert json.loads(out)["reads"]["release"]["stale"] is True


def test_cli_grey_release_verdict_is_unread(tmp_path):
    heart = tmp_path / "h.json"
    heart.write_text(json.dumps({"status": "grey", "updated": TS, "items": []}))
    rc, out, _ = _run(["maintain", "--dry-run", "--json", "--sources", "release",
                       "--heart-json", str(heart), "--at", NOW.isoformat()])
    assert rc == 3 and json.loads(out)["unread"] == ["release"]


def test_cli_sources_subset_and_bad_source(tmp_path):
    board, census, _h = _files(tmp_path)
    rc, out, _ = _run(["maintain", "--dry-run", "--json", "--sources", "census",
                       "--census-json", str(census), "--board-json", str(board),
                       "--at", NOW.isoformat()])
    doc = json.loads(out)
    assert rc == 0 and {f["source"] for f in doc["findings"]} == {"census"}
    assert doc["count"] == 3  # monitoring's census rows count as census
    rc, _, err = _run(["maintain", "--dry-run", "--sources", "census,bogus"])
    assert rc != 0 and "bogus" in err


def test_batch_help_names_maintain():
    rc_out = io.StringIO()
    with redirect_stdout(rc_out), pytest.raises(SystemExit):
        _batch.main(["--help"])
    assert "batch maintain --dry-run" in rc_out.getvalue()


def test_maintain_writes_nothing_and_tick_never_calls_it():
    text = Path(_maintain.__file__).read_text(encoding="utf-8")
    assert ".write_text(" not in text and "open(" not in text.replace("urlopen(", "")
    import _orchestrator
    import _watch
    for path in (Path(_watch.__file__), Path(_orchestrator.__file__),
                 BRAIN / "bin" / "orchestrator_watch.py"):
        src = path.read_text(encoding="utf-8")
        assert "maintain" not in src and "_maintain" not in src, path
