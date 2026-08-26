"""A board that could not ask must not answer.

In a Claude Code remote session the board's two data sources are both absent:
there is no `gh`, and the sibling GitHub Pages boards are refused by the
environment's egress policy (403 to CONNECT). The render went on regardless and
came out looking healthy — seven scheduled workflows reported "no runs", the
readiness line said "unreachable", and the headline read **clear to work** in
brightgreen. Every one of those is a claim about the world made by a process
that had not been able to query it.

These tests pin the distinction the render now has to keep: *found nothing* and
*could not look* are different answers, and only the first earns a green board.
"""

import json
import sys
import urllib.error
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN_HOME / "board"))

import _board  # noqa: E402


# The published JSON surface's key set, pinned in test_board.py. Built from the
# same list so this file cannot drift into testing a shape the board never emits.
SURFACE_KEYS = {
    "generated", "org", "overnight", "heart", "heart_blockers", "heart_plan",
    "performance",
    "hands", "versions", "community", "resume", "open_issues", "hygiene",
    "devbox", "autonomy", "doors", "boards", "degraded", "history",
}


def _surface(**over):
    """A complete, healthy surface — every key present, nothing wrong."""
    base = {k: None for k in SURFACE_KEYS}
    base.update({
        "generated": "2026-01-01 00:00 UTC",
        "org": "ExampleOrg",
        "overnight": [],
        "heart": {},
        "heart_blockers": [],
        "performance": {},
        # Shapes the render and the verdict actually subscript, kept minimal
        # and healthy so these tests isolate the degradation behaviour.
        "versions": {"drift": [], "consensus": None},
        "community": {},
        "resume": {"counts": {}, "pending_prs": [], "tasks": []},
        "open_issues": {},
        "hygiene": {},
        "autonomy": [],
        "doors": {},
        "boards": {},
        "degraded": [],
        "history": [],
    })
    base.update(over)
    return base


# --------------------------------------------------------------------------
# "no runs" vs "could not ask"
# --------------------------------------------------------------------------

def _row(**over):
    row = {"repo": "Org/Repo", "workflow": "wf.yml", "conclusion": None,
           "age_h": None, "url": None, "blocked": False,
           "blocked_reason": None, "unreadable": False}
    row.update(over)
    return row


def test_a_workflow_with_no_runs_says_so():
    line = _board._overnight_line(_row(unreadable=False))
    assert "no runs" in line


def test_a_workflow_that_could_not_be_read_does_not_claim_no_runs():
    line = _board._overnight_line(_row(unreadable=True))
    assert "no runs" not in line, "an unaskable workflow still reports as empty"
    assert "could not read" in line


def test_the_two_states_render_differently():
    assert _board._overnight_line(_row(unreadable=True)) != \
        _board._overnight_line(_row(unreadable=False))


# --------------------------------------------------------------------------
# The headline is a claim, and must be qualified by what was read
# --------------------------------------------------------------------------

def test_a_complete_board_with_nothing_wrong_is_clear_and_green():
    data = _surface()
    assert _board.headline(data) == "clear to work"
    assert _board.badge_color(data) == "brightgreen"


def test_a_degraded_board_never_claims_an_unqualified_all_clear():
    data = _surface(degraded=["overnight: could not read Org/Repo/wf.yml"])
    head = _board.headline(data)
    assert head != "clear to work"
    assert "partial" in head
    assert "1 leg unread" in head


def test_a_degraded_board_is_not_green():
    """The green badge is the strongest signal the board emits; unread legs
    have not earned it."""
    assert _board.badge_color(_surface(degraded=["a"])) != "brightgreen"


def test_real_findings_still_outrank_degradation():
    """Degradation qualifies the headline; it must not mask an actual blocker."""
    data = _surface(degraded=["a", "b"])
    blocking, attention = ["something is on fire"], []
    _real = _board.verdict
    _board.verdict = lambda d: (blocking, attention)
    try:
        assert _board.badge_color(data) == "red"
        assert "need you" in _board.headline(data)
    finally:
        _board.verdict = _real


def test_banner_appears_at_the_top_not_only_the_foot():
    """A reader who stops after the headline must still learn the render is
    partial — the foot section alone did not reach them."""
    md = _board.render_md(_surface(degraded=["overnight: could not read x"]))
    head, sep, foot = md.partition("## Degraded")
    assert sep, "no Degraded section at all"
    assert "Degraded render" in head, "the banner is not above the sections"
    assert "could not read x" in foot, "the detail left the foot section"


def test_a_healthy_board_carries_no_banner():
    """The banner must mean something; a clean render does not wear one."""
    md = _board.render_md(_surface())
    assert "Degraded render" not in md
    assert "## Degraded" not in md


# --------------------------------------------------------------------------
# Why a published surface could not be read
# --------------------------------------------------------------------------

def test_a_policy_block_is_named_as_one_not_as_a_flake():
    """403 on CONNECT will never succeed on retry — say so, once."""
    reason = _board._fetch_reason(urllib.error.HTTPError(
        "https://example.invalid/board.json", 403, "Forbidden", {}, None))
    assert "network policy" in reason
    assert "allowlist" in reason


def test_a_timeout_is_not_reported_as_a_policy_block():
    reason = _board._fetch_reason(urllib.error.URLError("timed out"))
    assert "network policy" not in reason
    assert "timed out" in reason


def test_fetch_records_its_reason_for_the_caller():
    why = []
    assert _board._fetch_json("http://127.0.0.1:9/nothing.json", why) is None
    assert why, "the caller was given no reason to report"


def test_local_checkout_answers_when_the_published_copy_is_unreachable(tmp_path,
                                                                      monkeypatch):
    """A session holding the checkout can still answer from the tree."""
    repo = "SomeOrgan"
    (tmp_path / repo / "board").mkdir(parents=True)
    (tmp_path / repo / "board" / "board.json").write_text(
        json.dumps({"blockers": [{"text": "from the local tree"}]}))
    monkeypatch.setattr(_board, "PYAUTO_ROOT", tmp_path)

    degraded = []
    board = _board.fetch_heart_board("https://unreachable.invalid", repo, degraded)
    assert board is not None, "held the checkout and still reported nothing"
    assert board["blockers"][0]["text"] == "from the local tree"
    assert degraded, "a fallback answer must still be flagged as degraded"
    assert "local" in degraded[0]
