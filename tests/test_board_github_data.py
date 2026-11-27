"""The board can be handed the GitHub data it cannot fetch itself.

`_board.py` reads GitHub through `gh api`, and the surface the board is
actually read from — a Claude Code session on a phone — has no `gh`. Its
GitHub access is the `mcp__github__*` tools, which are an **agent** capability:
this script is a subprocess and cannot reach them however it is invoked. So the
`/board` skill fetches and this file renders, and `--github-data` is the seam
between them.

The one invariant these tests exist to protect is the one the 2026-08-26
degraded-render work established, restated for the new path: an endpoint that
was not injected is *could not ask*, never *asked and found nothing*. A seam
that quietly turned a missing key into an empty answer would put the board back
where it started — green because it never looked.

Fixtures only. Nothing here calls GitHub, and `BOARD_GH` is pointed at a
command that does not exist so a leak would fail loudly rather than answer.
"""

import json
import sys
from pathlib import Path

import pytest

BRAIN_HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN_HOME / "board"))

import _board  # noqa: E402

RUNS = "repos/Org/Repo/actions/workflows/nightly.yml/runs?per_page=1"


@pytest.fixture(autouse=True)
def _no_live_gh(monkeypatch):
    """No test here may reach a real `gh`, injected data or not."""
    monkeypatch.setattr(_board, "GH", "gh-does-not-exist-in-tests")
    monkeypatch.setattr(_board, "_INJECTED", None)


def _write(tmp_path, mapping):
    path = tmp_path / "github-data.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    return path


def test_an_injected_endpoint_is_answered_without_gh(tmp_path):
    payload = {"workflow_runs": [{"id": 1, "conclusion": "success"}]}
    _board.load_github_data(_write(tmp_path, {RUNS: payload}))
    assert _board.gh_json([RUNS]) == payload


@pytest.mark.parametrize("injected,endpoint", [
    # The invariant: a miss must not become an empty answer. `None` is what
    # the callers read as *could not ask* — it is why a leg names itself
    # unread rather than reporting zero. An injected map that answered `{}` or
    # `[]` for a key it does not hold would hand the board a confident wrong
    # answer, which is the failure this whole surface was rebuilt to stop.
    pytest.param({RUNS: {"workflow_runs": []}}, "repos/Org/Other/actions/runs",
                 id="an-endpoint-that-was-not-injected"),
    # The gatherer says so explicitly when its own fetch failed.
    pytest.param({RUNS: None}, RUNS, id="an-injected-null"),
    # The dev-box path is untouched: no injected map, so `gh` is consulted —
    # here a command that does not exist, which is exactly the honest `None`.
    pytest.param(None, RUNS, id="without-the-flag-nothing-changes"),
])
def test_could_not_ask_is_none(tmp_path, injected, endpoint):
    if injected is None:
        assert _board._INJECTED is None
    else:
        _board.load_github_data(_write(tmp_path, injected))
    assert _board.gh_json([endpoint]) is None


def test_an_injected_empty_result_is_a_real_answer(tmp_path):
    """And the other half of the distinction: asked, and there was nothing."""
    _board.load_github_data(_write(tmp_path, {RUNS: {"workflow_runs": []}}))
    assert _board.gh_json([RUNS]) == {"workflow_runs": []}


def test_a_malformed_file_fails_loudly_rather_than_degrading(tmp_path):
    """An unreadable map would make every leg read "could not read".

    That renders as a GitHub outage. What actually happened is that the
    gatherer wrote a broken file, and the difference matters to whoever reads
    the board at 8am.
    """
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit):
        _board.load_github_data(bad)

    with pytest.raises(SystemExit):
        _board.load_github_data(tmp_path / "absent.json")

    listy = tmp_path / "listy.json"
    listy.write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit):
        _board.load_github_data(listy)


# --------------------------------------------------------------------------
# Phase 2: versions, community, resume, upkeep
#
# Of the four legs phase 1 left dark, three (versions, community, resume) were
# retired with the agents/workflows simplification: `collect()` no longer runs
# `bin/version_drift.sh`, the community scan or the pending-release search, so
# neither those scripts nor the board need a seam for them. Upkeep is the one
# that still reads GitHub, and it already goes through `gh_json` — so the
# phase-1 seam covers it with one more key and no second shape.
# --------------------------------------------------------------------------

PHASE2_LEGS = ("versions", "community", "resume", "upkeep")


def _remote_collect(monkeypatch):
    """`collect()` as a gh-less session runs it, with only the non-GitHub
    sources (body map, Pages, local subprocess legs) stubbed out."""
    monkeypatch.setattr(_board, "load_policy", dict)
    monkeypatch.setattr(_board, "repo_homes", list)
    monkeypatch.setattr(_board, "derive_org", lambda _homes: "Org")
    monkeypatch.setattr(_board, "fetch_heart_board", lambda *a: {})
    monkeypatch.setattr(_board, "collect_hygiene", lambda _degraded, *_rows: None)
    monkeypatch.setattr(_board, "collect_devbox", lambda: None)
    monkeypatch.setattr(_board, "collect_doors", list)
    return _board.collect()


def _phase2_unread(data):
    return [d for d in data["degraded"] if d.split(":", 1)[0] in PHASE2_LEGS]


def test_a_remote_render_reads_all_four_phase2_legs(tmp_path, monkeypatch):
    """The headline criterion: with `--github-data`, zero of the four unread."""
    _board.load_github_data(_write(tmp_path, {
        # GitHub's search payload, verbatim; the leg reads `total_count`.
        _board.open_issues_endpoint("Org"): {
            "total_count": 17, "incomplete_results": False, "items": []},
    }))

    data = _remote_collect(monkeypatch)

    assert _phase2_unread(data) == [], data["degraded"]
    assert data["open_issues"] == 17
    # The retired legs are compatibility placeholders, never fetched.
    assert data["community"] is None
    assert data["versions"]["stamps"] == []
    assert data["resume"]["pending_prs"] == []


@pytest.mark.parametrize("injected", [
    pytest.param(lambda: {_board.open_issues_endpoint("Org"): None},
                 id="injected-null"),
    # The endpoint absent altogether: honest, and still degraded.
    pytest.param(dict, id="not-injected"),
])
def test_without_the_upkeep_key_the_leg_names_itself_unread(tmp_path, monkeypatch,
                                                           injected):
    """A gatherer that could not ask leaves upkeep dark — and says so, rather
    than reporting zero open issues."""
    _board.load_github_data(_write(tmp_path, injected()))

    data = _remote_collect(monkeypatch)

    assert _phase2_unread(data) == ["upkeep: open-issue count unavailable"]
    assert data["open_issues"] is None
