"""Contract tests for the health conductor's verdict footing — in particular
Heart's STALE freshness tier (PyAutoBrain#198).

Hermetic: every test stubs `pyauto-heart` on PATH with a script that echoes a
fabricated readiness payload, so the conductor is exercised end-to-end (through
the vitals faculty, exactly as in production) without touching real Heart state.
`PYAUTO_HEART` points at an empty directory so the optional capability manifest
is absent and triage reasons purely by signal category.

The bug these pin: the conductor walked only `red_reasons` and `yellow_reasons`,
so a STALE-only verdict produced zero triage items, the UNKNOWN recommendation,
and exit 4 — indistinguishable from "Heart unreachable" for a machine caller,
even though AUTONOMY.md leg 4 treats STALE as *passing* the dev-ship gate.
"""

import json
import os
import subprocess
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
BRAIN = BRAIN_HOME / "bin" / "pyauto-brain"
HEALTH_DIR = BRAIN_HOME / "agents" / "conductors" / "health"
HEALTH_SH = (HEALTH_DIR / "health.sh").read_text()
HEALTH_DOC = (HEALTH_DIR / "AGENTS.md").read_text()

# Exit codes are a machine contract: 6 is STALE, and it is deliberately NOT the
# free slot 1 (bash's own generic failure), because STALE passes the ship gate.
EXIT_GREEN, EXIT_YELLOW, EXIT_RED, EXIT_UNKNOWN, EXIT_USAGE, EXIT_STALE = 0, 2, 3, 4, 5, 6

# Reason strings are stubbed Heart output. The repo half of a "<repo>: <problem>"
# reason is deliberately a NEUTRAL placeholder, never a real satellite repo name:
# nothing here asserts on it (the conductor classifies by verdict and reason
# text, not by who reported it), so a real name would be an instance fact the
# tenant firewall counts against organ code for no test value.
STALE_ONLY = {
    "verdict": "stale",
    "score": 75,
    "ts": "2026-08-05T10:00:00+00:00",
    "red_reasons": [],
    "yellow_reasons": [],
    "stale_reasons": [
        "no release validation for current source",
        "install verification not run",
        "library-a: status unknown",
    ],
}


