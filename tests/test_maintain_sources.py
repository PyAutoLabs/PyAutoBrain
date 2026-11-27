"""Phase 14.5 maintenance sources (PyAutoBrain#739): the hygiene ledger and
Heart-flagged slowed CI timings.

Witness: fixture ledgers and boards only (placeholder repo names; nothing
reads the network or a real Heart). Hygiene keys are the ledger's own and stay
stable across reads and line drift; each mode is gated on its own completeness
(partial, unkeyed, not_scanned and absent_repos are listed, never filed and
never cleared, while complete modes file and clear); a stale, missing or
malformed ledger is unread (exit 3), never "0 findings"; tiers (glance for
refs/docstrings/escapes, judge for optdeps/extras and every timing); timing
comes only from rows Heart flags, one key per test or gate whatever the run
id or python version, and a release-verdict timing line about the same test is
deduped into it; the writer's prompt text for both sources.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import re
from contextlib import redirect_stderr, redirect_stdout

import pytest

from _shift_fixtures import _batch  # noqa: F401 — puts the batch package on sys.path
import _maintain  # noqa: E402
import _maintain_write as W  # noqa: E402

L = _maintain._ledger()
NOW = dt.datetime(2026, 11, 27, 15, 0, tzinfo=dt.timezone.utc)
TS = "2026-11-27T14:00:00+00:00"
OK = {"ok": True, "stale": False, "partial": False, "source": "fixture", "age_hours": 1.0}


@pytest.fixture(autouse=True)
def _no_published_ledger(monkeypatch):
    """Never the network: the published hygiene ledger reads as unread."""
    monkeypatch.setattr(_maintain, "ledger_url", lambda: (None, "tests: no ledger URL"))


# --- fixtures -------------------------------------------------------------------

def _rows(shift=0, **over):
    """A HygieneDecision's keyed rows with findings; `shift` moves every line."""
    rows = [
        {"mode": "refs", "status": "finding", "count": 2, "findings": [
            {"repo": "ws_alpha", "file": "README.md", "line": 10 + shift,
             "reference": "old_folder/"},
            {"repo": "ws_alpha", "file": "scripts/README.md", "line": 3 + shift,
             "reference": "gone.py"}]},
        {"mode": "docstrings", "status": "finding", "count": 2, "findings": [
            {"repo": "ws_beta", "file": "scripts/a.py", "line": 5 + shift, "line2": 7 + shift},
            {"repo": "ws_beta", "file": "scripts/a.py", "line": 40 + shift,
             "line2": 42 + shift}]},
        {"mode": "escapes", "status": "finding", "count": 1, "findings": [
            {"repo": "ws_beta", "file": "scripts/b.py", "line": 9 + shift}]},
        {"mode": "optdeps", "status": "finding", "count": 1, "findings": [
            {"workspace": "ws_alpha", "script": "scripts/nufft.py", "line": 2 + shift,
             "dependency": "optdep_x"}]},
        {"mode": "extras", "status": "finding", "count": 1, "findings": [
            {"dependency": "optdep_y", "repos": ["libalpha", "libbeta"],
             "declared_by": ["libalpha"]}]},
        {"mode": "tidy", "status": "debris", "count": 4},
    ]
    for r in rows:
        r.update(over.get(r["mode"], {}))
    return rows


def _line(shift=0, date="2026-11-27", **over):
    return L.day_line(_rows(shift, **over), date, "deadbeef")


def _ledger_file(tmp_path, *lines, name="ledger.jsonl"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(e) + "\n" for e in lines), encoding="utf-8")
    return p


def _mon(family, subject, status="red", disc="", evidence=None, fresh=True):
    return {"id": f"{family}:{subject}:{disc}", "family": family, "subject": subject,
            "status": status, "summary": status, "observed_at": TS, "fresh": fresh,
            "source": f"snapshot.{family}", "owner": family, "evidence": evidence}


T1 = "tests/test_a.py::test_slow[p0]"
T2 = "tests/test_b.py::test_ok"


