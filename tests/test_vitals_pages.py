"""tests/test_vitals_pages.py — the vitals faculty with no Heart CLI.

The faculty used to `exit` when `pyauto-heart` could not be resolved, which is
every web/mobile session — so the ship gate ran with no verdict at all. It now
reads the Heart's PUBLISHED Pages board (`agents/faculties/vitals/_vitals.py`),
and these pin the three things that read must get right:

  * the published verdict, blockers and timestamp are reported, and labelled
    as published rather than live;
  * `--scope` answers the question a branch has — a RepoA branch must not
    acknowledge a RED caused by `repob_workspace` smoke;
  * an unreachable board says UNKNOWN and exits 3. Never a traceback: the
    caller is a gate, and a stack trace is not a verdict.

No network: the one fetch door in `board/_board.py` is monkeypatched to serve
the fixture pages under `tests/fixtures/heart_pages/`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BRAIN_HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN_HOME / "agents" / "faculties" / "vitals"))

import _vitals  # noqa: E402

PAGES = Path(__file__).resolve().parent / "fixtures" / "heart_pages"
BASE = "https://example.invalid"


def _load(name):
    return json.loads((PAGES / name).read_text(encoding="utf-8"))


@pytest.fixture
def published(monkeypatch):
    """Serve the fixture pages through `_board._fetch_json` — the single door
    `fetch_badge` and `fetch_heart_board` both go through, so one patch covers
    the whole read and nothing touches the network."""
    monkeypatch.setenv("BOARD_PAGES_BASE", BASE)

    def fake_fetch(url, why=None):
        name = url.rsplit("/", 1)[-1]
        if (PAGES / name).is_file():
            return _load(name)
        if why is not None:
            why.append("unreachable (fixture has no such page)")
        return None

    monkeypatch.setattr(_vitals._board, "_fetch_json", fake_fetch)
    # The local-checkout fallback would answer from a real sibling PyAutoHeart
    # on a developer box and make the unreachable case untestable.
    monkeypatch.setattr(_vitals._board, "_local_published_json",
                        lambda repo, name: None)


@pytest.fixture
def unreachable(monkeypatch):
    monkeypatch.setenv("BOARD_PAGES_BASE", BASE)

    def dead(url, why=None):
        if why is not None:
            why.append("blocked by this environment's network policy")
        return None

    monkeypatch.setattr(_vitals._board, "_fetch_json", dead)
    monkeypatch.setattr(_vitals._board, "_local_published_json",
                        lambda repo, name: None)


def test_the_published_verdict_is_reported(published, capsys):
    assert _vitals.main([]) == 0
    out = capsys.readouterr().out
    assert "verdict:   RED" in out
    assert "2026-09-17 06:12 UTC" in out
    # the reader must never mistake a publish for a tick
    assert "published" in out.lower() and "not a live tick" in out
    assert "repob_workspace: nightly smoke red" in out


def test_scope_filters_to_the_branch_repo(published, capsys):
    assert _vitals.main(["--scope", "RepoA"]) == 0
    out = capsys.readouterr().out
    # the organism-wide RED is still shown, but it is not RepoA's verdict
    assert "scoped verdict: STALE   (organism-wide: RED)" in out
    assert "RepoA: install verification not run" in out
    assert "repob_workspace" not in out


def test_a_repo_with_no_blocker_is_scoped_green(published, capsys):
    assert _vitals.main(["--scope", "RepoC"]) == 0
    out = capsys.readouterr().out
    assert "scoped verdict: GREEN   (organism-wide: RED)" in out
    assert "in-scope blockers: none" in out


def test_scope_accepts_a_comma_list(published, capsys):
    assert _vitals.main(["--scope", "RepoC,repob_workspace"]) == 0
    out = capsys.readouterr().out
    assert "scoped verdict: RED" in out
    assert "repob_workspace: nightly smoke red" in out


def test_json_carries_both_verdicts(published, capsys):
    assert _vitals.main(["--scope", "RepoA", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "RED"
    assert payload["scoped_verdict"] == "STALE"
    assert payload["scope"] == ["repoa"]
    assert [b["repo"] for b in payload["scoped_blockers"]] == ["RepoA"]
    assert payload["published"] is True
    assert payload["generated"] == "2026-09-17 06:12 UTC"


def test_an_unreachable_board_is_unknown_and_exits_3(unreachable, capsys):
    assert _vitals.main([]) == 3
    out = capsys.readouterr().out
    assert out.startswith("verdict: UNKNOWN (Pages unreachable:")
    assert "network policy" in out


def test_blockers_are_never_capped_out_of_a_scoped_read(published, monkeypatch,
                                                        capsys):
    """`extract_heart_blockers` caps the list for a morning glance. A scoped
    read filters BEFORE that cap, so the one blocker that is yours cannot be
    pushed off the end by unrelated ones."""
    monkeypatch.setattr(_vitals._board, "HEART_BLOCKER_CAP", 1)
    assert _vitals.main(["--scope", "RepoA"]) == 0
    out = capsys.readouterr().out
    assert "RepoA: install verification not run" in out