def _run(tmp_path, readiness, *args):
    """Run the health conductor against a stubbed Heart returning ``readiness``."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(exist_ok=True)
    payload = tmp_path / "readiness.json"
    payload.write_text(json.dumps(readiness))
    heart = stub_dir / "pyauto-heart"
    heart.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${1:-}" == "readiness" ]]; then cat "$STUB_READINESS"; fi\n'
        "exit 0\n"
    )
    heart.chmod(0o755)
    empty_heart_repo = tmp_path / "no_heart_checkout"
    empty_heart_repo.mkdir(exist_ok=True)

    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
    env["STUB_READINESS"] = str(payload)
    env["PYAUTO_HEART"] = str(empty_heart_repo)
    return subprocess.run(
        [str(BRAIN), "health", *args], capture_output=True, text=True, env=env,
    )


def _triage(tmp_path, readiness):
    result = _run(tmp_path, readiness, "triage", "--json")
    return json.loads(result.stdout), result.returncode


# --------------------------------------------------------------------------
# 1. the classifier walks stale_reasons
# --------------------------------------------------------------------------

def test_stale_reasons_become_triage_items(tmp_path):
    t, _ = _triage(tmp_path, STALE_ONLY)
    reasons = [it["reason"] for it in t["items"]]
    assert sorted(reasons) == sorted(STALE_ONLY["stale_reasons"])
    assert {it["severity"] for it in t["items"]} == {"stale"}


def test_stale_items_are_evidence_gaps_not_accepted_baseline_gaps(tmp_path):
    """A stale reason is an *action item* (re-run the check), so it must not land
    in the bucket the renderer labels "accept, not action items"."""
    t, _ = _triage(tmp_path, STALE_ONLY)
    assert {it["kind"] for it in t["items"]} == {"evidence-gap"}
    assert t["counts"]["expected_gaps"] == 0
    assert all(it["blocks_green"] for it in t["items"])


def test_stale_counts_are_no_longer_zero(tmp_path):
    """The reported symptom: counts read 0 blockers / 0 warnings / 0 gaps."""
    t, _ = _triage(tmp_path, STALE_ONLY)
    c = t["counts"]
    assert c["evidence_gaps"] == len(STALE_ONLY["stale_reasons"])
    assert (c["blockers"], c["warnings_real"], c["advisory"]) == (0, 0, 0)


# --------------------------------------------------------------------------
# 2. the recommendation chain has a STALE branch
# --------------------------------------------------------------------------

def test_stale_recommendation_is_refresh_not_unknown(tmp_path):
    t, _ = _triage(tmp_path, STALE_ONLY)
    rec = t["recommendation"]
    assert rec["action"] == "refresh-evidence"
    assert rec["headline"].startswith("STALE")
    assert "UNKNOWN" not in rec["headline"]
    assert "could not obtain a verdict" not in rec["detail"]


def test_stale_detail_states_the_tier_semantics(tmp_path):
    """The remedy is re-running the check, never fixing code — and a release
    still needs GREEN even though the dev-ship gate treats STALE as passing."""
    t, _ = _triage(tmp_path, STALE_ONLY)
    detail = t["recommendation"]["detail"].lower()
    assert "missing or expired" in detail
    assert "never a code fix" in detail
    assert "requires green" in detail
    assert "leg 4" in detail


def test_stale_prefers_the_release_validation_gap(tmp_path):
    """Refreshing the hard readiness gate is the leg that makes GREEN reachable,
    so it is recommended ahead of other evidence gaps regardless of input order."""
    t, _ = _triage(tmp_path, STALE_ONLY)
    rec = t["recommendation"]
    assert "no release validation" in rec["headline"]
    assert rec["command"] == "pyauto-brain release validate"


def test_refresh_commands_are_never_invented(tmp_path):
    """A capability Heart exposes no refresh entry point for yields command None
    and says so in prose — the same discipline as the `pyauto-heart fix` topics."""
    t, _ = _triage(tmp_path, {
        "verdict": "stale", "score": 90,
        "red_reasons": [], "yellow_reasons": [],
        "stale_reasons": ["test run stale (12d old)"],
    })
    rec = t["recommendation"]
    assert rec["command"] is None
    assert "no refresh entry point" in rec["detail"]
    assert t["items"][0]["capability"] == "test_run"


def test_stale_verdict_with_no_named_reason_still_recommends_a_refresh(tmp_path):
    """Defensive: a verdict of stale with an empty reason list must not fall
    through to UNKNOWN."""
    t, code = _triage(tmp_path, {
        "verdict": "stale", "score": 80,
        "red_reasons": [], "yellow_reasons": [], "stale_reasons": [],
    })
    assert t["recommendation"]["action"] == "refresh-evidence"
    assert code == EXIT_STALE


# --------------------------------------------------------------------------
# 3. the exit code — distinguishable from unknown by a machine caller
# --------------------------------------------------------------------------

def test_stale_exits_six(tmp_path):
    _, code = _triage(tmp_path, STALE_ONLY)
    assert code == EXIT_STALE


def test_every_verdict_maps_to_a_distinct_exit_code(tmp_path):
    """The point of the fix: "Heart says STALE" and "Heart unreachable" must not
    collapse onto the same code."""
    cases = {
        EXIT_GREEN: {"verdict": "green", "red_reasons": [], "yellow_reasons": [],
                     "stale_reasons": []},
        EXIT_YELLOW: {"verdict": "yellow", "red_reasons": [],
                      "yellow_reasons": ["library-a: uncommitted changes"],
                      "stale_reasons": []},
        EXIT_RED: {"verdict": "red", "red_reasons": ["library-a: CI failing on main"],
                   "yellow_reasons": [], "stale_reasons": []},
        EXIT_UNKNOWN: {},
        EXIT_STALE: STALE_ONLY,
    }
    observed = {expected: _triage(tmp_path, payload)[1]
                for expected, payload in cases.items()}
    assert observed == {code: code for code in cases}


def test_usage_error_stays_five(tmp_path):
    result = _run(tmp_path, STALE_ONLY, "not-a-subcommand")
    assert result.returncode == EXIT_USAGE


def test_stale_exit_code_is_not_the_shell_generic_failure():
    """1 is bash's own generic failure (a missing `_common.sh`, a failed
    `readlink`). STALE passes the dev-ship gate, so a crash must never be
    readable as a passing verdict — hence 6, not the free slot 1."""
    assert EXIT_STALE != 1
    assert "stale) return 6 ;;" in HEALTH_SH
    assert "return 1" not in HEALTH_SH.split("_exit_code_for() {")[1].split("}")[0]


def test_header_exit_code_table_documents_stale():
    """The documented table and `_exit_code_for` must not drift apart."""
    header = HEALTH_SH.split("set -uo pipefail")[0]
    assert "6 stale" in header
    for verdict, code in (("green", 0), ("yellow", 2), ("red", 3), ("unknown", 4)):
        assert f"{code} {verdict}" in header, verdict
    # the rationale for 6 travels with the table, not just the commit message
    assert "PASSING" in header or "passing" in header


def test_agents_doc_documents_the_stale_tier():
    """The conductor's own AGENTS.md is the second copy of the exit-code table
    and the triage taxonomy — both must carry the tier, or a reader is told the
    pre-fix story."""
    assert "`6` stale" in HEALTH_DOC
    assert "**STALE**" in HEALTH_DOC
    assert "Evidence gaps" in HEALTH_DOC
    assert "four kinds" in HEALTH_DOC


# --------------------------------------------------------------------------
# 4. regression guards — the other tiers are untouched, and an older Heart works
# --------------------------------------------------------------------------

def test_heart_without_the_stale_tier_behaves_as_before(tmp_path):
    """A verdict from a Heart predating the tier has no `stale_reasons` key at
    all: the conductor must degrade to the old behaviour, not to UNKNOWN."""
    t, code = _triage(tmp_path, {
        "verdict": "yellow", "score": 70, "red_reasons": [],
        "yellow_reasons": ["no release validation for current source"],
    })
    assert code == EXIT_YELLOW
    assert t["recommendation"]["action"] == "release-validate"
    assert t["counts"]["evidence_gaps"] == 0
    assert t["counts"]["expected_gaps"] == 1


def test_red_still_dominates_a_stale_reason(tmp_path):
    """Heart's precedence is red > yellow > stale; the conductor must adopt it,
    never recommend a refresh while a blocker is open."""
    t, code = _triage(tmp_path, {
        "verdict": "red", "score": 40,
        "red_reasons": ["library-a: CI failing on main"],
        "yellow_reasons": [],
        "stale_reasons": ["install verification not run"],
    })
    assert code == EXIT_RED
    assert t["recommendation"]["action"] == "resolve-blockers"
    assert t["counts"]["blockers"] == 1


def test_yellow_real_warning_still_wins_over_a_stale_reason(tmp_path):
    t, code = _triage(tmp_path, {
        "verdict": "yellow", "score": 60, "red_reasons": [],
        "yellow_reasons": ["library-b: uncommitted changes"],
        "stale_reasons": ["install verification not run"],
    })
    assert code == EXIT_YELLOW
    assert t["recommendation"]["action"] == "resolve-warning"


# --------------------------------------------------------------------------
# 5. the human render
# --------------------------------------------------------------------------

def test_human_render_shows_the_evidence_gap_section(tmp_path):
    result = _run(tmp_path, STALE_ONLY, "triage")
    assert result.returncode == EXIT_STALE
    out = result.stdout
    assert "adopted verdict: STALE" in out
    assert "Evidence gaps (re-run the named check" in out
    assert "3 evidence gap(s)" in out
    # the freshness glyph asserts nothing about the evidence, unlike ✗ / !
    assert "? [validate] no release validation for current source" in out
    assert "pyauto-brain release validate" in out
    assert "UNKNOWN" not in out