def _board(run_id=111, ts=TS):
    return {"ts": ts, "performance": {
        "gates": [
            {"repo": "ws_alpha", "workflow": "Smoke Tests", "median_s": 341.0, "state": "warn",
             "spark": "x"},
            {"repo": "ws_beta", "workflow": "Smoke Tests", "median_s": 100.0, "state": "ok"},
        ],
        "scripts": {"slowed": [{"repo": "ws_beta", "entry": "scripts/slow.py",
                                "seconds": 90.0, "prev_s": 20.0, "state": "slowed",
                                "run_id": run_id}],
                    "rows": [{"repo": "ws_beta", "entry": "scripts/fast.py", "seconds": 1.0,
                              "state": "ok", "run_id": run_id},
                             {"repo": "ws_beta", "entry": "scripts/slow.py", "seconds": 90.0,
                              "state": "warn", "run_id": run_id, "python": "3.12"},
                             # flagged, but Heart's monitoring row says the evidence is old
                             {"repo": "ws_gamma", "entry": "scripts/old.py", "seconds": 9.0,
                              "state": "warn", "run_id": run_id}]},
        "unit": {"slowed_tests": [{"repo": "libalpha", "nodeid": T1, "seconds": 5.5,
                                   "prev_s": 1.5, "ratio": 3.2, "state": "warn",
                                   "python": "3.13", "run_id": run_id}],
                 "tests": [{"repo": "libalpha", "nodeid": T2, "seconds": 1.0, "state": "ok",
                            "run_id": run_id},
                           {"repo": "libalpha", "nodeid": T1, "seconds": 5.5,
                            "state": "warn", "run_id": run_id}],
                 "imports": [], "slowed_imports": []}},
        "monitoring": {"findings": [
            _mon("ci_timing", "ws_alpha/Smoke Tests", "yellow",
                 evidence={"repo": "ws_alpha", "workflow": "Smoke Tests", "median_s": 341.0,
                           "baseline_s": 183.0, "ratio": 1.86, "state": "warn"}),
            {**_mon("ci_timing", "CI wall-clock", "yellow"), "id": "ci_timing:coverage"},
            _mon("unit_test_timing", f"libalpha/{T1}", "red",
                 evidence={"repo": "libalpha", "test": T1, "state": "red"}),
            _mon("unit_test_timing", f"libalpha/{T1}/3.13", "yellow", str(run_id),
                 evidence={"run_id": run_id}),
            _mon("unit_test_timing", f"libalpha/{T2}/3.12", "grey", str(run_id)),
            _mon("smoke_timings", "ws_gamma/scripts/old.py/3.12", "stale", str(run_id),
                 evidence={"repo": "ws_gamma", "entry": "scripts/old.py", "state": "warn"},
                 fresh=False),
            _mon("smoke_timings", "ws_gamma/scripts/fresh.py/3.12", "red", str(run_id),
                 evidence={"repo": "ws_gamma", "entry": "scripts/fresh.py", "state": "red"}),
        ]}}


def _keys(fs):
    return [f.key for f in fs]


def _all_hygiene(line):
    return [f for fs in _maintain.hygiene_findings(line).values() for f in fs]


# --- hygiene keys ----------------------------------------------------------------

def test_hygiene_keys_are_the_ledgers_and_stable_across_reads_and_line_drift():
    a = _keys(_all_hygiene(_line(0)))
    b = _keys(_all_hygiene(_line(0)))
    c = _keys(_all_hygiene(_line(57)))
    assert a == b == c
    assert set(a) == {k for ks in _line(0)["findings"].values() for k in ks}
    assert "refs:ws_alpha:README.md:old_folder/" in a
    assert "docstrings:ws_beta:scripts/a.py:adjacent-docstrings" in a  # one per file
    assert "escapes:ws_beta:scripts/b.py:latex-escapes" in a
    assert "optdeps:ws_alpha:scripts/nufft.py:optdep_x" in a
    assert "extras:::optdep_y" in a
    assert not any(re.search(r":\d+$", k) for k in a)


