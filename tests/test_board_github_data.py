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


def test_an_endpoint_that_was_not_injected_is_could_not_ask(tmp_path):
    """The invariant: a miss must not become an empty answer.

    `None` is what the callers read as *could not ask* — it is why a workflow
    row carries `unreadable` rather than "no runs". An injected map that
    answered `{}` or `[]` for a key it does not hold would hand the board a
    confident wrong answer, which is the failure this whole surface was
    rebuilt to stop.
    """
    _board.load_github_data(_write(tmp_path, {RUNS: {"workflow_runs": []}}))
    assert _board.gh_json(["repos/Org/Other/actions/runs"]) is None


def test_an_injected_null_is_still_could_not_ask(tmp_path):
    """The gatherer says so explicitly when its own fetch failed."""
    _board.load_github_data(_write(tmp_path, {RUNS: None}))
    assert _board.gh_json([RUNS]) is None


def test_an_injected_empty_result_is_a_real_answer(tmp_path):
    """And the other half of the distinction: asked, and there was nothing."""
    _board.load_github_data(_write(tmp_path, {RUNS: {"workflow_runs": []}}))
    assert _board.gh_json([RUNS]) == {"workflow_runs": []}


def test_without_the_flag_nothing_changes(tmp_path):
    """The dev-box path is untouched: no injected map, so `gh` is consulted —
    here a command that does not exist, which is exactly the honest `None`."""
    assert _board._INJECTED is None
    assert _board.gh_json([RUNS]) is None


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


def test_the_overnight_leg_renders_live_from_injected_data(tmp_path):
    """End to end on the leg this phase exists for.

    Seven `overnight: could not read …` rows are the largest block of the
    board's eleven dark legs; one injected endpoint turns one of them into a
    real row, with no `gh` anywhere in the process.
    """
    _board.load_github_data(_write(tmp_path, {
        RUNS: {"workflow_runs": [{
            "id": 42,
            "conclusion": "success",
            "status": "completed",
            # `created_at`, not `updated_at`: the row's age comes from this
            # field, and a gatherer that stores the wrong one renders "?" —
            # which reads as a render bug rather than a bad file. Pinned here
            # because the first hand-written fixture got it wrong.
            "created_at": "2026-01-01T00:00:00Z",
            "html_url": "https://example.invalid/run/42",
        }]},
        "repos/Org/Repo/actions/runs/42/jobs": {"jobs": []},
    }))

    degraded = []
    rows = _board.collect_overnight(["Org/Repo:nightly.yml"], "Org", degraded)

    assert len(rows) == 1
    assert rows[0]["unreadable"] is False
    assert rows[0]["conclusion"] == "success"
    assert rows[0]["age_h"] is not None, "the age field the row reads is unset"
    assert not degraded, degraded


def test_an_uninjected_workflow_stays_unreadable_and_degrades(tmp_path):
    """The same call with the endpoint absent: honest, and still degraded."""
    _board.load_github_data(_write(tmp_path, {}))

    degraded = []
    rows = _board.collect_overnight(["Org/Repo:nightly.yml"], "Org", degraded)

    assert rows[0]["unreadable"] is True
    assert degraded, "a leg that could not be read must degrade the render"