def test_hygiene_sources_are_per_mode_and_tiers():
    by = {f.key: f for f in _all_hygiene(_line())}
    for k, f in by.items():
        mode = k.split(":", 1)[0]
        assert f.source == f"hygiene:{mode}"
        assert f.tier_floor == ("glance" if mode in ("refs", "docstrings", "escapes")
                                else "judge"), k
        assert f.witness == _maintain.HYGIENE_WITNESS
    f = by["refs:ws_alpha:README.md:old_folder/"]
    assert (f.repo, f.paths) == ("ws_alpha", ["README.md"])
    extras = by["extras:::optdep_y"]
    assert extras.repo == "" and "libalpha" in extras.summary
    assert extras.evidence["ledger_evidence"]["declared_by"] == ["libalpha"]


# --- per-mode gating --------------------------------------------------------------

GAPPED = dict(
    refs={"status": "partial"},
    docstrings={"findings": None, "status": "finding"},      # unkeyed
    escapes={"not_scanned": ["ws_gamma"]},
    optdeps={"absent_repos": {"ws_delta": 2}},
)


def test_mode_reads_flag_each_incomplete_mode_and_leave_complete_ones_fresh(tmp_path):
    r = _maintain.load_hygiene(str(_ledger_file(tmp_path, _line(**GAPPED))), now=NOW)
    assert r["ok"] and not r["stale"]
    reads = _maintain.mode_reads(r)
    assert set(reads) == {f"hygiene:{m}" for m in L.KEYED_MODES}
    for mode, word in (("refs", "partial"), ("docstrings", "unkeyed"),
                       ("escapes", "not_scanned"), ("optdeps", "absent_repos")):
        rr = reads[f"hygiene:{mode}"]
        assert rr["ok"] and rr["partial"] and rr["stale"] and word in rr["why"], mode
        assert W.unusable(rr)
    assert not W.unusable(reads["hygiene:extras"])
    fs = {f.key: f for f in _all_hygiene(r["data"])}
    assert fs["extras:::optdep_y"].stale is False
    assert fs["refs:ws_alpha:README.md:old_folder/"].stale is True


def _plain_mind(tmp_path):
    m = tmp_path / "mind"
    for d in ("draft", "active"):
        (m / d).mkdir(parents=True)
    (m / "queue.md").write_text("# Queue\n", encoding="utf-8")
    return m


def test_incomplete_modes_never_file_or_clear_complete_modes_do(tmp_path):
    mind = _plain_mind(tmp_path)
    state = tmp_path / "home" / W.STATE_NAME
    state.parent.mkdir()
    # Keys an earlier run recorded, now absent from the ledger in every mode.
    seeded = {"refs:ws_alpha:old.md:x": "hygiene:refs",
              "escapes:ws_beta:old.py:latex-escapes": "hygiene:escapes",
              "optdeps:ws_alpha:old.py:dep": "hygiene:optdeps",
              "extras:::gone_dep": "hygiene:extras"}
    state.write_text(json.dumps({"version": 1, "migrated": "x", "keys": {
        k: {"first_seen": "t", "last_seen": "t", "source": s} for k, s in seeded.items()}}))
    ledger = _ledger_file(tmp_path, _line(**GAPPED))
    reads, raw, found = _maintain.read_sources(("hygiene",), hygiene_json=str(ledger), now=NOW)
    res = W.file_findings(found, reads, mind, cap=10, state_path=state, now=NOW,
                          present=W.present_keys(raw, reads))
    filed = {r["key"] for r in res["filed"]}
    assert filed == {"extras:::optdep_y"}
    skipped = {r["key"]: r["reason"] for r in res["skipped"]}
    assert all("partial read" in skipped[k] for k in _keys(found) if k not in filed)
    assert res["cleared"] == ["extras:::gone_dep"]
    kept = json.loads(state.read_text())["keys"]
    for k in ("refs:ws_alpha:old.md:x", "escapes:ws_beta:old.py:latex-escapes",
              "optdeps:ws_alpha:old.py:dep"):
        assert k in kept
    assert kept["extras:::optdep_y"]["source"] == "hygiene:extras"


def test_a_complete_clean_mode_clears_and_a_missing_mode_clears_nothing(tmp_path):
    line = _line(refs={"findings": [], "status": "clean", "count": 0})
    del line["status"]["extras"], line["rows"]["extras"], line["findings"]["extras"]
    raw = {**_maintain.hygiene_findings(line)}
    assert raw["hygiene:refs"] == [] and "hygiene:extras" not in raw
    reads = _maintain.mode_reads({"ok": True, "data": line, "source": "f", "age_hours": 1})
    fresh = {s for s, r in reads.items() if not W.unusable(r)}
    assert "hygiene:refs" in fresh and "hygiene:extras" not in fresh


# --- unread ledgers -----------------------------------------------------------------

def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = _batch.main(argv)
    return rc, out.getvalue(), err.getvalue()


@pytest.mark.parametrize("body", [
    None,                                              # no file
    "",                                                # empty
    "<html>not a ledger</html>\n",                     # malformed (an error page)
    json.dumps({"date": "2026-11-24", "rows": {}}) + "\n",  # over the age rule
    json.dumps({"date": "2026-11-29", "rows": {}}) + "\n",  # in the future
])
def test_a_stale_missing_or_unreadable_ledger_is_unread_exit_3(tmp_path, body):
    path = tmp_path / "ledger.jsonl"
    if body is not None:
        path.write_text(body)
    rc, out, err = _run(["maintain", "--dry-run", "--json", "--sources", "hygiene",
                         "--hygiene-json", str(path), "--at", NOW.isoformat()])
    doc = json.loads(out)
    assert rc == 3 and doc["unread"] == ["hygiene"] and doc["count"] == 0
    assert "not all-clear" in err
    assert not any(k.startswith("hygiene:") for k in doc["reads"])


def test_unpublished_ledger_is_unread_not_zero_findings(monkeypatch):
    monkeypatch.setattr(_maintain, "ledger_url",
                        lambda: ("https://pages.invalid/Board/hygiene_ledger.jsonl", ""))
    monkeypatch.setattr(_maintain, "fetch_text",
                        lambda url: (None, f"no hygiene ledger published at {url} (404)"))
    rc, out, _ = _run(["maintain", "--dry-run", "--sources", "hygiene"])
    assert rc == 3 and "UNREAD" in out and "404" in out


def test_ledger_url_is_beside_the_brain_board_from_the_declared_surface(monkeypatch):
    monkeypatch.undo()   # the real `ledger_url`, offline: the base comes from the env
    monkeypatch.setenv("BOARD_PAGES_BASE", "https://pages.invalid")
    brain = (_maintain._green._hf()._board().load_policy().get("boards") or {})["brain"]
    url, why = _maintain.ledger_url()
    assert not why and url == f"https://pages.invalid/{brain}/{L.LEDGER_NAME}"


def test_latest_day_wins_and_a_single_saved_line_reads(tmp_path):
    old, new = _line(date="2026-11-26"), _line(date="2026-11-27", refs={"findings": []})
    r = _maintain.load_hygiene(str(_ledger_file(tmp_path, new, old)), now=NOW)
    assert r["ok"] and r["data"]["date"] == "2026-11-27"
    pretty = tmp_path / "one.json"
    pretty.write_text(json.dumps(old, indent=2))
    r = _maintain.load_hygiene(str(pretty), now=NOW)
    assert r["ok"] and r["data"]["date"] == "2026-11-26"


# --- timing -----------------------------------------------------------------------------

def test_timing_only_from_heart_flagged_rows_with_stable_keys():
    fs = _maintain.timing_findings(_board())
    keys = set(_keys(fs))
    assert keys == {
        "timing:gate:ws_alpha:Smoke Tests",
        "timing:script:ws_beta:scripts/slow.py",
        "timing:unit:libalpha:" + T1,
        "timing:script:ws_gamma:scripts/old.py",
        "timing:script:ws_gamma:scripts/fresh.py",
    }
    assert not any("ws_beta:Smoke" in k or T2 in k or "fast.py" in k for k in keys)
    assert _keys(_maintain.timing_findings(_board(run_id=999))) == _keys(fs)
    assert len(_keys(fs)) == len(keys)   # one key per test, gate and script
    by = {f.key: f for f in fs}
    assert by["timing:script:ws_gamma:scripts/old.py"].stale       # Heart: not fresh
    assert not by["timing:script:ws_gamma:scripts/fresh.py"].stale
    for f in fs:
        assert f.source == "timing" and f.tier_floor == "judge"
        assert f.witness == _maintain.TIMING_WITNESS and "post-merge" in f.witness
    assert by["timing:unit:libalpha:" + T1].paths == ["tests/test_a.py"]
    assert by["timing:unit:libalpha:" + T1].evidence["status"] == "red"
    assert "baseline" in by["timing:gate:ws_alpha:Smoke Tests"].summary


def test_timing_never_reads_the_raw_ranking():
    board = {"ts": TS, "performance": {"unit": {"tests": [
        {"repo": "libalpha", "nodeid": f"tests/t.py::test_{i}", "seconds": 100.0 - i,
         "state": "ok"} for i in range(20)]}, "gates": [], "scripts": {"rows": []}},
             "monitoring": {"findings": []}}
    assert _maintain.timing_findings(board) == []


def test_monitoring_leaves_timing_to_the_timing_source():
    fs = _maintain.collect(board=_board(), sources=("monitoring", "timing"))
    assert all(f.source == "timing" for f in fs if "timing" in f.key)
    assert not any(f.key.startswith(("ci_timing:", "unit_test_timing:", "smoke_timings:"))
                   for f in fs)


TIMING_LINE = {"severity": "red", "text": f"libalpha/{T1}/3.13: red", "heart_key": "",
               "repo": ""}
ROLLUP = {"severity": "yellow", "text": "Unit-test timing: 2 slowed", "heart_key": "",
          "repo": ""}
FAILING = {"severity": "red", "text": "libalpha/tests/test_c.py::test_breaks", "heart_key": "",
           "repo": ""}


def test_release_timing_line_dedupes_into_the_timing_key():
    heart = {"reasons": [TIMING_LINE, ROLLUP, FAILING]}
    raw = _maintain.collect_raw(board=_board(), heart=heart,
                                sources=("release", "timing"))
    rel = _keys(raw["release"])
    assert "test:libalpha/tests/test_a.py" not in rel           # one slow test, one key
    assert "test:libalpha/tests/test_c.py" in rel               # a real failure stays
    assert "timing:unit:libalpha:" + T1 in _keys(raw["timing"])
    # Without the timing source the release line stays, human-only (14.2).
    alone = _maintain.collect_raw(board=_board(), heart=heart, sources=("release",))
    f = next(f for f in alone["release"] if f.key == "test:libalpha/tests/test_a.py")
    assert _maintain.human_only_reason(f).startswith("human-only")


def test_a_release_timing_line_for_an_unflagged_test_stays_human_only():
    # A line that says "timing" is a timing line (14.2), here about a test the
    # timing source does not list: it stays in the release list, human-only.
    heart = {"reasons": [dict(TIMING_LINE,
                              text="libalpha/tests/test_z.py::test_q: unit-test timing red"),
                         ROLLUP]}
    raw = _maintain.collect_raw(board=_board(), heart=heart, sources=("release", "timing"))
    f = next(f for f in raw["release"] if f.key == "test:libalpha/tests/test_z.py")
    assert _maintain.human_only_reason(f)


# --- the writer's text ---------------------------------------------------------------------

def _draft(f, read=OK):
    return W.draft_text(f, read, "2026-11-27", target=f.repo or "workspaces",
                        lane=f.lane, difficulty="small", unattended="never",
                        review_minutes=10)


def test_timing_prompt_action_text_never_says_fix_the_failing_test():
    f = next(f for f in _maintain.timing_findings(_board()) if f.key.startswith("timing:unit"))
    text = _draft(f)
    assert "Consequence: judge" in text and f"Source-key: {f.key}" in text
    assert "investigate whether the slowdown is real" in text.lower()
    assert "re-baseline" in text and "--sources timing" in text
    # Every mention is the prohibition itself (the action line and its evidence copy).
    hits = [m.start() for m in re.finditer("fix the failing test", text)]
    assert hits and all(re.search(r'never \\?"$', text[:i]) for i in hits)
    assert "Filed from the `timing` source" in text and W.source_of(text) == "timing"


def test_hygiene_glance_prompt_carries_the_file_surface_rule():
    f = next(f for f in _all_hygiene(_line()) if f.key.startswith("escapes:"))
    text = _draft(f)
    assert "Consequence: glance" in text and "`scripts/b.py`" in text
    assert "raise `Consequence:` to `judge`" in text and "any other file" in text
    assert "--sources hygiene" in text and "mode is complete" in text
    assert W.source_of(text) == "hygiene:escapes"
    j = next(f for f in _all_hygiene(_line()) if f.key.startswith("extras:"))
    assert "never lower it" in _draft(j) and "Consequence: judge" in _draft(j)


def test_files_hygiene_and_timing_findings_through_the_one_writer(tmp_path):
    mind = _plain_mind(tmp_path)
    board = tmp_path / "board.json"
    board.write_text(json.dumps(_board()))
    ledger = _ledger_file(tmp_path, _line())
    reads, raw, found = _maintain.read_sources(("hygiene", "timing"), board_json=str(board),
                                               hygiene_json=str(ledger), now=NOW)
    res = W.file_findings(found, reads, mind, cap=20, state_path=tmp_path / "s.json",
                          now=NOW, present=W.present_keys(raw, reads))
    filed = {r["key"]: r for r in res["filed"]}
    assert "timing:unit:libalpha:" + T1 in filed
    assert "timing:script:ws_gamma:scripts/old.py" not in filed   # Heart: stale row
    assert filed["escapes:ws_beta:scripts/b.py:latex-escapes"]["tier"] == "glance"
    assert all(r["unattended"] == "never" for r in filed.values() if r["tier"] == "judge")
    again = W.file_findings(found, reads, mind, cap=20, state_path=tmp_path / "s.json",
                            now=NOW, present=W.present_keys(raw, reads))
    assert again["filed"] == []


# --- CLI ----------------------------------------------------------------------------------

def test_cli_defaults_read_all_five_sources_and_two_reads_agree(tmp_path):
    board = tmp_path / "board.json"
    board.write_text(json.dumps(_board()))
    heart = tmp_path / "h.json"
    heart.write_text(json.dumps({"verdict": "GREEN", "ts": TS, "red_reasons": []}))
    ledger = _ledger_file(tmp_path, _line())
    argv = ["maintain", "--dry-run", "--json", "--board-json", str(board),
            "--census-json", str(tmp_path / "absent.json"), "--heart-json", str(heart),
            "--hygiene-json", str(ledger), "--at", NOW.isoformat()]
    rc, out, _ = _run(argv)
    doc = json.loads(out)
    assert rc == 0 and doc["sources"] == list(_maintain.SOURCES)
    assert {"hygiene", "timing"} <= set(doc["sources"])
    srcs = {_maintain.base_source(f["source"]) for f in doc["findings"]}
    assert {"hygiene", "timing"} <= srcs
    rc2, out2, _ = _run(argv)
    assert rc2 == 0
    assert [f["key"] for f in json.loads(out2)["findings"]] == [f["key"] for f in doc["findings"]]
    rc, text, _ = _run([a for a in argv if a != "--json"])
    assert "hygiene:escapes" in text and "timing:unit:libalpha" in text


def test_rank_is_unchanged_for_the_first_three_sources():
    a = _maintain.Finding("a", "release", "r", [], "s", "w", "judge", "any", {})
    b = _maintain.Finding("b", "census", "r", [], "s", "w", "judge", "any", {})
    assert [f.key for f in W.rank([a, b])] == ["b", "a"]
    assert _maintain.SOURCES[:3] == ("census", "monitoring", "release")
    assert _maintain.SOURCES == ("census", "monitoring", "release", "hygiene",
                                            "timing")
